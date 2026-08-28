"""Thin wrapper around the Anthropic Messages API, used by every stage so
model choice, system prompt, and error handling live in one place
(Architecture §5) instead of being duplicated across stage modules.

Uses `client.messages.parse(..., output_format=<pydantic model>)` —
structured-output enforcement is done server-side against the model's
JSON schema, so `response.parsed_output` is already a validated instance;
stage code never hand-parses free text.
"""

import logging
import os
from typing import TypeVar

import anthropic
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_jinja_env = Environment(loader=FileSystemLoader(PROMPTS_DIR), keep_trailing_newline=True)

DEFAULT_MODEL = "claude-opus-5"
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

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy singleton so importing this module never requires credentials —
    only calling generate() does."""
    global _client
    if _client is None:
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
) -> ModelT:
    """Call Claude with `prompt`, enforce output against `output_model` via
    structured outputs, and return a validated instance.

    `stage` is a free-text label (e.g. "intake", "prioritization") logged
    alongside token usage so a recruiter/operator can see per-stage API
    spend — see docs/implementation-plan.md Phase 6. It has no effect on
    the request itself.

    Raises RuntimeError with a clear cause for auth/permission/rate-limit/
    request errors, or if Claude declines the request (`stop_reason ==
    "refusal"`) — a stage should surface that to the recruiter rather than
    silently producing empty output.
    """
    client = _get_client()
    logger.info(
        "generate start stage=%s model=%s output_model=%s prompt_chars=%d",
        stage or "?", model, output_model.__name__, len(prompt),
    )
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_model,
        )
    except anthropic.AuthenticationError as e:
        raise RuntimeError(
            "Anthropic API authentication failed — check ANTHROPIC_API_KEY."
        ) from e
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
    logger.info(
        "generate done stage=%s model=%s input_tokens=%s output_tokens=%s",
        stage or "?", model, usage.input_tokens, usage.output_tokens,
    )
    return response.parsed_output
