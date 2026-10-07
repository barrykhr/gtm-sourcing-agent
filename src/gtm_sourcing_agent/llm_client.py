"""Thin wrapper around the configured LLM provider's structured-output
API, used by every stage so model choice, system prompt, and error
handling live in one place (Architecture §5) instead of being duplicated
across stage modules.

Two providers are supported, chosen via GTM_LLM_PROVIDER (default
"anthropic"): "anthropic" (client.messages.parse) or "openai"
(client.chat.completions.parse). Both return server-side-validated
structured output against output_model's JSON schema — stage code never
hand-parses free text, regardless of which provider is configured.
Every call site in this codebase calls generate() with no model=
override, so this one env var moves the whole app (except
orchestrator.py's AI Copilot, which still talks to Anthropic directly —
its tool-use loop is built on an Anthropic-specific abstraction with no
OpenAI equivalent yet; see its own module docstring).
"""

import logging
import os
from dataclasses import dataclass
from typing import Callable, TypeVar

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_jinja_env = Environment(loader=FileSystemLoader(PROMPTS_DIR), keep_trailing_newline=True)

# "anthropic" (default) or "openai". Read once at import time, same as
# every other env-driven module constant in this codebase (e.g. db.py's
# DATABASE_URL handling) — changing it requires a process restart, not a
# runtime toggle.
LLM_PROVIDER = (os.environ.get("GTM_LLM_PROVIDER") or "anthropic").strip().lower()

# GTM_LLM_MODEL overrides the provider's own default outright (either
# provider, any model string); otherwise each provider gets a sensible
# flagship default. Nothing in this codebase passes generate()'s own
# model= kwarg explicitly, so this one constant is what actually picks
# the model everywhere.
DEFAULT_MODEL = os.environ.get("GTM_LLM_MODEL") or ("gpt-5" if LLM_PROVIDER == "openai" else "claude-sonnet-5")
DEFAULT_MAX_TOKENS = 16000

SYSTEM_PROMPT = (
    "You are a senior recruiting research assistant operating under a strict "
    "evidence-discipline policy. For every candidate-facing fact, label it "
    "VERIFIED (explicitly stated in the source), NOT_STATED (looked for and "
    "absent), or INFERRED (a reasonable read that isn't explicit) — never "
    "present an inferred or absent fact as verified, and never invent "
    "information to fill a gap. You never make a final hiring, rejection, or "
    "send decision — every output is a recommendation for the recruiter, who "
    "remains the decision-maker. Follow the field-level instructions in the "
    "user prompt exactly."
)


@dataclass
class Usage:
    """Provider-agnostic token usage — an on_usage caller (Feature 01's
    agent_observability.py) reads these two fields regardless of which
    provider actually served the request, instead of each caller needing
    to know whether it's looking at an anthropic.types.Usage or an
    openai Completion's usage object (different attribute names on
    each: input_tokens/output_tokens vs. prompt_tokens/completion_tokens)."""

    input_tokens: int
    output_tokens: int


_client = None  # anthropic.Anthropic | openai.OpenAI, set lazily below


def _get_client():
    """Lazy singleton so importing this module never requires
    credentials — only calling generate() does."""
    global _client
    if _client is None:
        if LLM_PROVIDER == "openai":
            import openai

            _client = openai.OpenAI()
        else:
            import anthropic

            _client = anthropic.Anthropic()
    return _client


def render_prompt(template_name: str, **context: object) -> str:
    """Render a prompt template from prompts/<template_name> with the
    given context variables."""
    return _jinja_env.get_template(template_name).render(**context)


def generate(
    prompt: str,
    output_model: type[ModelT],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    stage: str = "",
    on_usage: Callable[[Usage], None] | None = None,
) -> ModelT:
    """Call the configured LLM provider with `prompt`, enforce output
    against `output_model` via structured outputs, and return a
    validated instance.

    `stage` is a free-text label (e.g. "intake", "prioritization") logged
    alongside token usage so a recruiter/operator can see per-stage API
    spend — see docs/implementation-plan.md Phase 6. It has no effect on
    the request itself.

    `on_usage`, if given, is called with a provider-agnostic Usage
    instance before returning — additive-only hook (every existing
    caller omits it and behaves exactly as before) so a caller that
    needs to *persist* usage (Feature 01's agent_observability.py)
    doesn't require widening this function's return type for every
    other caller in the codebase.

    Raises RuntimeError with a clear cause for auth/permission/rate-limit/
    request errors, or if the model declines the request — a stage
    should surface that to the recruiter rather than silently producing
    empty output.
    """
    client = _get_client()
    logger.info(
        "generate start provider=%s stage=%s model=%s output_model=%s prompt_chars=%d",
        LLM_PROVIDER, stage or "?", model, output_model.__name__, len(prompt),
    )

    if LLM_PROVIDER == "openai":
        parsed, usage = _generate_openai(client, prompt, output_model, model, max_tokens)
    else:
        parsed, usage = _generate_anthropic(client, prompt, output_model, model, max_tokens)

    logger.info(
        "generate done provider=%s stage=%s model=%s input_tokens=%s output_tokens=%s",
        LLM_PROVIDER, stage or "?", model, usage.input_tokens, usage.output_tokens,
    )
    if on_usage is not None:
        on_usage(usage)
    return parsed


def _generate_anthropic(
    client, prompt: str, output_model: type[ModelT], model: str, max_tokens: int
) -> tuple[ModelT, Usage]:
    import anthropic

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_model,
        )
    except anthropic.AuthenticationError as e:
        raise RuntimeError("Anthropic API authentication failed — check ANTHROPIC_API_KEY.") from e
    except anthropic.PermissionDeniedError as e:
        raise RuntimeError("Anthropic API key lacks required permissions.") from e
    except anthropic.NotFoundError as e:
        raise RuntimeError(f"Anthropic model '{model}' not found.") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError("Anthropic API rate limit hit — retry later.") from e
    except anthropic.BadRequestError as e:
        raise RuntimeError(f"Anthropic API rejected the request: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Network error calling the Anthropic API.") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}") from e

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        raise RuntimeError(f"Claude declined to generate a response (category={category}).")

    usage = response.usage
    return response.parsed_output, Usage(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)


def _generate_openai(
    client, prompt: str, output_model: type[ModelT], model: str, max_tokens: int
) -> tuple[ModelT, Usage]:
    import openai

    try:
        response = client.chat.completions.parse(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format=output_model,
        )
    except openai.AuthenticationError as e:
        raise RuntimeError("OpenAI API authentication failed — check OPENAI_API_KEY.") from e
    except openai.PermissionDeniedError as e:
        raise RuntimeError("OpenAI API key lacks required permissions.") from e
    except openai.NotFoundError as e:
        raise RuntimeError(f"OpenAI model '{model}' not found.") from e
    except openai.RateLimitError as e:
        raise RuntimeError("OpenAI API rate limit hit — retry later.") from e
    except openai.BadRequestError as e:
        raise RuntimeError(f"OpenAI API rejected the request: {e}") from e
    except openai.APIConnectionError as e:
        raise RuntimeError("Network error calling the OpenAI API.") from e
    except openai.APIStatusError as e:
        raise RuntimeError(f"OpenAI API error ({e.status_code}): {e}") from e

    message = response.choices[0].message
    if message.refusal:
        raise RuntimeError(f"OpenAI declined to generate a response: {message.refusal}")
    if message.parsed is None:
        # Shouldn't happen alongside a non-None refusal check above, but
        # a stage silently getting None back (and crashing on attribute
        # access two frames later with no clue why) is worse than a
        # clear error here.
        raise RuntimeError("OpenAI response did not include structured output.")

    usage = response.usage
    return message.parsed, Usage(input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens)
