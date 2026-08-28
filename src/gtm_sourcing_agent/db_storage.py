"""SQLite-backed drop-in replacement for storage.py's file backend, with
matching function signatures (Architecture §4 update, Phase 1 of
docs/product-plan.md: "swap the storage backend, keep everything above
it"). Every stage in stages/*.py can use this instead of storage.py via
the storage_backend= kwarg without any other code changing.

Deliberately a parallel, standalone implementation rather than one that
imports from storage.py — storage.py and its 44 original tests stay
completely untouched, so the CLI has zero regression risk from this file
existing. The two modules share logic (merge_section et al. are ~5 lines)
rather than an abstraction; see ARCHITECTURE.md for why premature
abstraction is avoided here.

Phase 2 (candidate intelligence layer, docs/product-plan.md): candidates
and prioritizations are now backed by CandidateEvaluation rows joined to a
CanonicalCandidate (models_orm.py), not generic JobSection blobs — but
load_role()'s return shape is byte-identical to before, so nothing above
this module (stages/*.py, api.py's existing routes) needed to change.
save_role() explicitly skips the "candidates"/"prioritizations" keys for
the same reason: those two are owned by merge_candidate/
merge_prioritization now, never by a generic whole-state write-back.
"""

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db
from .models_orm import ActivityLog, CandidateEvaluation, CanonicalCandidate, Job, JobSection, Task

logger = logging.getLogger(__name__)

# save_role() round-trips whatever load_role() handed back; these two keys
# are reconstructed from CandidateEvaluation rows on every load_role() call
# (see below), so writing them back as generic JobSection blobs would be a
# second, driftable copy of the same data.
_CANDIDATE_OWNED_KEYS = ("candidates", "prioritizations")


def load_role(role_id: str) -> dict[str, Any]:
    """Return the role's current state, or an empty skeleton if this role
    has no job row yet — mirrors storage.load_role exactly."""
    with db.get_session() as session:
        job = session.get(Job, role_id)
        state: dict[str, Any] = {"role_id": role_id, "candidates": {}, "prioritizations": {}}
        if job is None:
            return state
        rows = session.scalars(select(JobSection).where(JobSection.role_id == role_id)).all()
        for row in rows:
            state[row.section_key] = row.data
        evaluations = session.scalars(
            select(CandidateEvaluation).where(CandidateEvaluation.role_id == role_id)
        ).all()
        for ev in evaluations:
            # canonical_candidate_id is additive — not part of storage.py's
            # (file backend's) contract, only present via this DB backend,
            # so the frontend can link a per-job candidate to their global
            # roster profile (Phase 2's cross-job view).
            state["candidates"][ev.candidate_evaluation_id] = {
                **ev.data, "canonical_candidate_id": ev.canonical_candidate_id, "note": ev.note
            }
            if ev.prioritization is not None:
                state["prioritizations"][ev.candidate_evaluation_id] = ev.prioritization
        return state


def save_role(role_id: str, state: dict[str, Any]) -> None:
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            job = Job(role_id=role_id)
            session.add(job)
        else:
            job.updated_at = datetime.now(UTC)
        for key, value in state.items():
            if key == "role_id" or key in _CANDIDATE_OWNED_KEYS:
                continue
            row = session.scalars(
                select(JobSection).where(JobSection.role_id == role_id, JobSection.section_key == key)
            ).first()
            if row is None:
                session.add(JobSection(role_id=role_id, section_key=key, data=value))
            else:
                row.data = value
                row.updated_at = datetime.now(UTC)
        session.commit()


def require_section(role_id: str, key: str) -> Any:
    """Read a section a later stage depends on, raising the same clear
    error storage.require_section does if the upstream checkpoint hasn't
    run yet."""
    state = load_role(role_id)
    value = state.get(key)
    if not value:
        raise ValueError(
            f"role '{role_id}' has no '{key}' yet — run that stage first "
            f"(see README.md pipeline order)"
        )
    return value


def merge_section(role_id: str, key: str, value: Any) -> dict[str, Any]:
    state = load_role(role_id)
    state[key] = value
    save_role(role_id, state)
    return state


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _find_matching_canonical(
    session: Session, name: str, current_company: str, source_url: str
) -> tuple[CanonicalCandidate | None, str]:
    """Dedup heuristic (Phase 2) — deliberately simple and inspectable,
    never silent: exact source_url match first (the one identifier that
    isn't ambiguous), then normalized name+company as a fallback. An O(n)
    scan over all canonical candidates — fine at this phase's scale; add
    normalized indexed columns before this matters. Returns (match, how)
    so callers can log what happened rather than guess."""
    if source_url:
        target = source_url.strip().rstrip("/").lower()
        for c in session.scalars(select(CanonicalCandidate)).all():
            if c.source_url and c.source_url.strip().rstrip("/").lower() == target:
                return c, "source_url"
    if name:
        norm_name, norm_company = _normalize(name), _normalize(current_company)
        for c in session.scalars(select(CanonicalCandidate)).all():
            if _normalize(c.name) == norm_name and _normalize(c.current_company) == norm_company:
                return c, "name+company"
    return None, "new"


def merge_candidate(role_id: str, candidate_id: str, value: dict[str, Any]) -> dict[str, Any]:
    with db.get_session() as session:
        if session.get(Job, role_id) is None:
            session.add(Job(role_id=role_id))
            session.flush()

        existing_eval = session.scalars(
            select(CandidateEvaluation).where(
                CandidateEvaluation.role_id == role_id,
                CandidateEvaluation.candidate_evaluation_id == candidate_id,
            )
        ).first()

        if existing_eval is not None:
            existing_eval.data = value
            existing_eval.updated_at = datetime.now(UTC)
        else:
            name = value.get("name", "")
            current_company = value.get("current_company", "")
            source_url = value.get("source_url", "")
            canonical, match_method = _find_matching_canonical(session, name, current_company, source_url)
            if canonical is None:
                canonical = CanonicalCandidate(
                    id=f"cand-{uuid.uuid4().hex[:12]}",
                    name=name, current_company=current_company,
                    current_title=value.get("current_title", ""), location=value.get("location", ""),
                    source_url=source_url, first_seen_job_id=role_id,
                )
                session.add(canonical)
            else:
                # keep the canonical identity fresh with the latest capture
                canonical.current_company = current_company or canonical.current_company
                canonical.current_title = value.get("current_title") or canonical.current_title
                canonical.location = value.get("location") or canonical.location
                canonical.source_url = source_url or canonical.source_url
                canonical.updated_at = datetime.now(UTC)
            session.flush()  # assign canonical.id before it's used as a FK below
            logger.info(
                "candidate dedup match=%s canonical_id=%s role_id=%s candidate_id=%s",
                match_method, canonical.id, role_id, candidate_id,
            )
            session.add(CandidateEvaluation(
                role_id=role_id, candidate_evaluation_id=candidate_id,
                canonical_candidate_id=canonical.id, data=value,
            ))
        session.commit()
    return load_role(role_id)


def merge_prioritization(role_id: str, candidate_id: str, value: dict[str, Any]) -> dict[str, Any]:
    with db.get_session() as session:
        row = session.scalars(
            select(CandidateEvaluation).where(
                CandidateEvaluation.role_id == role_id,
                CandidateEvaluation.candidate_evaluation_id == candidate_id,
            )
        ).first()
        if row is None:
            raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
        row.prioritization = value
        row.updated_at = datetime.now(UTC)
        session.commit()
    return load_role(role_id)


def set_candidate_note(role_id: str, candidate_id: str, note: str) -> dict[str, Any]:
    """A recruiter's own private impression of a candidate (Phase 10,
    docs/product-plan.md) — deliberately separate from `data` (the
    model's evidence-labeled output) and from `prioritization`'s
    recruiter_decision (a structured pursue/pass/revisit call). This is
    just a place to jot something down; nothing reads it, no stage
    depends on it."""
    with db.get_session() as session:
        row = session.scalars(
            select(CandidateEvaluation).where(
                CandidateEvaluation.role_id == role_id,
                CandidateEvaluation.candidate_evaluation_id == candidate_id,
            )
        ).first()
        if row is None:
            raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
        row.note = note
        row.updated_at = datetime.now(UTC)
        session.commit()
        return {"candidate_id": candidate_id, "note": row.note}


def _job_dict(job: Job) -> dict[str, Any]:
    return {
        "role_id": job.role_id, "title": job.title, "role_family": job.role_family,
        "lifecycle_status": job.lifecycle_status, "owner_email": job.owner_email,
        "created_at": job.created_at, "updated_at": job.updated_at,
    }


def create_job(role_id: str, *, title: str = "", role_family: str = "", owner_email: str = "") -> dict[str, Any]:
    """First-class job creation with display metadata. Not part of
    storage.py's contract — the file backend has no "job shell" concept,
    a role only exists once a section is written. The API's POST /jobs
    needs this so a dashboard has a title to show before intake has run.
    `owner_email` (Phase 10) defaults the job to whoever created it —
    api.py passes the authenticated recruiter's email; left unset for
    calls (e.g. from tests) that don't have one.
    """
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            job = Job(role_id=role_id, title=title or role_id, role_family=role_family, owner_email=owner_email or None)
            session.add(job)
        else:
            if title:
                job.title = title
            if role_family:
                job.role_family = role_family
        session.commit()
        return _job_dict(job)


def list_jobs() -> list[dict[str, Any]]:
    with db.get_session() as session:
        jobs = session.scalars(select(Job).order_by(Job.updated_at.desc())).all()
        return [_job_dict(j) for j in jobs]


# One of these four, never inferred by a stage or the model — a job's
# lifecycle is a recruiter's own call about whether the req is still
# open, same "deterministic, recruiter-authored" category as
# set_recruiter_decision (Architecture §1.1's per-candidate analogue).
JOB_LIFECYCLE_STATUSES = ("OPEN", "ON_HOLD", "FILLED", "CANCELLED")


def set_job_lifecycle(role_id: str, lifecycle_status: str) -> dict[str, Any]:
    if lifecycle_status not in JOB_LIFECYCLE_STATUSES:
        raise ValueError(f"'{lifecycle_status}' is not a valid job status — use one of {JOB_LIFECYCLE_STATUSES}")
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            raise ValueError(f"job '{role_id}' not found")
        job.lifecycle_status = lifecycle_status
        session.commit()
        return _job_dict(job)


def set_job_owner(role_id: str, owner_email: str | None) -> dict[str, Any]:
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            raise ValueError(f"job '{role_id}' not found")
        job.owner_email = owner_email or None
        session.commit()
        return _job_dict(job)


# Sections a role template carries forward — the hiring-strategy work
# (job description, calibration, ICP, talent map/search strategy), never
# anything candidate- or pipeline-specific (candidates/prioritizations are
# owned by merge_candidate, not save_role, so they're never touched here
# regardless; funnel/outreach/chat state is deliberately left off the
# clone — a template is "how to hire for this kind of role again", not
# "this specific search, replayed").
_CLONEABLE_SECTIONS = ("job_description", "calibration", "icp", "talent_map")


def clone_role(
    source_role_id: str, new_role_id: str, *, title: str = "", role_family: str = "", owner_email: str = ""
) -> dict[str, Any]:
    """Role templates (Phase 8, docs/product-plan.md): start a new job from
    an existing one's hiring strategy instead of a blank intake. Pure
    section copy, no model call — deterministic, same category as
    create_job."""
    with db.get_session() as session:
        source_job = session.get(Job, source_role_id)
        if source_job is None:
            raise ValueError(f"job '{source_role_id}' not found")
        source_family = source_job.role_family or ""
    source_state = load_role(source_role_id)
    new_job = create_job(new_role_id, title=title, role_family=role_family or source_family, owner_email=owner_email)
    new_state: dict[str, Any] = {"role_id": new_role_id}
    for key in _CLONEABLE_SECTIONS:
        if source_state.get(key):
            new_state[key] = source_state[key]
    if len(new_state) > 1:  # more than just role_id — something was actually cloned
        save_role(new_role_id, new_state)
    return new_job


def job_exists(role_id: str) -> bool:
    with db.get_session() as session:
        return session.get(Job, role_id) is not None


# ── global candidate roster (Phase 2) ───────────────────────────────────


def _evaluation_summary(ev: CandidateEvaluation, jobs: dict[str, Job]) -> dict[str, Any]:
    p = ev.prioritization or {}
    job = jobs.get(ev.role_id)
    return {
        "role_id": ev.role_id,
        "job_title": job.title if job else ev.role_id,
        "candidate_evaluation_id": ev.candidate_evaluation_id,
        "tier": p.get("tier"),
        "why_they_fit": p.get("why_they_fit"),
        "recruiter_decision": p.get("recruiter_decision"),
    }


def list_canonical_candidates() -> list[dict[str, Any]]:
    """Every canonical candidate with a summary of every job they've been
    evaluated against — the "92% fit Job A, 71% fit Job B, not evaluated
    for Job C" view from the build instruction's §9."""
    with db.get_session() as session:
        jobs = {j.role_id: j for j in session.scalars(select(Job)).all()}
        candidates = session.scalars(
            select(CanonicalCandidate).order_by(CanonicalCandidate.updated_at.desc())
        ).all()
        result = []
        for c in candidates:
            evals = session.scalars(
                select(CandidateEvaluation).where(CandidateEvaluation.canonical_candidate_id == c.id)
            ).all()
            result.append({
                "candidate_id": c.id, "name": c.name, "current_company": c.current_company,
                "current_title": c.current_title, "location": c.location, "source_url": c.source_url,
                "evaluations": [_evaluation_summary(e, jobs) for e in evals],
            })
        return result


def get_canonical_candidate(canonical_id: str) -> dict[str, Any] | None:
    with db.get_session() as session:
        c = session.get(CanonicalCandidate, canonical_id)
        if c is None:
            return None
        jobs = {j.role_id: j for j in session.scalars(select(Job)).all()}
        evals = session.scalars(
            select(CandidateEvaluation).where(CandidateEvaluation.canonical_candidate_id == canonical_id)
        ).all()
        return {
            "candidate_id": c.id, "name": c.name, "current_company": c.current_company,
            "current_title": c.current_title, "location": c.location, "source_url": c.source_url,
            "evaluations": [_evaluation_summary(e, jobs) for e in evals],
        }


# ── global search (Phase 10) ────────────────────────────────────────────
# One query over the two things a recruiter actually looks a workspace
# up by — a job's title/role_id and a candidate's name. Deliberately not
# a full-text index: SQLite LIKE is plenty at this scale, and it keeps
# this dependency-free like everything else in this module.

_SEARCH_RESULT_LIMIT = 10


def search(query: str) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"jobs": [], "candidates": []}
    like = f"%{q}%"
    with db.get_session() as session:
        jobs = session.scalars(
            select(Job)
            .where(Job.title.ilike(like) | Job.role_id.ilike(like))
            .order_by(Job.updated_at.desc())
            .limit(_SEARCH_RESULT_LIMIT)
        ).all()
        candidates = session.scalars(
            select(CanonicalCandidate)
            .where(CanonicalCandidate.name.ilike(like))
            .order_by(CanonicalCandidate.updated_at.desc())
            .limit(_SEARCH_RESULT_LIMIT)
        ).all()
        return {
            "jobs": [{"role_id": j.role_id, "title": j.title} for j in jobs],
            "candidates": [
                {"candidate_id": c.id, "name": c.name, "current_title": c.current_title, "current_company": c.current_company}
                for c in candidates
            ],
        }


# ── cross-job analytics (Phase 6) ───────────────────────────────────────


def analytics_overview() -> dict[str, Any]:
    """Deterministic counting across every job — no model call, same
    discipline as stages/funnel.py's report(). Distinct from the per-job
    Analytics tab (funnel conversion for one role): this is the
    dashboard-level view across the whole roster."""
    with db.get_session() as session:
        total_jobs = len(session.scalars(select(Job)).all())
        total_candidates = len(session.scalars(select(CanonicalCandidate)).all())
        evaluations = session.scalars(select(CandidateEvaluation)).all()

        tier_distribution = {"A": 0, "B": 0, "C": 0, "D": 0, "not_prioritized": 0}
        decisions_recorded = 0
        decisions_pending = 0
        decision_breakdown: dict[str, int] = {}

        for ev in evaluations:
            p = ev.prioritization
            if not p:
                tier_distribution["not_prioritized"] += 1
                continue
            tier = p.get("tier")
            if tier in tier_distribution:
                tier_distribution[tier] += 1
            decision = p.get("recruiter_decision")
            if decision:
                decisions_recorded += 1
                decision_breakdown[decision] = decision_breakdown.get(decision, 0) + 1
            else:
                decisions_pending += 1

        return {
            "total_jobs": total_jobs,
            "total_candidates": total_candidates,
            "total_evaluations": len(evaluations),
            "tier_distribution": tier_distribution,
            "decisions_recorded": decisions_recorded,
            "decisions_pending": decisions_pending,
            "decision_breakdown": decision_breakdown,
        }


_AWAITING_RESPONSE_STAGES = {"CONTACTED", "RESPONDED", "RECRUITER_SCREEN", "HM_INTERVIEW", "FINAL_INTERVIEW"}


def _parse_aware(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def attention_needed(follow_up_threshold_days: int = 3) -> dict[str, Any]:
    """Deterministic scan across every job's funnel data (Phase 8) — same
    "swap what's below" simplicity as analytics_overview(), just
    row-level instead of aggregate. Two lists a recruiter would otherwise
    have to notice by checking every job's Pipeline tab themselves:
    candidates stalled in a stage that's waiting on someone else to
    respond, and any interview scheduled in the future."""
    needs_follow_up: list[dict[str, Any]] = []
    upcoming_interviews: list[dict[str, Any]] = []
    now = datetime.now(UTC)

    for job in list_jobs():
        role_id = job["role_id"]
        state = load_role(role_id)
        candidates = state.get("candidates") or {}
        funnel = state.get("funnel") or {}
        for candidate_id, record in funnel.items():
            history = record.get("stage_history") or []
            if not history:
                continue
            last = history[-1]
            name = (candidates.get(candidate_id) or {}).get("name", candidate_id)
            current_stage = record.get("current_stage", "IDENTIFIED")

            last_at_raw = last.get("at")
            days_in_stage = (now - _parse_aware(last_at_raw)).days if last_at_raw else None
            if (
                current_stage in _AWAITING_RESPONSE_STAGES
                and days_in_stage is not None
                and days_in_stage >= follow_up_threshold_days
            ):
                needs_follow_up.append({
                    "role_id": role_id, "job_title": job["title"], "candidate_id": candidate_id,
                    "candidate_name": name, "current_stage": current_stage, "days_in_stage": days_in_stage,
                })

            scheduled_at_raw = last.get("scheduled_at")
            if scheduled_at_raw and _parse_aware(scheduled_at_raw) > now:
                upcoming_interviews.append({
                    "role_id": role_id, "job_title": job["title"], "candidate_id": candidate_id,
                    "candidate_name": name, "current_stage": current_stage, "scheduled_at": scheduled_at_raw,
                })

    needs_follow_up.sort(key=lambda x: -x["days_in_stage"])
    upcoming_interviews.sort(key=lambda x: x["scheduled_at"])
    return {"needs_follow_up": needs_follow_up, "upcoming_interviews": upcoming_interviews}


# ── background tasks (Phase 4) ──────────────────────────────────────────
# CRUD only — task_queue.py owns *when* a task runs and what "running" a
# given kind means; this module just persists state so the worker thread
# and any number of HTTP request threads can all see the same truth.


def _task_dict(task: Task) -> dict[str, Any]:
    return {
        "task_id": task.id, "role_id": task.role_id, "kind": task.kind, "status": task.status,
        "args": task.args, "result": task.result, "error": task.error,
        "created_at": task.created_at, "updated_at": task.updated_at, "finished_at": task.finished_at,
    }


def create_task(role_id: str, kind: str, args: dict[str, Any]) -> dict[str, Any]:
    with db.get_session() as session:
        task = Task(id=f"task-{uuid.uuid4().hex[:12]}", role_id=role_id, kind=kind, args=args, status="pending")
        session.add(task)
        session.commit()
        return _task_dict(task)


def get_task(task_id: str) -> dict[str, Any] | None:
    with db.get_session() as session:
        task = session.get(Task, task_id)
        return _task_dict(task) if task else None


def list_tasks(role_id: str) -> list[dict[str, Any]]:
    with db.get_session() as session:
        tasks = session.scalars(
            select(Task).where(Task.role_id == role_id).order_by(Task.created_at.desc())
        ).all()
        return [_task_dict(t) for t in tasks]


def update_task(
    task_id: str, *, status: str, result: dict[str, Any] | None = None, error: str | None = None
) -> dict[str, Any]:
    with db.get_session() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise ValueError(f"task '{task_id}' not found")
        task.status = status
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        task.updated_at = datetime.now(UTC)
        if status in ("succeeded", "failed"):
            task.finished_at = datetime.now(UTC)
        session.commit()
        return _task_dict(task)


# ── activity log (Phase 8) ──────────────────────────────────────────────
# Written from api.py's route handlers, the only layer with the
# authenticated user (request.state.user) — never from stages/*.py, which
# stay HTTP-agnostic. Best-effort by design: a logging failure should
# never be the reason a real recruiter action (a decision, a stage move)
# fails, so callers wrap this in a try/except, not the other way around.


def log_activity(
    role_id: str, user_email: str, action: str, *, detail: str = "", candidate_id: str | None = None
) -> dict[str, Any]:
    with db.get_session() as session:
        entry = ActivityLog(
            role_id=role_id, user_email=user_email, action=action, detail=detail, candidate_id=candidate_id
        )
        session.add(entry)
        session.commit()
        return {
            "id": entry.id, "role_id": entry.role_id, "user_email": entry.user_email,
            "action": entry.action, "detail": entry.detail, "candidate_id": entry.candidate_id,
            "created_at": entry.created_at,
        }


def list_activity(role_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with db.get_session() as session:
        rows = session.scalars(
            select(ActivityLog)
            .where(ActivityLog.role_id == role_id)
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": r.id, "role_id": r.role_id, "user_email": r.user_email, "action": r.action,
                "detail": r.detail, "candidate_id": r.candidate_id, "created_at": r.created_at,
            }
            for r in rows
        ]
