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
