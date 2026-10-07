"""Feature 01's observability fix (TALYN_V2_ARCHITECTURE.md §5): every
role-intelligence tool call and every extraction LLM call gets a real,
queryable AgentRun + AgentAction row — request id, org id, user, role,
tool, model, tokens, latency, error. Deliberately scoped to Feature 01's
own tools/stage, not a retrofit of every existing stage call (see
AgentRun's docstring in models_orm.py): this is the first place this gets
persisted at all, not a general observability migration.

One AgentRun per recorded call (1:1 with its AgentAction) rather than
grouping multiple tool calls from one chat turn under a shared run — the
simpler shape still answers "what did Talyn do, and what did it cost",
and nothing here precludes grouping by a request id later if that turns
out to matter.
"""

import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from . import db
from .models_orm import DEFAULT_ORGANIZATION_ID, AgentAction, AgentRun


def record_tool_call(
    *,
    role_id: str | None,
    user_email: str = "",
    agent_name: str = "role_intelligence",
    tool_name: str,
    input_summary: str = "",
    output_summary: str = "",
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: float = 0.0,
    status: str = "succeeded",
    error: str | None = None,
) -> str:
    """Write one AgentRun + its one AgentAction. Returns the run id."""
    run_id = str(uuid.uuid4())
    with db.get_session() as session:
        session.add(AgentRun(
            id=run_id, organization_id=DEFAULT_ORGANIZATION_ID, user_email=user_email,
            role_id=role_id, agent_name=agent_name, status=status, error=error,
            finished_at=None if status == "running" else _now(),
        ))
        session.add(AgentAction(
            agent_run_id=run_id, tool_name=tool_name, input_summary=input_summary[:2000],
            output_summary=output_summary[:2000], model=model,
            input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=latency_ms,
        ))
        session.commit()
    return run_id


def _now():
    from datetime import UTC, datetime
    return datetime.now(UTC)


@contextmanager
def timed_tool_call(
    *, role_id: str | None, user_email: str = "", agent_name: str = "role_intelligence",
    tool_name: str, input_summary: str = "",
) -> Iterator[dict[str, Any]]:
    """Context manager that times a block and records it on exit —
    `result` dict is mutable; the caller sets result["output_summary"]
    (and optionally model/input_tokens/output_tokens) before the block
    ends. An exception inside the block is still recorded, as status
    "failed" with the exception message, and re-raised unchanged."""
    result: dict[str, Any] = {"output_summary": "", "model": "", "input_tokens": 0, "output_tokens": 0}
    started = time.perf_counter()
    try:
        yield result
    except Exception as e:
        record_tool_call(
            role_id=role_id, user_email=user_email, agent_name=agent_name, tool_name=tool_name,
            input_summary=input_summary, output_summary=result.get("output_summary", ""),
            model=result.get("model", ""), input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            latency_ms=(time.perf_counter() - started) * 1000, status="failed", error=str(e),
        )
        raise
    else:
        record_tool_call(
            role_id=role_id, user_email=user_email, agent_name=agent_name, tool_name=tool_name,
            input_summary=input_summary, output_summary=result.get("output_summary", ""),
            model=result.get("model", ""), input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            latency_ms=(time.perf_counter() - started) * 1000, status="succeeded",
        )


def get_agent_runs(role_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    from sqlalchemy import select
    with db.get_session() as session:
        runs = session.scalars(
            select(AgentRun).where(AgentRun.role_id == role_id).order_by(AgentRun.started_at.desc()).limit(limit)
        ).all()
        out = []
        for run in runs:
            actions = session.scalars(select(AgentAction).where(AgentAction.agent_run_id == run.id)).all()
            out.append({
                "id": run.id, "agent_name": run.agent_name, "status": run.status, "error": run.error,
                "user_email": run.user_email, "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "actions": [
                    {
                        "tool_name": a.tool_name, "input_summary": a.input_summary, "output_summary": a.output_summary,
                        "model": a.model, "input_tokens": a.input_tokens, "output_tokens": a.output_tokens,
                        "latency_ms": a.latency_ms,
                    }
                    for a in actions
                ],
            })
        return out
