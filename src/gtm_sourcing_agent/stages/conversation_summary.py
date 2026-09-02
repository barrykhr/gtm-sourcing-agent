"""Rolling summary across a candidate's full communication log (email,
WhatsApp, calls) — see prompts/conversation_summary.md. Distinct from
outreach.py (drafts one message) and screening.py (per-candidate
questions): this looks backward across everything already logged, not
forward at what to say or ask next. Runs after every new log entry
(db_storage.log_communication's caller enqueues this), never on its own
schedule.

Unlike every other stage in this package, this one is DB-only: the
communication log is a genuinely relational, append-only table
(models_orm.CommunicationLogEntry) with no file-backend equivalent —
same category as multi-recruiter assignment and the activity log, which
are also db_storage-only concepts never exposed via the file-backed CLI
(storage.py). storage_backend therefore defaults to db_storage, not
storage, and this stage has no CLI pipeline entry."""

import json

from .. import db_storage, llm_client
from ..models import ConversationIntelligence, ConversationSummaryResult


def run(role_id: str, candidate_id: str, *, storage_backend=db_storage) -> ConversationSummaryResult:
    candidate = storage_backend.require_section(role_id, "candidates").get(candidate_id)
    if candidate is None:
        raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
    entries = storage_backend.list_communications(role_id, candidate_id)
    if not entries:
        raise ValueError(f"candidate '{candidate_id}' has no communications logged yet")

    prompt = llm_client.render_prompt(
        "conversation_summary.md",
        candidate_json=json.dumps(candidate),
        entries_json=json.dumps(entries),
    )
    result = llm_client.generate(prompt, ConversationSummaryResult, stage="conversation_summary")
    storage_backend.set_conversation_summary(role_id, candidate_id, result.summary, len(entries))
    return result


def run_intelligence(role_id: str, candidate_id: str, *, storage_backend=db_storage) -> ConversationIntelligence:
    """Conversation Intelligence batch: structured extraction over the
    same communication log `run` above summarizes in prose — current/
    expected comp, notice period, interest level, concerns, risks. Same
    checkpoint as `run`: requires at least one logged communication."""
    candidate = storage_backend.require_section(role_id, "candidates").get(candidate_id)
    if candidate is None:
        raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
    entries = storage_backend.list_communications(role_id, candidate_id)
    if not entries:
        raise ValueError(f"candidate '{candidate_id}' has no communications logged yet")

    prompt = llm_client.render_prompt(
        "conversation_intelligence.md",
        candidate_json=json.dumps(candidate),
        entries_json=json.dumps(entries),
    )
    result = llm_client.generate(prompt, ConversationIntelligence, stage="conversation_intelligence")
    storage_backend.set_conversation_intelligence(role_id, candidate_id, result.model_dump())
    return result
