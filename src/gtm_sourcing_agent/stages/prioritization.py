"""Stage 8: Candidate Prioritization (A/B/C/D). Never deletes or hides a
candidate — see Architecture §1.1 and prompts/prioritization.md."""

import json

from .. import llm_client, storage
from ..models import CandidatePrioritization


def run(role_id: str, candidate_id: str, *, storage_backend=storage) -> CandidatePrioritization:
    icp = storage_backend.require_section(role_id, "icp")
    candidates = storage_backend.require_section(role_id, "candidates")
    if candidate_id not in candidates:
        raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")

    prompt = llm_client.render_prompt(
        "prioritization.md",
        icp_json=json.dumps(icp),
        candidate_json=json.dumps(candidates[candidate_id]),
    )
    result = llm_client.generate(prompt, CandidatePrioritization, stage="prioritization")
    result.candidate_id = candidate_id
    result.recruiter_decision = None  # only the recruiter sets this, never this stage
    storage_backend.merge_prioritization(role_id, candidate_id, result.model_dump())
    return result


def set_recruiter_decision(role_id: str, candidate_id: str, decision: str, *, storage_backend=storage) -> dict:
    """Phase 6 (docs/product-plan.md): the write path `recruiter_decision`
    never had. Deterministic bookkeeping, not a model call — this field
    is the only thing that can move a candidate out of the active pool
    (Architecture §1.1), and it is only ever set here, by an explicit
    recruiter action, never by run() above. Requires the candidate to
    already be prioritized — there's no decision to attach to a tier
    that doesn't exist yet."""
    state = storage_backend.load_role(role_id)
    prioritizations = state.get("prioritizations") or {}
    if candidate_id not in prioritizations:
        raise ValueError(f"candidate '{candidate_id}' has not been prioritized yet for role '{role_id}'")
    record = dict(prioritizations[candidate_id])
    record["recruiter_decision"] = decision or None
    storage_backend.merge_prioritization(role_id, candidate_id, record)
    return {"candidate_id": candidate_id, "recruiter_decision": record["recruiter_decision"]}
