"""Stage 8: Candidate Prioritization (A/B/C/D). Never deletes or hides a
candidate — see Architecture §1.1 and prompts/prioritization.md."""

import json
from datetime import UTC, datetime

from .. import llm_client, storage
from ..models import CandidatePrioritization


def run(role_id: str, candidate_id: str, *, storage_backend=storage) -> CandidatePrioritization:
    icp = storage_backend.require_section(role_id, "icp")
    candidates = storage_backend.require_section(role_id, "candidates")
    if candidate_id not in candidates:
        raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
    # Re-running this (a "re-rank") replaces the whole prioritization
    # record — carry the recruiter-set fields forward rather than
    # silently wiping a decision or a placement/fee a re-rank has nothing
    # to do with. Only the recruiter's own actions (set_recruiter_decision,
    # set_placement) ever change these.
    existing = (storage_backend.load_role(role_id).get("prioritizations") or {}).get(candidate_id) or {}

    prompt = llm_client.render_prompt(
        "prioritization.md",
        icp_json=json.dumps(icp),
        candidate_json=json.dumps(candidates[candidate_id]),
    )
    result = llm_client.generate(prompt, CandidatePrioritization, stage="prioritization")
    result.candidate_id = candidate_id
    result.recruiter_decision = existing.get("recruiter_decision")
    result.placed = existing.get("placed", False)
    result.placement_fee = existing.get("placement_fee", 0.0)
    result.placed_at = existing.get("placed_at")
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


def set_placement(
    role_id: str, candidate_id: str, *, placed: bool, fee: float = 0.0, storage_backend=storage,
) -> dict:
    """Placement/fee tracking (Batch B): the one outcome this system
    tracks in dollar terms, since "did we place this person and what did
    it earn" is the number a consultancy actually runs on. Same category
    as set_recruiter_decision — deterministic, recruiter-authored, never
    set by a stage or the model. Unplacing (placed=False) clears the fee
    and timestamp rather than leaving a stale figure behind."""
    state = storage_backend.load_role(role_id)
    prioritizations = state.get("prioritizations") or {}
    if candidate_id not in prioritizations:
        raise ValueError(f"candidate '{candidate_id}' has not been prioritized yet for role '{role_id}'")
    record = dict(prioritizations[candidate_id])
    record["placed"] = placed
    record["placement_fee"] = fee if placed else 0.0
    record["placed_at"] = datetime.now(UTC).isoformat() if placed else None
    storage_backend.merge_prioritization(role_id, candidate_id, record)
    return {
        "candidate_id": candidate_id, "placed": record["placed"],
        "placement_fee": record["placement_fee"], "placed_at": record["placed_at"],
    }
