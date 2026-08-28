"""SQLAlchemy tables backing db_storage.py (Phase 1 + 2 of the product
build — see docs/product-plan.md). `jobs` + `job_sections` (Phase 1) mirror
storage.py's one-JSON-blob-per-section model for everything except
candidates. `candidates` + `candidate_evaluations` (Phase 2) split
candidate identity (reusable across jobs) from a per-job evaluation
(achievements/evidence/tier as captured *for that job's ICP* — evidence is
inherently job-context-specific, so it lives on the evaluation, not the
canonical identity). `candidate_evaluations.candidate_evaluation_id` is
the same job-scoped id (`f"{role_id}-{slug}"`) candidate_analysis.py has
always produced — nothing about that id's shape changed, only where it's
stored.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Job(Base):
    __tablename__ = "jobs"

    role_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(String, default=None)
    role_family: Mapped[str | None] = mapped_column(String, default=None)
    # Lifecycle (Phase 10, docs/product-plan.md) — named lifecycle_status,
    # not status, so it's never confused with pipeline.status()'s
    # per-stage-done dict or Task.status's pending/running/succeeded/
    # failed. One of OPEN/ON_HOLD/FILLED/CANCELLED (models/job_lifecycle.py).
    lifecycle_status: Mapped[str] = mapped_column(String, default="OPEN")
    # Ownership (Phase 10) — defaults to whoever created the job but is
    # reassignable; drives the dashboard's "My jobs" filter now that
    # Phase 8 lets more than one recruiter share this workspace.
    owner_email: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class JobSection(Base):
    __tablename__ = "job_sections"
    __table_args__ = (UniqueConstraint("role_id", "section_key", name="uq_job_section"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("jobs.role_id"))
    section_key: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class CanonicalCandidate(Base):
    """A person, reusable across jobs. Deliberately thin — identity only,
    no achievements/evidence (those are job-context-specific and live on
    CandidateEvaluation). Matched at add-time by db_storage's dedup
    heuristic (source_url, then normalized name+company); never
    auto-merged after the fact."""

    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    current_company: Mapped[str] = mapped_column(String, default="")
    current_title: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    source_url: Mapped[str] = mapped_column(String, default="")
    first_seen_job_id: Mapped[str] = mapped_column(ForeignKey("jobs.role_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Task(Base):
    """A queued/running/finished background unit of work — Phase 4 (async +
    scale, docs/product-plan.md). Every LLM-touching stage call is enqueued
    here and executed by task_queue.py's single worker thread instead of
    running inline in the request handler, so a slow real model call never
    blocks the HTTP response. `args` is whatever the runner needs (e.g.
    {"candidate_id": ...}); `result` is the stage's own .model_dump() once
    status is "succeeded"; `error` is a human-readable message once status
    is "failed" — the async equivalent of api.py's old synchronous
    ValueError/RuntimeError -> 400/502 mapping."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("jobs.role_id"))
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class CandidateEvaluation(Base):
    """One job's evaluation of one canonical candidate. `data` is the full
    Candidate model dump (identity + achievements + evidence) as captured
    for this job; `prioritization` is the CandidatePrioritization dump,
    null until stages.prioritization has run. `note` (Phase 10) is a
    recruiter's own freeform text, deliberately kept out of `data` — that
    JSON blob is the model's evidence-labeled output (Architecture §1.2),
    and a private impression like "seemed distracted on the call" is
    neither evidence nor something the model produced, so it gets its own
    column rather than blurring that boundary."""

    __tablename__ = "candidate_evaluations"
    __table_args__ = (
        UniqueConstraint("role_id", "candidate_evaluation_id", name="uq_role_candidate_eval"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("jobs.role_id"))
    candidate_evaluation_id: Mapped[str] = mapped_column(String)
    canonical_candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"))
    data: Mapped[dict] = mapped_column(JSON)
    prioritization: Mapped[dict | None] = mapped_column(JSON, default=None)
    note: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class User(Base):
    """Phase 7 (auth, docs/product-plan.md). Deliberately minimal — this is
    a locally-run, single-recruiter tool with no real domain/hosting, not
    a multi-tenant SaaS, so this is plain session-based email+password
    auth rather than OAuth/SSO. `password_hash` is PBKDF2-HMAC-SHA256
    (stdlib hashlib, no new dependency) with a per-user random salt."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    password_salt: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Session(Base):
    """A logged-in session, keyed by an opaque bearer token stored in an
    HTTP-only cookie (see auth.py). Persisted rather than in-memory so a
    login survives an API process restart, same reasoning as everything
    else in this file."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class ActivityLog(Base):
    """Who did what, when — Phase 8's multi-account accounts share one
    workspace (Phase 8, docs/product-plan.md), so once more than one
    person can be in the same job, "who set this decision / moved this
    candidate" stops being obvious from context alone. Written from
    api.py's route handlers (the one layer that has the authenticated
    user, via request.state.user) right after a mutation succeeds — never
    from stages/*.py, which stay storage-backend-only and HTTP-agnostic.
    candidate_id is nullable: some actions (job creation, cloning) aren't
    about one candidate."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("jobs.role_id"))
    user_email: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(String, default="")
    candidate_id: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
