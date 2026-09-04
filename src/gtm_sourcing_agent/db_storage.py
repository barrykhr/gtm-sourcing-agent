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
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db, revenue
from .models_orm import (
    ActivityLog, CandidateEvaluation, CanonicalCandidate, CommunicationLogEntry, Job, JobRecruiter, JobSection,
    Task, User,
)

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
        client_shares = state.get("client_shares") or {}
        conversation_intelligence = state.get("conversation_intelligence") or {}
        evaluations = session.scalars(
            select(CandidateEvaluation).where(CandidateEvaluation.role_id == role_id)
        ).all()
        for ev in evaluations:
            # canonical_candidate_id is additive — not part of storage.py's
            # (file backend's) contract, only present via this DB backend,
            # so the frontend can link a per-job candidate to their global
            # roster profile (Phase 2's cross-job view).
            state["candidates"][ev.candidate_evaluation_id] = {
                **ev.data, "canonical_candidate_id": ev.canonical_candidate_id, "note": ev.note,
                "phone": ev.phone, "email": ev.email,
                "resume_file_key": ev.resume_file_key, "resume_filename": ev.resume_filename,
                "conversation_summary": ev.conversation_summary,
                "conversation_summary_updated_at": (
                    ev.conversation_summary_updated_at.isoformat() if ev.conversation_summary_updated_at else None
                ),
                "conversation_summary_entry_count": ev.conversation_summary_entry_count,
                "client_visible": bool(client_shares.get(ev.candidate_evaluation_id)),
                "conversation_intelligence": conversation_intelligence.get(ev.candidate_evaluation_id),
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


def set_candidate_contact(role_id: str, candidate_id: str, *, phone: str | None = None, email: str | None = None) -> dict[str, Any]:
    """Contact info for the WhatsApp/call handoff — recruiter-entered or
    confirmed, same category as set_candidate_note above. `None` for a
    field leaves it unchanged; pass "" explicitly to clear one."""
    with db.get_session() as session:
        row = session.scalars(
            select(CandidateEvaluation).where(
                CandidateEvaluation.role_id == role_id,
                CandidateEvaluation.candidate_evaluation_id == candidate_id,
            )
        ).first()
        if row is None:
            raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
        if phone is not None:
            row.phone = phone
        if email is not None:
            row.email = email
        row.updated_at = datetime.now(UTC)
        session.commit()
        return {"candidate_id": candidate_id, "phone": row.phone, "email": row.email}


def set_candidate_resume(role_id: str, candidate_id: str, *, file_key: str, filename: str) -> dict[str, Any]:
    """Records where the original uploaded resume file landed in object
    storage (file_storage.py) — called once, right after a resume-upload
    add_candidate task creates the candidate, never re-called on a later
    edit (there's no "replace resume" flow)."""
    with db.get_session() as session:
        row = session.scalars(
            select(CandidateEvaluation).where(
                CandidateEvaluation.role_id == role_id,
                CandidateEvaluation.candidate_evaluation_id == candidate_id,
            )
        ).first()
        if row is None:
            raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
        row.resume_file_key = file_key
        row.resume_filename = filename
        row.updated_at = datetime.now(UTC)
        session.commit()
        return {"candidate_id": candidate_id, "resume_file_key": file_key, "resume_filename": filename}


def list_communications(role_id: str, candidate_id: str) -> list[dict[str, Any]]:
    """Every logged touchpoint with this candidate, oldest first —
    across email, WhatsApp, and calls in one place (Conversation History
    batch). See CommunicationLogEntry's docstring for what "logged"
    means here: this repo never sends or connects anything itself, so an
    entry records that the recruiter used the wa.me/tel: handoff or sent
    an email, not a delivery confirmation."""
    with db.get_session() as session:
        rows = session.scalars(
            select(CommunicationLogEntry)
            .where(
                CommunicationLogEntry.role_id == role_id,
                CommunicationLogEntry.candidate_evaluation_id == candidate_id,
            )
            .order_by(CommunicationLogEntry.created_at)
        ).all()
        return [
            {
                "id": r.id, "channel": r.channel, "direction": r.direction, "content": r.content,
                "transcript": r.transcript, "contact_used": r.contact_used, "logged_by": r.logged_by,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


def log_communication(
    role_id: str, candidate_id: str, *, channel: str, direction: str, content: str,
    transcript: str | None = None, contact_used: str = "", logged_by: str = "",
) -> dict[str, Any]:
    with db.get_session() as session:
        if session.get(Job, role_id) is None:
            raise ValueError(f"job '{role_id}' not found")
        eval_row = session.scalars(
            select(CandidateEvaluation).where(
                CandidateEvaluation.role_id == role_id,
                CandidateEvaluation.candidate_evaluation_id == candidate_id,
            )
        ).first()
        if eval_row is None:
            raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
        entry = CommunicationLogEntry(
            role_id=role_id, candidate_evaluation_id=candidate_id, channel=channel, direction=direction,
            content=content, transcript=transcript, contact_used=contact_used, logged_by=logged_by,
        )
        session.add(entry)
        session.commit()
        return {
            "id": entry.id, "channel": entry.channel, "direction": entry.direction, "content": entry.content,
            "transcript": entry.transcript, "contact_used": entry.contact_used, "logged_by": entry.logged_by,
            "created_at": entry.created_at.isoformat(),
        }


def get_conversation_summary(role_id: str, candidate_id: str) -> dict[str, Any]:
    with db.get_session() as session:
        row = session.scalars(
            select(CandidateEvaluation).where(
                CandidateEvaluation.role_id == role_id,
                CandidateEvaluation.candidate_evaluation_id == candidate_id,
            )
        ).first()
        if row is None:
            raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
        return {
            "summary": row.conversation_summary,
            "updated_at": row.conversation_summary_updated_at.isoformat() if row.conversation_summary_updated_at else None,
            "based_on_entries": row.conversation_summary_entry_count,
        }


def set_conversation_summary(role_id: str, candidate_id: str, summary: str, entry_count: int) -> None:
    with db.get_session() as session:
        row = session.scalars(
            select(CandidateEvaluation).where(
                CandidateEvaluation.role_id == role_id,
                CandidateEvaluation.candidate_evaluation_id == candidate_id,
            )
        ).first()
        if row is None:
            raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
        row.conversation_summary = summary
        row.conversation_summary_updated_at = datetime.now(UTC)
        row.conversation_summary_entry_count = entry_count
        session.commit()


def _job_dict(job: Job) -> dict[str, Any]:
    return {
        "role_id": job.role_id, "title": job.title, "role_family": job.role_family,
        "client_name": job.client_name, "share_token": job.share_token,
        "lifecycle_status": job.lifecycle_status, "owner_email": job.owner_email,
        "role_value": job.role_value, "expected_revenue": revenue.expected_revenue(job.role_value),
        "created_at": job.created_at, "updated_at": job.updated_at,
    }


def create_job(
    role_id: str, *, title: str = "", role_family: str = "", owner_email: str = "", client_name: str = "",
    role_value: float | None = None,
) -> dict[str, Any]:
    """First-class job creation with display metadata. Not part of
    storage.py's contract — the file backend has no "job shell" concept,
    a role only exists once a section is written. The API's POST /jobs
    needs this so a dashboard has a title to show before intake has run.
    `owner_email` (Phase 10) defaults the job to whoever created it —
    api.py passes the authenticated recruiter's email; left unset for
    calls (e.g. from tests) that don't have one. `client_name` (Batch B)
    is optional — an internal recruiting team has no client to name.
    """
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            job = Job(
                role_id=role_id, title=title or role_id, role_family=role_family,
                owner_email=owner_email or None, client_name=client_name or None,
                role_value=role_value,
            )
            session.add(job)
            session.flush()
            _sync_primary_recruiter(session, role_id, owner_email or None)
        else:
            if title:
                job.title = title
            if role_family:
                job.role_family = role_family
            if client_name:
                job.client_name = client_name
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


def _sync_primary_recruiter(session: Session, role_id: str, email: str | None) -> None:
    """Keeps job_recruiters' one "primary" row in step with Job.owner_email
    — called from create_job/set_job_owner so every existing owner_email
    read stays correct while multi-recruiter attribution (Batch: recruiter
    assignment) is purely additive on top. Never touches contributor rows."""
    existing_primary = session.scalars(
        select(JobRecruiter).where(JobRecruiter.role_id == role_id, JobRecruiter.assignment == "primary")
    ).first()
    if existing_primary is not None:
        if existing_primary.email == email:
            return
        session.delete(existing_primary)
    if email:
        # A contributor being promoted to primary shouldn't also linger as
        # a contributor row — same person, one assignment.
        stale_contributor = session.scalars(
            select(JobRecruiter).where(JobRecruiter.role_id == role_id, JobRecruiter.email == email)
        ).first()
        if stale_contributor is not None:
            session.delete(stale_contributor)
        session.flush()
        session.add(JobRecruiter(role_id=role_id, email=email, assignment="primary"))


def set_job_owner(role_id: str, owner_email: str | None) -> dict[str, Any]:
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            raise ValueError(f"job '{role_id}' not found")
        job.owner_email = owner_email or None
        _sync_primary_recruiter(session, role_id, owner_email or None)
        session.commit()
        return _job_dict(job)


def list_recruiters(role_id: str) -> list[dict[str, Any]]:
    """Every recruiter attributed to this role — the primary (kept in
    sync with Job.owner_email) plus any contributors. Primary sorts
    first, contributors by when they joined."""
    with db.get_session() as session:
        rows = session.scalars(select(JobRecruiter).where(JobRecruiter.role_id == role_id)).all()
        ordered = sorted(rows, key=lambda r: (r.assignment != "primary", r.added_at))
        return [
            {"email": r.email, "assignment": r.assignment, "added_at": r.added_at}
            for r in ordered
        ]


def add_recruiter(role_id: str, email: str) -> list[dict[str, Any]]:
    """Adds `email` as a contributor on this role. Raises ValueError if the
    job doesn't exist, the email is already the primary (nothing to add —
    reassign primary via set_job_owner instead), or already a contributor."""
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            raise ValueError(f"job '{role_id}' not found")
        existing = session.scalars(
            select(JobRecruiter).where(JobRecruiter.role_id == role_id, JobRecruiter.email == email)
        ).first()
        if existing is not None:
            raise ValueError(f"'{email}' is already assigned to this role as {existing.assignment}")
        session.add(JobRecruiter(role_id=role_id, email=email, assignment="contributor"))
        session.commit()
    return list_recruiters(role_id)


def remove_recruiter(role_id: str, email: str) -> list[dict[str, Any]]:
    """Removes a contributor. Refuses to remove the primary — reassign
    ownership via set_job_owner (to another recruiter, or None) instead,
    so a role is never left with a dangling owner_email/recruiter-row
    mismatch."""
    with db.get_session() as session:
        row = session.scalars(
            select(JobRecruiter).where(JobRecruiter.role_id == role_id, JobRecruiter.email == email)
        ).first()
        if row is None:
            raise ValueError(f"'{email}' is not assigned to this role")
        if row.assignment == "primary":
            raise ValueError("can't remove the primary recruiter this way — reassign ownership instead")
        session.delete(row)
        session.commit()
    return list_recruiters(role_id)


def set_job_client(role_id: str, client_name: str | None) -> dict[str, Any]:
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            raise ValueError(f"job '{role_id}' not found")
        job.client_name = client_name or None
        session.commit()
        return _job_dict(job)


def set_job_value(role_id: str, role_value: float | None) -> dict[str, Any]:
    """The revenue basis (see revenue.py) — recruiter-entered, never
    AI-inferred. `None` clears it (e.g. a role with no agreed fee yet),
    which is meaningfully different from a role genuinely worth 0."""
    if role_value is not None and role_value < 0:
        raise ValueError("role value can't be negative")
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            raise ValueError(f"job '{role_id}' not found")
        job.role_value = role_value
        session.commit()
        return _job_dict(job)


def revenue_overview() -> dict[str, Any]:
    """Cumulative revenue across the whole roster (Revenue Intelligence
    batch). Expected = every OPEN role's role_value * margin, for roles
    that have a role_value set at all — unpriced roles contribute
    nothing rather than being guessed at. Pipeline = the subset of that
    figure for roles that actually have candidates captured (real
    sourcing activity, not just an open req). Realized is never
    recomputed here — it's analytics_overview()'s existing sum of actual
    placement_fee values, a number recruiters already enter by hand at
    the moment of a real placement."""
    jobs = list_jobs()
    open_roles = [j for j in jobs if j["lifecycle_status"] == "OPEN"]
    total_expected = 0.0
    total_pipeline = 0.0
    priced_open_roles = 0
    for j in open_roles:
        rev = revenue.expected_revenue(j.get("role_value"))
        if rev is None:
            continue
        priced_open_roles += 1
        total_expected += rev
        state = load_role(j["role_id"])
        if state.get("candidates"):
            total_pipeline += rev
    realized = analytics_overview()["total_placement_fees"]
    return {
        "open_roles": len(open_roles),
        "open_roles_priced": priced_open_roles,
        "expected_revenue": round(total_expected, 2),
        "pipeline_revenue": round(total_pipeline, 2),
        "realized_revenue": realized,
        "margin_percentage": revenue.REVENUE_MARGIN_PERCENTAGE,
    }


def recruiter_revenue() -> list[dict[str, Any]]:
    """Per-recruiter revenue contribution — the second half of Revenue
    Intelligence, alongside revenue_overview()'s firm-wide totals.
    *Every* recruiter attributed to a role (primary or contributor, see
    JobRecruiter) gets full credit for that role's expected and realized
    revenue — this is not a split. A role with a primary and a
    contributor counts fully toward both of their totals, so summing
    every recruiter's `expected_revenue` will not equal
    revenue_overview()'s firm-wide `expected_revenue` once contributors
    are in use — each recruiter's own number, and their `share_of_firm`
    against the *true* firm total, are the meaningful figures here, not
    a partition that has to add up to 100%. Expected revenue only
    counts a role while it's OPEN, matching revenue_overview()."""
    jobs = {j["role_id"]: j for j in list_jobs()}
    with db.get_session() as session:
        recruiter_rows = session.scalars(select(JobRecruiter)).all()
        evaluations = session.scalars(select(CandidateEvaluation)).all()

    role_recruiters: dict[str, list[str]] = {}
    for row in recruiter_rows:
        role_recruiters.setdefault(row.role_id, []).append(row.email)

    role_realized: dict[str, float] = {}
    for ev in evaluations:
        p = ev.prioritization
        if p and p.get("placed"):
            role_realized[ev.role_id] = role_realized.get(ev.role_id, 0.0) + (p.get("placement_fee") or 0.0)

    by_recruiter: dict[str, dict[str, Any]] = {}

    def _bucket(email: str) -> dict[str, Any]:
        return by_recruiter.setdefault(email, {"email": email, "roles": 0, "expected_revenue": 0.0, "realized_revenue": 0.0})

    for role_id, emails in role_recruiters.items():
        job = jobs.get(role_id)
        if job is None:
            continue
        expected = revenue.expected_revenue(job.get("role_value")) if job["lifecycle_status"] == "OPEN" else None
        realized = role_realized.get(role_id, 0.0)
        for email in emails:
            bucket = _bucket(email)
            bucket["roles"] += 1
            if expected is not None:
                bucket["expected_revenue"] += expected
            bucket["realized_revenue"] += realized

    firm_total = revenue_overview()
    firm_denominator = firm_total["expected_revenue"] + firm_total["realized_revenue"]

    result = []
    for bucket in by_recruiter.values():
        total = round(bucket["expected_revenue"] + bucket["realized_revenue"], 2)
        result.append({
            "email": bucket["email"],
            "roles": bucket["roles"],
            "expected_revenue": round(bucket["expected_revenue"], 2),
            "realized_revenue": round(bucket["realized_revenue"], 2),
            "total_revenue": total,
            "share_of_firm": round(total / firm_denominator * 100, 1) if firm_denominator > 0 else 0.0,
        })
    return sorted(result, key=lambda r: r["total_revenue"], reverse=True)


def generate_share_link(role_id: str) -> dict[str, Any]:
    """A random, rotatable token (Batch B) — never the role_id itself, so
    a leaked link can be revoked/regenerated without renaming the role."""
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            raise ValueError(f"job '{role_id}' not found")
        job.share_token = secrets.token_urlsafe(24)
        session.commit()
        return _job_dict(job)


def revoke_share_link(role_id: str) -> dict[str, Any]:
    with db.get_session() as session:
        job = session.get(Job, role_id)
        if job is None:
            raise ValueError(f"job '{role_id}' not found")
        job.share_token = None
        session.commit()
        return _job_dict(job)


def set_conversation_intelligence(role_id: str, candidate_id: str, intelligence: dict[str, Any]) -> None:
    """Structured extraction over a candidate's communication log
    (Conversation Intelligence batch) — stored as a JobSection, same
    zero-migration-risk reasoning as set_candidate_client_visible below,
    keyed by candidate_id since one role has many candidates."""
    if candidate_id not in load_role(role_id).get("candidates", {}):
        raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
    all_intelligence = dict(load_role(role_id).get("conversation_intelligence") or {})
    all_intelligence[candidate_id] = intelligence
    merge_section(role_id, "conversation_intelligence", all_intelligence)


def set_candidate_client_visible(role_id: str, candidate_id: str, visible: bool) -> dict[str, bool]:
    """Client sharing (recruiter/client/admin permission model): the
    recruiter's own explicit, per-candidate decision to expose a safe
    subset of this evaluation on the public share-link page. Stored as a
    JobSection (not a new CandidateEvaluation column) deliberately —
    this repo has no migration tool, and create_all() only creates
    missing *tables*, never adds a column to one that already exists in
    an already-provisioned production database. A JSON section under the
    existing job_sections table carries new fields with zero schema risk.
    Defaults to private; sharing is opt-in, never automatic."""
    if candidate_id not in load_role(role_id).get("candidates", {}):
        raise ValueError(f"candidate '{candidate_id}' not found for role '{role_id}'")
    shares = dict(load_role(role_id).get("client_shares") or {})
    if visible:
        shares[candidate_id] = True
    else:
        shares.pop(candidate_id, None)
    merge_section(role_id, "client_shares", shares)
    return {"candidate_id": candidate_id, "client_visible": visible}


# Fields considered safe for an unauthenticated client-facing link — see
# get_public_role_summary's docstring for what's deliberately excluded.
_CLIENT_SAFE_CANDIDATE_FIELDS = (
    "name", "current_title", "current_company", "location",
    "relevant_experience_summary", "achievements", "evidence_of_fit",
)


def get_public_role_summary(share_token: str) -> dict[str, Any] | None:
    """Read-only client-facing view (Batch B) behind a share token —
    aggregate counts/stage names for every candidate, plus a safe subset
    of detail (name, title, company, evidence-labeled achievements/fit —
    the "candidate profile/summary" the recruiter has explicitly opted a
    candidate into sharing via set_candidate_client_visible) for only
    the candidates the recruiter has explicitly marked shareable.
    Never included, on any candidate, shared or not: CTC/compensation,
    private recruiter notes, weaknesses/concerns (internal assessment),
    recruiter_decision, phone/email (PII on an unauthenticated public
    link), placement/revenue figures, or anything about other clients,
    other roles, or the recruiting team itself."""
    with db.get_session() as session:
        job = session.scalars(select(Job).where(Job.share_token == share_token)).first()
        if job is None:
            return None
        role_id, title, client_name = job.role_id, job.title, job.client_name
        lifecycle_status, updated_at = job.lifecycle_status, job.updated_at
        total_candidates = len(
            session.scalars(
                select(CandidateEvaluation).where(CandidateEvaluation.role_id == role_id)
            ).all()
        )

    state = load_role(role_id)
    funnel = state.get("funnel", {})
    counts_by_stage: dict[str, int] = {}
    for record in funnel.values():
        stage = record.get("current_stage", "IDENTIFIED")
        counts_by_stage[stage] = counts_by_stage.get(stage, 0) + 1

    candidates = state.get("candidates", {})
    prioritizations = state.get("prioritizations", {})
    shares = state.get("client_shares") or {}
    shared_candidates = []
    for candidate_id, is_shared in shares.items():
        if not is_shared or candidate_id not in candidates:
            continue
        full = candidates[candidate_id]
        safe = {k: full.get(k) for k in _CLIENT_SAFE_CANDIDATE_FIELDS}
        p = prioritizations.get(candidate_id) or {}
        safe["tier"] = p.get("tier")
        safe["fit_rating"] = p.get("fit_rating")
        safe["why_they_fit"] = p.get("why_they_fit")
        safe["current_stage"] = (funnel.get(candidate_id) or {}).get("current_stage", "IDENTIFIED")
        shared_candidates.append(safe)

    return {
        "role_id": role_id, "title": title, "client_name": client_name,
        "lifecycle_status": lifecycle_status, "updated_at": updated_at,
        "total_candidates": total_candidates, "counts_by_stage": counts_by_stage,
        "shared_candidates": shared_candidates,
    }


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
        "fit_rating": p.get("fit_rating"),
        "why_they_fit": p.get("why_they_fit"),
        "recruiter_decision": p.get("recruiter_decision"),
        "phone": ev.phone,
        "email": ev.email,
        "resume_file_key": ev.resume_file_key,
        "resume_filename": ev.resume_filename,
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
        total_placements = 0
        total_placement_fees = 0.0

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
            if p.get("placed"):
                total_placements += 1
                total_placement_fees += p.get("placement_fee") or 0.0

        return {
            "total_jobs": total_jobs,
            "total_candidates": total_candidates,
            "total_evaluations": len(evaluations),
            "tier_distribution": tier_distribution,
            "decisions_recorded": decisions_recorded,
            "decisions_pending": decisions_pending,
            "decision_breakdown": decision_breakdown,
            "total_placements": total_placements,
            "total_placement_fees": total_placement_fees,
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


def velocity_report() -> dict[str, Any]:
    """Per-role and per-recruiter velocity/conversion (Batch B) — the
    question none of the activity-count views answer: is the effort
    actually converting, and where does it stall? Stage dwell time comes
    from each candidate's own stage_history (Phase 8, stages/funnel.py) —
    only *completed* stage spans count (a transition with a following
    one), never an open-ended "still sitting here" duration, which is a
    different stat (see attention_needed's days_in_stage). The
    conversion funnel (sourced -> tiered A -> pursued -> placed) is
    deterministic counting over CandidateEvaluation + its prioritization,
    same discipline as analytics_overview()."""
    jobs = {j["role_id"]: j for j in list_jobs()}

    empty_conv = {"sourced": 0, "tiered_a": 0, "pursued": 0, "placed": 0}
    conv_by_role: dict[str, dict[str, int]] = {}
    conv_by_recruiter: dict[str, dict[str, int]] = {}
    stage_days_by_role: dict[str, dict[str, list[float]]] = {}
    stage_days_by_recruiter: dict[str, dict[str, list[float]]] = {}

    def _bump(bucket: dict[str, dict[str, int]], key: str, field: str) -> None:
        bucket.setdefault(key, dict(empty_conv))[field] += 1

    for role_id, job in jobs.items():
        owner = job.get("owner_email")
        state = load_role(role_id)
        candidates = state.get("candidates") or {}
        prioritizations = state.get("prioritizations") or {}
        funnel = state.get("funnel") or {}

        for candidate_id in candidates:
            _bump(conv_by_role, role_id, "sourced")
            if owner:
                _bump(conv_by_recruiter, owner, "sourced")
            p = prioritizations.get(candidate_id)
            if not p:
                continue
            if p.get("tier") == "A":
                _bump(conv_by_role, role_id, "tiered_a")
                if owner:
                    _bump(conv_by_recruiter, owner, "tiered_a")
            if p.get("recruiter_decision") == "pursue":
                _bump(conv_by_role, role_id, "pursued")
                if owner:
                    _bump(conv_by_recruiter, owner, "pursued")
            if p.get("placed"):
                _bump(conv_by_role, role_id, "placed")
                if owner:
                    _bump(conv_by_recruiter, owner, "placed")

        for record in funnel.values():
            history = record.get("stage_history") or []
            for i in range(len(history) - 1):
                stage = history[i].get("stage")
                start_raw, end_raw = history[i].get("at"), history[i + 1].get("at")
                if not stage or not start_raw or not end_raw:
                    continue
                days = (_parse_aware(end_raw) - _parse_aware(start_raw)).total_seconds() / 86400
                if days < 0:
                    continue
                stage_days_by_role.setdefault(role_id, {}).setdefault(stage, []).append(days)
                if owner:
                    stage_days_by_recruiter.setdefault(owner, {}).setdefault(stage, []).append(days)

    def _avg_days(bucket: dict[str, list[float]]) -> dict[str, float]:
        return {stage: round(sum(vals) / len(vals), 1) for stage, vals in bucket.items()}

    by_role = [
        {
            "role_id": role_id,
            "title": jobs[role_id]["title"],
            "conversion": conv_by_role.get(role_id, dict(empty_conv)),
            "avg_days_in_stage": _avg_days(stage_days_by_role.get(role_id, {})),
        }
        for role_id in jobs
    ]
    by_recruiter = [
        {
            "email": email,
            "conversion": conv,
            "avg_days_in_stage": _avg_days(stage_days_by_recruiter.get(email, {})),
        }
        for email, conv in conv_by_recruiter.items()
    ]

    return {"by_role": by_role, "by_recruiter": by_recruiter}


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


def reset_incomplete_tasks(error: str) -> int:
    """Mark every task still in a non-terminal state ("pending" or
    "running") as failed. Returns how many rows were touched.

    task_queue.py's queue is in-memory (see its module docstring); it
    never survives a process restart. A task that was "pending" or
    "running" in the database when the previous process died (crash,
    redeploy) has no worker left that will ever pick it back up — it
    would otherwise sit there forever looking like a request that never
    finished. Call this once at startup, before any new task is
    enqueued, so a recruiter sees a clear failure instead of an action
    that spins forever.
    """
    with db.get_session() as session:
        tasks = session.scalars(select(Task).where(Task.status.in_(("pending", "running")))).all()
        now = datetime.now(UTC)
        for task in tasks:
            task.status = "failed"
            task.error = error
            task.updated_at = now
            task.finished_at = now
        session.commit()
        return len(tasks)


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


def team_usage() -> dict[str, Any]:
    """Per-recruiter activity across every job — answers "is every
    recruiter actually using this," not just one recruiter's own view of
    their own work. Also answers a different question, "who's overloaded
    right now" — open_jobs/active_candidates are current load, distinct
    from the lifetime totals (jobs_owned, candidates_added) alongside
    them. Deterministic counting from User + ActivityLog + Job +
    CandidateEvaluation, same discipline as analytics_overview(): no
    model call, no interpretation, just what's actually in the log."""
    with db.get_session() as session:
        users = session.scalars(select(User).order_by(User.created_at)).all()
        logs = session.scalars(select(ActivityLog)).all()
        jobs = session.scalars(select(Job)).all()
        evaluations = session.scalars(select(CandidateEvaluation)).all()

        logs_by_user: dict[str, list[ActivityLog]] = {}
        for log in logs:
            logs_by_user.setdefault(log.user_email, []).append(log)

        jobs_owned_by_user: dict[str, int] = {}
        open_jobs_by_user: dict[str, int] = {}
        owner_by_role: dict[str, str] = {}
        job_by_role: dict[str, Job] = {}
        for job in jobs:
            job_by_role[job.role_id] = job
            if job.owner_email:
                jobs_owned_by_user[job.owner_email] = jobs_owned_by_user.get(job.owner_email, 0) + 1
                owner_by_role[job.role_id] = job.owner_email
                if job.lifecycle_status == "OPEN":
                    open_jobs_by_user[job.owner_email] = open_jobs_by_user.get(job.owner_email, 0) + 1

        # Placements/fees (Batch B) attribute to whoever owns the job the
        # placement happened on — the closest thing to "whose deal was
        # this" without a separate assignment concept.
        placements_by_user: dict[str, int] = {}
        fees_by_user: dict[str, float] = {}
        # Current load (Batch B), distinct from the lifetime totals above:
        # candidates still live in one of this recruiter's OPEN searches —
        # not yet placed, not passed on. A closed/on-hold job or a
        # candidate already resolved one way or the other isn't work
        # still sitting on their plate.
        active_candidates_by_user: dict[str, int] = {}
        for ev in evaluations:
            p = ev.prioritization
            owner = owner_by_role.get(ev.role_id)
            job = job_by_role.get(ev.role_id)
            if p and p.get("placed"):
                if owner:
                    placements_by_user[owner] = placements_by_user.get(owner, 0) + 1
                    fees_by_user[owner] = fees_by_user.get(owner, 0.0) + (p.get("placement_fee") or 0.0)
                continue
            if owner and job and job.lifecycle_status == "OPEN" and (not p or p.get("recruiter_decision") != "pass for now"):
                active_candidates_by_user[owner] = active_candidates_by_user.get(owner, 0) + 1

        recruiters = []
        for u in users:
            user_logs = logs_by_user.get(u.email, [])
            candidates_added = sum(1 for log in user_logs if log.action.startswith("added candidate"))
            last_active = max((log.created_at for log in user_logs), default=None)
            recruiters.append({
                "email": u.email,
                "joined_at": u.created_at,
                "jobs_owned": jobs_owned_by_user.get(u.email, 0),
                "candidates_added": candidates_added,
                "total_actions": len(user_logs),
                "last_active": last_active,
                "placements": placements_by_user.get(u.email, 0),
                "placement_fees": fees_by_user.get(u.email, 0.0),
                "open_jobs": open_jobs_by_user.get(u.email, 0),
                "active_candidates": active_candidates_by_user.get(u.email, 0),
            })

        return {"total_users": len(users), "recruiters": recruiters}


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
