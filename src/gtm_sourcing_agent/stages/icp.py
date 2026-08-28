"""Stage 3: Ideal Candidate Profile. See prompts/icp.md."""

import json

from .. import llm_client, storage
from ..models import IdealCandidateProfile


def run(role_id: str, *, storage_backend=storage) -> IdealCandidateProfile:
    jd = storage_backend.require_section(role_id, "job_description")
    calibration = storage_backend.require_section(role_id, "calibration")
    prompt = llm_client.render_prompt(
        "icp.md",
        job_description_json=json.dumps(jd),
        calibration_json=json.dumps(calibration),
    )
    result = llm_client.generate(prompt, IdealCandidateProfile, stage="icp")
    storage_backend.merge_section(role_id, "icp", result.model_dump())
    return result


def update_criteria(
    role_id: str, *, must_have: list[str] | None = None, nice_to_have: list[str] | None = None,
    storage_backend=storage,
) -> IdealCandidateProfile:
    """Rubric tuning (Phase 8, docs/product-plan.md): the recruiter's own
    direct edit to the must-have/nice-to-have criteria the model used to
    build this ICP, without going through the chat propose/apply loop —
    this isn't an AI-suggested change needing confirmation, it's the
    recruiter editing their own criteria list, same category as
    set_recruiter_decision. `None` for either list leaves it unchanged;
    an empty list clears it. Requires an ICP to already exist — there's
    nothing to tune before Build ICP has run once."""
    current = storage_backend.require_section(role_id, "icp")
    updated = dict(current)
    if must_have is not None:
        updated["must_have"] = must_have
    if nice_to_have is not None:
        updated["nice_to_have"] = nice_to_have
    storage_backend.merge_section(role_id, "icp", updated)
    return IdealCandidateProfile(**updated)
