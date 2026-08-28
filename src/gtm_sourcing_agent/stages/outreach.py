"""Stage 11: Outreach drafting. Draft only — nothing here sends a
message (Architecture §1.4, §7). See prompts/outreach.md.

mark_sent() (Phase 5, docs/product-plan.md) does not change that: it
never transmits anything either, it only records that the *recruiter*
took the real-world action of reaching out through some channel outside
this product (LinkedIn, their email client, ...) — a deterministic
bookkeeping write triggered by an explicit recruiter click, same
category as funnel.update(), not a stage that calls the model.
"""

import json
from datetime import UTC, datetime

from .. import llm_client, storage
from ..models import OutreachSequence
from ..models.funnel import FUNNEL_STAGE_ORDER
from . import funnel as funnel_stage


def run(role_id: str, candidate_id: str, *, storage_backend=storage) -> OutreachSequence:
    jd = storage_backend.require_section(role_id, "job_description")
    candidates = storage_backend.require_section(role_id, "candidates")
    if candidate_id not in candidates:
        raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")

    prompt = llm_client.render_prompt(
        "outreach.md",
        candidate_json=json.dumps(candidates[candidate_id]),
        job_description_json=json.dumps(jd),
    )
    result = llm_client.generate(prompt, OutreachSequence, stage="outreach")
    result.candidate_id = candidate_id

    state = storage_backend.load_role(role_id)
    state.setdefault("outreach", {})[candidate_id] = result.model_dump()
    storage_backend.save_role(role_id, state)
    return result


def mark_sent(role_id: str, candidate_id: str, *, storage_backend=storage) -> dict:
    """Record that the recruiter actually sent (some form of) outreach to
    this candidate. Requires a draft to already exist — there's nothing
    to mark sent otherwise. If the candidate hasn't reached CONTACTED
    yet, advances them there: a direct, deterministic consequence of the
    recruiter's own click, exactly like manually moving the pipeline
    card would — never skips ahead further than CONTACTED, never moves a
    candidate backward."""
    state = storage_backend.load_role(role_id)
    outreach = state.get("outreach") or {}
    if candidate_id not in outreach:
        raise ValueError(f"candidate '{candidate_id}' has no outreach draft yet for role '{role_id}'")

    sent_at = datetime.now(UTC).isoformat()
    state.setdefault("outreach_log", {})[candidate_id] = {"sent_at": sent_at}
    storage_backend.save_role(role_id, state)

    funnel = state.get("funnel") or {}
    current_stage = (funnel.get(candidate_id) or {}).get("current_stage", "IDENTIFIED")
    if FUNNEL_STAGE_ORDER.index(current_stage) < FUNNEL_STAGE_ORDER.index("CONTACTED"):
        record = funnel_stage.update(
            role_id, candidate_id, "CONTACTED", note="outreach marked sent", storage_backend=storage_backend
        )
        current_stage = record["current_stage"]

    return {"candidate_id": candidate_id, "sent_at": sent_at, "funnel_stage": current_stage}
