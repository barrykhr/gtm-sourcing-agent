"""Covers llm_client.py's provider-switch logic (GTM_LLM_PROVIDER) and
generate()'s OpenAI code path specifically. The Anthropic path has no
direct tests of its own (every stage test mocks generate() itself, same
"no way to test real model behavior without a live key" reasoning as
orchestrator.py's _run_tool_loop) and that's unchanged here — but the
provider-agnostic Usage normalization and error-mapping logic added for
OpenAI support are deterministic Python worth testing against a mocked
client object, never a real API call.
"""

from unittest.mock import MagicMock

import httpx
import openai
import pytest
from pydantic import BaseModel

from gtm_sourcing_agent import llm_client


class _Thing(BaseModel):
    value: str


@pytest.fixture
def openai_provider(monkeypatch):
    """LLM_PROVIDER/DEFAULT_MODEL are read once at import time from env
    vars (see the module docstring) — monkeypatching the module
    attributes directly, not the env vars, is how every other test in
    this repo overrides a similar module-level constant (e.g. db.py's
    DB_PATH in test_db.py)."""
    monkeypatch.setattr(llm_client, "LLM_PROVIDER", "openai")


def _fake_response(*, parsed=None, refusal=None, prompt_tokens=10, completion_tokens=5):
    message = MagicMock()
    message.parsed = parsed
    message.refusal = refusal
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return response


def test_default_model_and_provider_default_to_anthropic(monkeypatch):
    monkeypatch.delenv("GTM_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GTM_LLM_MODEL", raising=False)
    # DEFAULT_MODEL/LLM_PROVIDER are computed once at import time, so this
    # asserts against the module's actual current values rather than
    # re-importing — the real regression this guards is "an existing
    # anthropic-only deployment with no GTM_LLM_PROVIDER set keeps
    # behaving exactly as before", which is what matters, not re-deriving
    # the constant.
    assert llm_client.LLM_PROVIDER == "anthropic"
    assert llm_client.DEFAULT_MODEL == "claude-sonnet-5"


def test_get_client_builds_an_openai_client_when_provider_is_openai(openai_provider, monkeypatch):
    monkeypatch.setattr(llm_client, "_client", None)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-construction-only")
    client = llm_client._get_client()
    assert isinstance(client, openai.OpenAI)


def test_generate_openai_returns_parsed_output(openai_provider, monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.parse.return_value = _fake_response(parsed=_Thing(value="x"))
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)

    result = llm_client.generate("prompt", _Thing, stage="test")

    assert result == _Thing(value="x")


def test_generate_openai_reports_normalized_usage(openai_provider, monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.parse.return_value = _fake_response(
        parsed=_Thing(value="x"), prompt_tokens=123, completion_tokens=45,
    )
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)

    captured = []
    llm_client.generate("prompt", _Thing, on_usage=captured.append)

    assert len(captured) == 1
    assert captured[0].input_tokens == 123
    assert captured[0].output_tokens == 45


def test_generate_openai_passes_system_prompt_response_format_and_token_limit(openai_provider, monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.parse.return_value = _fake_response(parsed=_Thing(value="x"))
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)

    llm_client.generate("the prompt text", _Thing, model="gpt-5", max_tokens=321)

    kwargs = fake_client.chat.completions.parse.call_args.kwargs
    assert kwargs["model"] == "gpt-5"
    assert kwargs["max_completion_tokens"] == 321
    assert kwargs["response_format"] is _Thing
    assert kwargs["messages"][0] == {"role": "system", "content": llm_client.SYSTEM_PROMPT}
    assert kwargs["messages"][1] == {"role": "user", "content": "the prompt text"}


def test_generate_openai_raises_on_refusal(openai_provider, monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.parse.return_value = _fake_response(parsed=None, refusal="can't help with that")
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="declined.*can't help with that"):
        llm_client.generate("prompt", _Thing)


def test_generate_openai_raises_when_parsed_is_missing_with_no_refusal(openai_provider, monkeypatch):
    """Defensive: shouldn't happen given the refusal check above, but a
    stage silently getting None back and crashing on attribute access
    two frames later with no clue why is worse than a clear error here."""
    fake_client = MagicMock()
    fake_client.chat.completions.parse.return_value = _fake_response(parsed=None, refusal=None)
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="structured output"):
        llm_client.generate("prompt", _Thing)


def _httpx_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))


@pytest.mark.parametrize(
    "exc, match",
    [
        (openai.AuthenticationError("bad key", response=_httpx_response(401), body=None), "OPENAI_API_KEY"),
        (openai.PermissionDeniedError("nope", response=_httpx_response(403), body=None), "permissions"),
        (openai.NotFoundError("nope", response=_httpx_response(404), body=None), "not found"),
        (openai.RateLimitError("slow down", response=_httpx_response(429), body=None), "rate limit"),
        (openai.BadRequestError("bad request", response=_httpx_response(400), body=None), "rejected"),
        (openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")), "Network error"),
        (openai.APIStatusError("server exploded", response=_httpx_response(500), body=None), "OpenAI API error"),
    ],
)
def test_generate_openai_maps_sdk_exceptions_to_runtime_error(openai_provider, monkeypatch, exc, match):
    fake_client = MagicMock()
    fake_client.chat.completions.parse.side_effect = exc
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match=match):
        llm_client.generate("prompt", _Thing)
