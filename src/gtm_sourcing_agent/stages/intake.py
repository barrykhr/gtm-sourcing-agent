"""Stage 1: Role Intake & Deconstruction. See prompts/intake.md and
docs/implementation-plan.md Phase 1."""

from .. import llm_client, storage
from ..models import JobDescription


def run(role_id: str, jd_text: str, *, storage_backend=storage) -> JobDescription:
    """`storage_backend` defaults to the file-based storage module (CLI
    behavior, unchanged); the API layer passes db_storage instead — see
    ARCHITECTURE.md §4 update in the Recruiting OS Blueprint."""
    prompt = llm_client.render_prompt("intake.md", jd_text=jd_text)
    result = llm_client.generate(prompt, JobDescription, stage="intake")
    storage_backend.merge_section(role_id, "job_description", result.model_dump())
    return result


EDITABLE_FIELDS = (
    "role_title", "seniority", "geography", "compensation",
    "must_have_requirements", "nice_to_have_requirements",
)


def update_fields(role_id: str, *, storage_backend=storage, **fields: object) -> JobDescription:
    """The recruiter's own direct correction to the "here's what we
    understood" JD review — same category as icp.update_criteria: a
    deterministic edit to the model's already-extracted fields, not an
    AI-suggested change. Only EDITABLE_FIELDS may be set this way; a key
    outside that set is a programming error, not a recruiter input, so it
    raises rather than silently being accepted or ignored. `None` for a
    given field leaves it unchanged. Requires the JD to already exist —
    there's nothing to correct before Analyse JD has run once."""
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"not an editable job-description field: {', '.join(sorted(unknown))}")
    current = storage_backend.require_section(role_id, "job_description")
    updated = dict(current)
    for key, value in fields.items():
        if value is not None:
            updated[key] = value
    storage_backend.merge_section(role_id, "job_description", updated)
    return JobDescription(**updated)
