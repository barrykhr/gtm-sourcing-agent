"""FastAPI service — the HTTP surface for the product layer (Phase 1, see
docs/implementation-plan.md and the Recruiting OS Blueprint). One route
per stage, mirroring the CLI 1:1: every route is a thin wrapper that calls
the exact same stages/*.py functions the CLI calls, passing
storage_backend=db_storage instead of the file backend. No recruiting
logic lives in this file — see ARCHITECTURE.md for why that boundary
matters.
"""

import csv
import io
import logging
import os
import re
import unicodedata
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from . import auth, db_storage, file_storage, orchestrator, pipeline, resume_extraction, task_queue, webhooks
from .models.funnel import ForecastAssumptions
from .models.interview_questions import InterviewQuestionHistory
from .stages import calibration as calibration_stage
from .stages import candidate_analysis as candidate_analysis_stage
from .stages import conversation_summary as conversation_summary_stage
from .stages import funnel as funnel_stage
from .stages import icp as icp_stage
from .stages import intake as intake_stage
from .stages import interview_questions as interview_questions_stage
from .stages import outreach as outreach_stage
from .stages import prioritization as prioritization_stage
from .stages import screening as screening_stage
from .stages import search_strategy as search_strategy_stage
from .stages import talent_map as talent_map_stage

app = FastAPI(title="Talyn API", version="0.1.0")
logger = logging.getLogger(__name__)

# ── auth (Phase 7) ──────────────────────────────────────────────────────
# Every route below requires a valid session except this allowlist —
# enforced here, once, via middleware rather than a per-route dependency,
# so a route can never be accidentally left unguarded. See auth.py's
# module docstring for why this is plain session auth, not OAuth/SSO.

_PUBLIC_PATHS = {"/health", "/auth/signup", "/auth/login", "/auth/status", "/auth/google"}
_COOKIE_SECURE = os.environ.get("GTM_COOKIE_SECURE", "false").lower() == "true"
# SameSite=Lax (the default) is right for local dev, where the frontend
# and API share a host. A split-host deployment (frontend and API on
# different domains — e.g. Vercel + Render) needs SameSite=None so the
# browser sends the cookie on the frontend's cross-origin fetch() calls
# at all; browsers reject a None cookie that isn't also Secure, so that
# combination forces secure=True regardless of GTM_COOKIE_SECURE.
_COOKIE_SAMESITE = os.environ.get("GTM_COOKIE_SAMESITE", "lax").lower()
if _COOKIE_SAMESITE == "none":
    _COOKIE_SECURE = True


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # /public/... (Batch B: client-facing share links) is deliberately
        # unauthenticated — it's the one surface meant for someone
        # outside the recruiting team, gated by an unguessable token
        # instead of a login, and it only ever returns the curated
        # summary from get_public_role_summary(), never raw workspace data.
        if (
            request.method == "OPTIONS"
            or request.url.path in _PUBLIC_PATHS
            or request.url.path.startswith("/public/")
        ):
            return await call_next(request)
        token = request.cookies.get(auth.SESSION_COOKIE_NAME)
        user = auth.get_user_from_session(token) if token else None
        if user is None:
            return JSONResponse({"detail": "not authenticated"}, status_code=401)
        request.state.user = user
        return await call_next(request)


def require_role(*allowed_roles: str):
    """FastAPI dependency gating a route to specific roles — server-side
    enforcement (Production-Readiness Phase §4), never a frontend nav
    check. AuthMiddleware has already guaranteed request.state.user
    exists (or the request never reaches here) by the time this runs.
    Raises 403, distinct from AuthMiddleware's 401 — the caller IS
    authenticated, just not authorized for this specific route."""

    def _check(request: Request) -> dict[str, Any]:
        user = request.state.user
        if user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"requires one of role(s): {', '.join(allowed_roles)}")
        return user

    return _check


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE_NAME, token, httponly=True, samesite=_COOKIE_SAMESITE,
        secure=_COOKIE_SECURE, max_age=int(auth.SESSION_TTL.total_seconds()), path="/",
    )


# Registration order matters: Starlette makes the *last*-added middleware
# outermost, so CORS (added second, below) wraps AuthMiddleware and
# handles preflight OPTIONS requests before anything else runs — the
# explicit OPTIONS check above is a belt-and-suspenders backstop, not the
# only thing preflight relies on.
app.add_middleware(AuthMiddleware)

_allowed_origins = os.environ.get("GTM_CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SignupRequest(BaseModel):
    email: str
    password: str
    signup_code: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleAuthRequest(BaseModel):
    credential: str


@app.get("/auth/status")
def auth_status() -> dict[str, Any]:
    return {
        "signup_requires_code": auth.signup_requires_code(),
        "google_client_id": auth.GOOGLE_CLIENT_ID,
    }


@app.post("/auth/signup")
def signup(body: SignupRequest, response: Response) -> dict[str, Any]:
    user = _run_stage(auth.create_user, body.email, body.password, body.signup_code)
    token = auth.create_session(user["id"])
    _set_session_cookie(response, token)
    return user


@app.post("/auth/login")
def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    user = auth.verify_credentials(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="incorrect email or password")
    token = auth.create_session(user["id"])
    _set_session_cookie(response, token)
    return user


@app.post("/auth/google")
def google_auth(body: GoogleAuthRequest, response: Response) -> dict[str, Any]:
    user = _run_stage(auth.google_login, body.credential)
    token = auth.create_session(user["id"])
    _set_session_cookie(response, token)
    return user


@app.post("/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    if token:
        auth.delete_session(token)
    response.delete_cookie(auth.SESSION_COOKIE_NAME, path="/")
    return {"status": "logged out"}


@app.get("/auth/me")
def me(request: Request) -> dict[str, Any]:
    return request.state.user


class UserRoleRequest(BaseModel):
    role: str


@app.get("/users")
def list_users(_admin: dict[str, Any] = Depends(require_role("admin"))) -> list[dict[str, Any]]:
    return auth.list_users()


@app.patch("/users/{user_id}/role")
def set_user_role(user_id: str, body: UserRoleRequest, _admin: dict[str, Any] = Depends(require_role("admin"))) -> dict[str, Any]:
    # Not logged via ActivityLog: that table is job-scoped (role_id is a
    # non-null FK to jobs.role_id) — a role change isn't about any job.
    return _run_stage(auth.set_user_role, user_id, body.role)


def _run_stage(fn, *args, **kwargs) -> Any:
    """Every stage call goes through this so a missing checkpoint
    (ValueError) and an LLM-call failure (RuntimeError) map to distinct,
    predictable HTTP statuses instead of a generic 500 — the API-layer
    equivalent of cli.py's _friendly_errors decorator."""
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "job"


def _job_summary(role_id: str) -> dict[str, Any]:
    return {
        "role_id": role_id,
        "status": pipeline.status(role_id, storage_backend=db_storage),
        "next_stage": pipeline.next_stage(role_id, storage_backend=db_storage),
    }


def _log(request: Request, role_id: str, action: str, *, detail: str = "", candidate_id: str | None = None) -> None:
    """Best-effort activity logging (Phase 8) — never lets a logging
    failure break the real recruiter action it's attached to. Reads the
    authenticated user off request.state.user, set by AuthMiddleware."""
    try:
        user_email = request.state.user["email"]
        db_storage.log_activity(role_id, user_email, action, detail=detail, candidate_id=candidate_id)
    except Exception:
        logger.exception("activity logging failed for role_id=%s action=%s", role_id, action)


def _maybe_fire_decision_webhook(role_id: str, candidate_id: str, decision: str) -> None:
    """Outbound integration webhook (Phase 8): if the recruiter configured
    one for this job, a "pursue" decision is real enough downstream news
    (an ATS, a Slack channel) to push out automatically — every other
    decision stays a silent internal note, same as before this existed.
    Best-effort: webhooks.send_webhook never raises, and any failure is
    only ever logged, never surfaced as an error on the decision call
    that triggered it."""
    if decision != "pursue":
        return
    try:
        integrations = db_storage.load_role(role_id).get("integrations") or {}
        webhook_url = integrations.get("webhook_url")
        if not webhook_url:
            return
        candidates = db_storage.load_role(role_id).get("candidates") or {}
        candidate = candidates.get(candidate_id) or {}
        result = webhooks.send_webhook(
            webhook_url, "candidate.decision.pursue",
            {"role_id": role_id, "candidate_id": candidate_id, "candidate_name": candidate.get("name", "")},
        )
        db_storage.log_activity(
            role_id, "system", "webhook delivery" if result["ok"] else "webhook delivery failed",
            detail=result["detail"], candidate_id=candidate_id,
        )
    except Exception:
        logger.exception("webhook dispatch failed for role_id=%s candidate_id=%s", role_id, candidate_id)


# ── request bodies ──────────────────────────────────────────────────────


class JobCreateRequest(BaseModel):
    title: str
    role_family: str = ""
    client_name: str = ""
    role_value: float | None = None
    role_id: str | None = None  # override the auto-generated slug if provided


class IntakeRequest(BaseModel):
    jd_text: str


class CandidateAddRequest(BaseModel):
    source_text: str
    role_family: str
    source_url: str = ""


class FunnelUpdateRequest(BaseModel):
    stage: str
    note: str = ""
    scheduled_at: str | None = None


class RecruiterDecisionRequest(BaseModel):
    decision: str


class PlacementRequest(BaseModel):
    placed: bool
    fee: float = 0.0


class ChatRequest(BaseModel):
    message: str


class ChatConfirmRequest(BaseModel):
    approve: bool


class CloneJobRequest(BaseModel):
    title: str
    role_family: str = ""
    role_id: str | None = None  # override the auto-generated slug if provided


class IcpCriteriaRequest(BaseModel):
    must_have: list[str] | None = None
    nice_to_have: list[str] | None = None


class JobDescriptionUpdateRequest(BaseModel):
    role_title: str | None = None
    seniority: str | None = None
    geography: str | None = None
    compensation: str | None = None
    must_have_requirements: list[str] | None = None
    nice_to_have_requirements: list[str] | None = None


class WebhookConfigRequest(BaseModel):
    webhook_url: str = ""


class JobLifecycleRequest(BaseModel):
    lifecycle_status: str


class JobOwnerRequest(BaseModel):
    owner_email: str | None = None


class RecruiterAddRequest(BaseModel):
    email: str


class JobClientRequest(BaseModel):
    client_name: str | None = None


class JobValueRequest(BaseModel):
    role_value: float | None = None


class CandidateNoteRequest(BaseModel):
    note: str = ""


class CandidateContactRequest(BaseModel):
    phone: str | None = None
    email: str | None = None


class CandidateShareRequest(BaseModel):
    visible: bool


class CommunicationLogRequest(BaseModel):
    channel: Literal["email", "whatsapp", "call", "note"]
    direction: Literal["outbound", "inbound"] = "outbound"
    content: str = ""
    transcript: str | None = None
    contact_used: str = ""


class ForecastRequest(BaseModel):
    hires: int
    weeks: int
    source: str = "market_default"
    screen_to_hm: float = 0.5
    hm_to_final: float = 0.5
    final_to_offer: float = 0.5
    offer_to_accept: float = 0.8
    contacted_to_screen: float = 0.3
    sourced_to_contacted: float = 0.3


# ── health ───────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ── jobs ─────────────────────────────────────────────────────────────────


@app.post("/jobs")
def create_job(body: JobCreateRequest, request: Request) -> dict[str, Any]:
    role_id = body.role_id or _slugify(body.title)
    base_role_id, n = role_id, 2
    while db_storage.job_exists(role_id):
        role_id = f"{base_role_id}-{n}"
        n += 1
    # Ownership (Phase 10) defaults to whoever created it — reassignable
    # later via PATCH /jobs/{role_id}/owner.
    job = db_storage.create_job(
        role_id, title=body.title, role_family=body.role_family, client_name=body.client_name,
        role_value=body.role_value, owner_email=request.state.user["email"],
    )
    _log(request, role_id, "created job", detail=body.title)
    return {**job, **_job_summary(role_id)}


@app.post("/jobs/{role_id}/clone")
def clone_job(role_id: str, body: CloneJobRequest, request: Request) -> dict[str, Any]:
    # Role templates (Phase 8): start a new job from an existing one's
    # hiring strategy (JD/calibration/ICP/talent map) instead of a blank
    # intake. Deterministic section copy, not a model call — see
    # db_storage.clone_role's docstring for exactly what does and
    # doesn't carry over.
    new_role_id = body.role_id or _slugify(body.title)
    base_role_id, n = new_role_id, 2
    while db_storage.job_exists(new_role_id):
        new_role_id = f"{base_role_id}-{n}"
        n += 1
    job = _run_stage(
        db_storage.clone_role, role_id, new_role_id, title=body.title, role_family=body.role_family,
        owner_email=request.state.user["email"],
    )
    _log(request, role_id, "cloned as new job", detail=new_role_id)
    _log(request, new_role_id, "cloned from job", detail=role_id)
    return {**job, **_job_summary(new_role_id)}


@app.patch("/jobs/{role_id}/lifecycle")
def set_job_lifecycle(role_id: str, body: JobLifecycleRequest, request: Request) -> dict[str, Any]:
    # Deterministic, recruiter-authored — same category as
    # set_recruiter_decision, but for the job as a whole rather than one
    # candidate. Never set by a stage or the model.
    job = _run_stage(db_storage.set_job_lifecycle, role_id, body.lifecycle_status)
    _log(request, role_id, f"set job status: {body.lifecycle_status}")
    return {**job, **_job_summary(role_id)}


@app.patch("/jobs/{role_id}/owner")
def set_job_owner(role_id: str, body: JobOwnerRequest, request: Request) -> dict[str, Any]:
    job = _run_stage(db_storage.set_job_owner, role_id, body.owner_email)
    _log(request, role_id, "changed job owner", detail=body.owner_email or "(unassigned)")
    return {**job, **_job_summary(role_id)}


@app.get("/jobs/{role_id}/recruiters")
def get_recruiters(role_id: str) -> list[dict[str, Any]]:
    return db_storage.list_recruiters(role_id)


@app.post("/jobs/{role_id}/recruiters")
def add_recruiter(role_id: str, body: RecruiterAddRequest, request: Request) -> list[dict[str, Any]]:
    recruiters = _run_stage(db_storage.add_recruiter, role_id, body.email)
    _log(request, role_id, "added recruiter", detail=body.email)
    return recruiters


@app.delete("/jobs/{role_id}/recruiters/{email}")
def remove_recruiter(role_id: str, email: str, request: Request) -> list[dict[str, Any]]:
    recruiters = _run_stage(db_storage.remove_recruiter, role_id, email)
    _log(request, role_id, "removed recruiter", detail=email)
    return recruiters


@app.patch("/jobs/{role_id}/client")
def set_job_client(role_id: str, body: JobClientRequest, request: Request) -> dict[str, Any]:
    job = _run_stage(db_storage.set_job_client, role_id, body.client_name)
    _log(request, role_id, "changed client", detail=body.client_name or "(unassigned)")
    return {**job, **_job_summary(role_id)}


@app.patch("/jobs/{role_id}/value")
def set_job_value(role_id: str, body: JobValueRequest, request: Request) -> dict[str, Any]:
    job = _run_stage(db_storage.set_job_value, role_id, body.role_value)
    _log(request, role_id, "changed role value", detail=str(body.role_value) if body.role_value is not None else "(unset)")
    return {**job, **_job_summary(role_id)}


@app.get("/revenue/overview")
def revenue_overview() -> dict[str, Any]:
    return db_storage.revenue_overview()


@app.get("/revenue/by-recruiter")
def revenue_by_recruiter() -> list[dict[str, Any]]:
    return db_storage.recruiter_revenue()


@app.post("/jobs/{role_id}/share-link")
def generate_share_link(role_id: str, request: Request) -> dict[str, Any]:
    job = _run_stage(db_storage.generate_share_link, role_id)
    _log(request, role_id, "generated client share link")
    return {**job, **_job_summary(role_id)}


@app.delete("/jobs/{role_id}/share-link")
def revoke_share_link(role_id: str, request: Request) -> dict[str, Any]:
    job = _run_stage(db_storage.revoke_share_link, role_id)
    _log(request, role_id, "revoked client share link")
    return {**job, **_job_summary(role_id)}


@app.get("/public/roles/{share_token}")
def public_role_summary(share_token: str) -> dict[str, Any]:
    summary = db_storage.get_public_role_summary(share_token)
    if summary is None:
        raise HTTPException(status_code=404, detail="This link is no longer valid.")
    return summary


@app.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [{**job, **_job_summary(job["role_id"])} for job in db_storage.list_jobs()]


@app.get("/jobs/{role_id}")
def get_job(role_id: str) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    state = db_storage.load_role(role_id)
    if state.get("interview_questions"):
        # Read-time normalization: older roles still have the flat
        # single-generation shape from before generation history existed
        # (see InterviewQuestionHistory.from_raw's docstring).
        state["interview_questions"] = InterviewQuestionHistory.from_raw(state["interview_questions"]).model_dump()
    jobs = {j["role_id"]: j for j in db_storage.list_jobs()}
    return {**jobs[role_id], **_job_summary(role_id), "state": state}


@app.get("/jobs/{role_id}/activity")
def get_activity(role_id: str) -> list[dict[str, Any]]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    return db_storage.list_activity(role_id)


# ── global candidate roster (Phase 2) ───────────────────────────────────
# Additive only — the per-job /jobs/{role_id}/candidates routes below are
# unchanged. This is the cross-job view: one canonical person, every job
# they've been evaluated against (build instruction §9).


@app.get("/candidates")
def list_candidates_global() -> list[dict[str, Any]]:
    return db_storage.list_canonical_candidates()


@app.get("/candidates/{candidate_id}")
def get_candidate_global(candidate_id: str) -> dict[str, Any]:
    detail = db_storage.get_canonical_candidate(candidate_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"candidate '{candidate_id}' not found")
    return detail


# ── global search (Phase 10) ────────────────────────────────────────────


@app.get("/search")
def search(q: str = "") -> dict[str, Any]:
    return db_storage.search(q)


# ── cross-job analytics (Phase 6) ───────────────────────────────────────
# Dashboard-level view across every job — distinct from the per-job
# Analytics tab (GET /jobs/{role_id}/funnel/report), which is one role's
# funnel conversion.


@app.get("/analytics/overview")
def analytics_overview() -> dict[str, Any]:
    return db_storage.analytics_overview()


@app.get("/analytics/attention")
def analytics_attention() -> dict[str, Any]:
    return db_storage.attention_needed()


@app.get("/team/usage")
def team_usage() -> dict[str, Any]:
    """Every authenticated user shares one workspace (Phase 8), so this
    is visible to any recruiter, not gated to an admin role — there is no
    admin/recruiter distinction anywhere else in the app either."""
    return db_storage.team_usage()


@app.get("/team/velocity")
def team_velocity() -> dict[str, Any]:
    """Same visibility as /team/usage — is the effort converting, and
    where does it stall, per role and per recruiter."""
    return db_storage.velocity_report()


# ── background task runners (Phase 4) ───────────────────────────────────
# Every LLM-touching stage call is registered here and executed by
# task_queue.py's worker thread instead of inline in a request handler —
# see task_queue.py's module docstring for why. Deterministic stages
# (funnel update/report/forecast below) stay synchronous; there's nothing
# to gain by queueing work that doesn't call the model.


def _run_intake(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return intake_stage.run(role_id, args["jd_text"], storage_backend=db_storage).model_dump()


def _run_calibrate(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return calibration_stage.run(role_id, storage_backend=db_storage).model_dump()


def _run_icp(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return icp_stage.run(role_id, storage_backend=db_storage).model_dump()


def _run_talent_map(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return talent_map_stage.run(role_id, storage_backend=db_storage).model_dump()


def _run_search_strategy(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return search_strategy_stage.run(role_id, storage_backend=db_storage).model_dump()


def _run_interview_questions(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return interview_questions_stage.run(role_id, storage_backend=db_storage).model_dump()


def _run_add_candidate(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return candidate_analysis_stage.run(
        role_id, args["source_text"], args["role_family"],
        source_url=args.get("source_url", ""), storage_backend=db_storage,
        resume_file_key=args.get("resume_file_key"), resume_filename=args.get("resume_filename"),
    ).model_dump()


def _run_prioritize(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return prioritization_stage.run(role_id, args["candidate_id"], storage_backend=db_storage).model_dump()


def _run_screen(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return screening_stage.run(role_id, args["candidate_id"], storage_backend=db_storage).model_dump()


def _run_outreach(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return outreach_stage.run(role_id, args["candidate_id"], storage_backend=db_storage).model_dump()


def _run_conversation_summary(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return conversation_summary_stage.run(role_id, args["candidate_id"], storage_backend=db_storage).model_dump()


def _run_conversation_intelligence(role_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return conversation_summary_stage.run_intelligence(
        role_id, args["candidate_id"], storage_backend=db_storage
    ).model_dump()


for _kind, _fn in [
    ("intake", _run_intake),
    ("calibrate", _run_calibrate),
    ("icp", _run_icp),
    ("talent_map", _run_talent_map),
    ("search_strategy", _run_search_strategy),
    ("interview_questions", _run_interview_questions),
    ("add_candidate", _run_add_candidate),
    ("prioritize", _run_prioritize),
    ("screen", _run_screen),
    ("outreach", _run_outreach),
    ("conversation_summary", _run_conversation_summary),
    ("conversation_intelligence", _run_conversation_intelligence),
]:
    task_queue.register_runner(_kind, _fn)


# ── role-level pipeline stages ──────────────────────────────────────────
# Each POST enqueues a task and returns immediately (202 + task_id) instead
# of blocking on the model call; poll GET .../tasks/{task_id} for the
# result. See task_queue.py.


@app.post("/jobs/{role_id}/intake", status_code=202)
def intake(role_id: str, body: IntakeRequest, request: Request) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    _log(request, role_id, "requested JD intake")
    return task_queue.enqueue(role_id, "intake", {"jd_text": body.jd_text})


@app.post("/jobs/{role_id}/intake/upload")
async def upload_jd(role_id: str, request: Request, file: UploadFile = File(...)) -> dict[str, str]:
    # Extraction only (PDF/DOCX/TXT -> text), same helper the candidate
    # upload route uses — deliberately not a task: no LLM call happens
    # here, just text extraction, so the recruiter can review/edit the
    # extracted text in the same box the existing paste flow already
    # uses before clicking "Analyse JD" (unchanged, same commit path as
    # pasting always had — this route never writes job_description).
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    content = await file.read()
    try:
        text = resume_extraction.extract_text(file.filename or "", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if not text.strip():
        raise HTTPException(status_code=400, detail="couldn't extract any text from that file")
    _log(request, role_id, "uploaded JD file", detail=file.filename or "")
    return {"text": text}


@app.post("/jobs/{role_id}/calibrate", status_code=202)
def calibrate(role_id: str, request: Request) -> dict[str, Any]:
    _log(request, role_id, "requested calibration")
    return task_queue.enqueue(role_id, "calibrate", {})


@app.post("/jobs/{role_id}/icp", status_code=202)
def icp(role_id: str, request: Request) -> dict[str, Any]:
    _log(request, role_id, "requested ICP build")
    return task_queue.enqueue(role_id, "icp", {})


@app.post("/jobs/{role_id}/talent-map", status_code=202)
def talent_map(role_id: str, request: Request) -> dict[str, Any]:
    _log(request, role_id, "requested talent map")
    return task_queue.enqueue(role_id, "talent_map", {})


@app.post("/jobs/{role_id}/search-strategy", status_code=202)
def search_strategy(role_id: str, request: Request) -> dict[str, Any]:
    _log(request, role_id, "requested search strategy")
    return task_queue.enqueue(role_id, "search_strategy", {})


@app.post("/jobs/{role_id}/interview-questions", status_code=202)
def interview_questions(role_id: str, request: Request) -> dict[str, Any]:
    _log(request, role_id, "requested interview questions")
    return task_queue.enqueue(role_id, "interview_questions", {})


@app.patch("/jobs/{role_id}/icp/criteria")
def update_icp_criteria(role_id: str, body: IcpCriteriaRequest, request: Request) -> dict[str, Any]:
    # Rubric tuning (Phase 8): the recruiter's own direct edit, not an
    # AI-suggested one — deterministic, synchronous, same category as
    # set_recruiter_decision below.
    result = _run_stage(
        icp_stage.update_criteria, role_id,
        must_have=body.must_have, nice_to_have=body.nice_to_have, storage_backend=db_storage,
    )
    _log(request, role_id, "updated hiring criteria")
    return result.model_dump()


@app.patch("/jobs/{role_id}/job-description")
def update_job_description(role_id: str, body: JobDescriptionUpdateRequest, request: Request) -> dict[str, Any]:
    # The recruiter's own correction to the "here's what we understood"
    # JD review — same deterministic-edit category as update_icp_criteria
    # above, not an AI-suggested change.
    result = _run_stage(
        intake_stage.update_fields, role_id, storage_backend=db_storage, **body.model_dump(exclude_unset=True)
    )
    _log(request, role_id, "corrected JD extraction")
    return result.model_dump()


# ── task status (Phase 4) ───────────────────────────────────────────────


@app.get("/jobs/{role_id}/tasks/{task_id}")
def get_task(role_id: str, task_id: str) -> dict[str, Any]:
    task = db_storage.get_task(task_id)
    if task is None or task["role_id"] != role_id:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")
    return task


@app.get("/jobs/{role_id}/tasks")
def list_tasks(role_id: str) -> list[dict[str, Any]]:
    return db_storage.list_tasks(role_id)


# ── candidates ───────────────────────────────────────────────────────────


@app.post("/jobs/{role_id}/candidates", status_code=202)
def add_candidate(role_id: str, body: CandidateAddRequest, request: Request) -> dict[str, Any]:
    _log(request, role_id, "added candidate (pasted text)")
    return task_queue.enqueue(role_id, "add_candidate", {
        "source_text": body.source_text, "role_family": body.role_family, "source_url": body.source_url,
    })


@app.post("/jobs/{role_id}/candidates/upload", status_code=202)
async def upload_candidate(
    role_id: str,
    request: Request,
    file: UploadFile = File(...),
    role_family: str = Form(...),
    source_url: str = Form(""),
) -> dict[str, Any]:
    # Extraction only, then the exact same "add_candidate" task the
    # paste-text route above enqueues — no separate stage or runner.
    content = await file.read()
    try:
        text = resume_extraction.extract_text(file.filename or "", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if not text.strip():
        raise HTTPException(status_code=400, detail="couldn't extract any text from that file")
    # Best-effort: persist the original file alongside the extracted
    # text. Returns None (silently) when object storage isn't
    # configured in this environment — the upload still succeeds either
    # way, exactly as it always has, since extraction never depended on
    # this landing anywhere.
    resume_file_key = file_storage.upload_resume(
        role_id, file.filename or "resume", content, file.content_type or "application/octet-stream"
    )
    _log(request, role_id, "added candidate (resume upload)", detail=file.filename or "")
    return task_queue.enqueue(role_id, "add_candidate", {
        "source_text": text, "role_family": role_family, "source_url": source_url,
        "resume_file_key": resume_file_key, "resume_filename": file.filename or None,
    })


@app.post("/jobs/{role_id}/candidates/bulk-import", status_code=202)
async def bulk_import_candidates(
    role_id: str, request: Request, file: UploadFile = File(...), role_family: str = Form(...),
) -> dict[str, Any]:
    """CSV bulk import (Batch B): a recruiter adding candidates one at a
    time all day is exactly the repetitive work this should remove. Same
    add_candidate task the paste/upload routes above enqueue — just
    triggered once per row instead of once per click, so there's no
    separate stage or runner to maintain. Expects a 'notes' (or
    'source_text'/'resume'/'text') column with each candidate's raw
    resume/notes text, and an optional 'source_url' column; any other
    columns are ignored rather than rejected, so an existing spreadsheet
    export doesn't need reshaping first."""
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400, detail="couldn't read that file as UTF-8 text — export the CSV as UTF-8 and try again"
        ) from None

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="that CSV has no header row")
    notes_col = next(
        (c for c in reader.fieldnames if c.strip().lower() in ("notes", "source_text", "resume", "text")), None
    )
    if notes_col is None:
        raise HTTPException(
            status_code=400,
            detail="CSV needs a 'notes' column with each candidate's resume/notes text",
        )
    url_col = next((c for c in reader.fieldnames if c.strip().lower() in ("source_url", "url", "link")), None)

    task_ids: list[str] = []
    skipped = 0
    for row in reader:
        source_text = (row.get(notes_col) or "").strip()
        if not source_text:
            skipped += 1
            continue
        source_url = (row.get(url_col) or "").strip() if url_col else ""
        task = task_queue.enqueue(role_id, "add_candidate", {
            "source_text": source_text, "role_family": role_family, "source_url": source_url,
        })
        task_ids.append(task["task_id"])

    _log(request, role_id, "bulk-imported candidates (CSV)", detail=f"{len(task_ids)} queued, {skipped} skipped")
    return {"task_ids": task_ids, "queued": len(task_ids), "skipped_empty_rows": skipped}


@app.get("/jobs/{role_id}/candidates")
def list_candidates(role_id: str) -> list[dict[str, Any]]:
    state = db_storage.load_role(role_id)
    candidates = state.get("candidates") or {}
    prioritizations = state.get("prioritizations") or {}
    return [
        {**c, "candidate_id": cid, "prioritization": prioritizations.get(cid)}
        for cid, c in candidates.items()
    ]


@app.get("/jobs/{role_id}/candidates/export.csv")
def export_candidates_csv(role_id: str) -> Response:
    # Deterministic formatting, not a model call — same category as the
    # funnel/analytics routes. Recruiters share this with a hiring
    # manager who doesn't have (or want) a login.
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    state = db_storage.load_role(role_id)
    candidates = state.get("candidates") or {}
    prioritizations = state.get("prioritizations") or {}
    funnel = state.get("funnel") or {}
    outreach = state.get("outreach") or {}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Name", "Current title", "Current company", "Tier", "Recruiter decision",
        "Pipeline stage", "Outreach drafted", "Source URL",
    ])
    for cid, c in candidates.items():
        p = prioritizations.get(cid) or {}
        writer.writerow([
            c.get("name", ""), c.get("current_title", ""), c.get("current_company", ""),
            p.get("tier", ""), p.get("recruiter_decision", "") or "",
            (funnel.get(cid) or {}).get("current_stage", "IDENTIFIED"),
            "yes" if cid in outreach else "no",
            c.get("source_url", ""),
        ])

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{role_id}-candidates.csv"'},
    )


@app.get("/jobs/{role_id}/candidates/export.json")
def export_candidates_json(role_id: str) -> dict[str, Any]:
    # Structured counterpart to export.csv above — for feeding an ATS or
    # any other downstream system, not for a human to open directly.
    # Same deterministic-formatting category, same no-model-call reason
    # this is synchronous.
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    state = db_storage.load_role(role_id)
    candidates = state.get("candidates") or {}
    prioritizations = state.get("prioritizations") or {}
    funnel = state.get("funnel") or {}
    outreach = state.get("outreach") or {}
    return {
        "role_id": role_id,
        "candidates": [
            {
                **c,
                "candidate_id": cid,
                "prioritization": prioritizations.get(cid),
                "pipeline_stage": (funnel.get(cid) or {}).get("current_stage", "IDENTIFIED"),
                "stage_history": (funnel.get(cid) or {}).get("stage_history", []),
                "outreach_drafted": cid in outreach,
            }
            for cid, c in candidates.items()
        ],
    }


@app.post("/jobs/{role_id}/candidates/{candidate_id}/prioritize", status_code=202)
def prioritize(role_id: str, candidate_id: str, request: Request) -> dict[str, Any]:
    _log(request, role_id, "requested prioritization", candidate_id=candidate_id)
    return task_queue.enqueue(role_id, "prioritize", {"candidate_id": candidate_id})


@app.post("/jobs/{role_id}/candidates/{candidate_id}/screen", status_code=202)
def screen(role_id: str, candidate_id: str, request: Request) -> dict[str, Any]:
    _log(request, role_id, "requested screening", candidate_id=candidate_id)
    return task_queue.enqueue(role_id, "screen", {"candidate_id": candidate_id})


@app.post("/jobs/{role_id}/candidates/{candidate_id}/outreach", status_code=202)
def outreach(role_id: str, candidate_id: str, request: Request) -> dict[str, Any]:
    _log(request, role_id, "requested outreach draft", candidate_id=candidate_id)
    return task_queue.enqueue(role_id, "outreach", {"candidate_id": candidate_id})


@app.patch("/jobs/{role_id}/candidates/{candidate_id}/share")
def set_candidate_share(role_id: str, candidate_id: str, body: CandidateShareRequest, request: Request) -> dict[str, Any]:
    # Client sharing (recruiter/client/admin permission model): a
    # recruiter's own explicit, per-candidate opt-in — never automatic,
    # never something a stage or the model sets. See
    # db_storage.set_candidate_client_visible / get_public_role_summary
    # for exactly what a client sees once shared.
    result = _run_stage(db_storage.set_candidate_client_visible, role_id, candidate_id, body.visible)
    _log(
        request, role_id,
        "shared candidate with client" if body.visible else "unshared candidate from client",
        candidate_id=candidate_id,
    )
    return result


@app.post("/jobs/{role_id}/candidates/{candidate_id}/outreach/mark-sent")
def mark_outreach_sent(role_id: str, candidate_id: str, request: Request) -> dict[str, Any]:
    # Deterministic bookkeeping, not a model call — synchronous like the
    # funnel routes below, not queued like the LLM-touching routes above.
    result = _run_stage(outreach_stage.mark_sent, role_id, candidate_id, storage_backend=db_storage)
    _log(request, role_id, "marked outreach sent", candidate_id=candidate_id)
    return result


@app.post("/jobs/{role_id}/candidates/{candidate_id}/decision")
def set_recruiter_decision(
    role_id: str, candidate_id: str, body: RecruiterDecisionRequest, request: Request
) -> dict[str, Any]:
    # Same category as mark-sent above: deterministic, recruiter-authored,
    # synchronous — never something a stage or the model sets.
    result = _run_stage(
        prioritization_stage.set_recruiter_decision, role_id, candidate_id, body.decision,
        storage_backend=db_storage,
    )
    _log(request, role_id, f"set decision: {body.decision}", candidate_id=candidate_id)
    _maybe_fire_decision_webhook(role_id, candidate_id, body.decision)
    return result


@app.post("/jobs/{role_id}/candidates/{candidate_id}/placement")
def set_placement(role_id: str, candidate_id: str, body: PlacementRequest, request: Request) -> dict[str, Any]:
    # Same category as decision/mark-sent above: deterministic,
    # recruiter-authored, synchronous — the one outcome this system
    # tracks in dollar terms.
    result = _run_stage(
        prioritization_stage.set_placement, role_id, candidate_id,
        placed=body.placed, fee=body.fee, storage_backend=db_storage,
    )
    _log(
        request, role_id, "marked candidate placed" if body.placed else "cleared placement",
        detail=f"fee={body.fee}" if body.placed else "", candidate_id=candidate_id,
    )
    return result


@app.patch("/jobs/{role_id}/candidates/{candidate_id}/note")
def set_candidate_note(role_id: str, candidate_id: str, body: CandidateNoteRequest, request: Request) -> dict[str, Any]:
    # A recruiter's own private text, not logged to the activity feed in
    # full (the note content is private; logging that a note was edited
    # would defeat that) — just a short marker that it changed.
    result = _run_stage(db_storage.set_candidate_note, role_id, candidate_id, body.note)
    _log(request, role_id, "edited candidate note", candidate_id=candidate_id)
    return result


@app.patch("/jobs/{role_id}/candidates/{candidate_id}/contact")
def set_candidate_contact(role_id: str, candidate_id: str, body: CandidateContactRequest, request: Request) -> dict[str, Any]:
    # Recruiter-entered/confirmed contact info for the WhatsApp/call
    # handoff below — same deterministic, recruiter-authored category as
    # the note route above.
    result = _run_stage(db_storage.set_candidate_contact, role_id, candidate_id, phone=body.phone, email=body.email)
    _log(request, role_id, "updated candidate contact info", candidate_id=candidate_id)
    return result


@app.get("/jobs/{role_id}/candidates/{candidate_id}/resume")
def get_candidate_resume_url(role_id: str, candidate_id: str) -> dict[str, Any]:
    """Returns a time-limited download link for the original uploaded
    resume file — never proxies the file bytes through this app. 404 if
    this candidate has no stored resume (added via pasted text, or
    object storage wasn't configured at upload time)."""
    state = db_storage.load_role(role_id)
    candidate = (state.get("candidates") or {}).get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"candidate '{candidate_id}' not found for role '{role_id}'")
    file_key = candidate.get("resume_file_key")
    if not file_key:
        raise HTTPException(status_code=404, detail="no resume file stored for this candidate")
    url = file_storage.get_resume_download_url(file_key)
    if url is None:
        raise HTTPException(status_code=503, detail="resume storage isn't available right now")
    return {"url": url, "filename": candidate.get("resume_filename")}


# ── conversation history (email/WhatsApp/call demo) ─────────────────────
# This repo never sends anything itself — see outreach.py's docstring.
# WhatsApp/call "sending" here means the wa.me/tel: device handoff (see
# the frontend's confirm popup), which the recruiter's own device carries
# out; logging happens the moment they confirm, not on delivery, because
# there is no messaging/telephony backend to confirm delivery with. A
# transcript is manually entered after a call today — wiring a real
# transcription provider (Twilio Voice Intelligence, Exotel, etc.) would
# populate the same field automatically, no schema change required.


@app.get("/jobs/{role_id}/candidates/{candidate_id}/communications")
def get_communications(role_id: str, candidate_id: str) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    entries = _run_stage(db_storage.list_communications, role_id, candidate_id)
    summary = _run_stage(db_storage.get_conversation_summary, role_id, candidate_id)
    candidate = db_storage.load_role(role_id).get("candidates", {}).get(candidate_id, {})
    intelligence = candidate.get("conversation_intelligence")
    return {"entries": entries, "intelligence": intelligence, **summary}


@app.post("/jobs/{role_id}/candidates/{candidate_id}/communications", status_code=202)
def log_communication(
    role_id: str, candidate_id: str, body: CommunicationLogRequest, request: Request
) -> dict[str, Any]:
    entry = _run_stage(
        db_storage.log_communication, role_id, candidate_id, channel=body.channel, direction=body.direction,
        content=body.content, transcript=body.transcript, contact_used=body.contact_used,
        logged_by=request.state.user["email"],
    )
    _log(request, role_id, f"logged {body.channel} communication", candidate_id=candidate_id)
    task = task_queue.enqueue(role_id, "conversation_summary", {"candidate_id": candidate_id})
    intelligence_task = task_queue.enqueue(role_id, "conversation_intelligence", {"candidate_id": candidate_id})
    return {"entry": entry, "summary_task": task, "intelligence_task": intelligence_task}


# ── funnel ───────────────────────────────────────────────────────────────


@app.post("/jobs/{role_id}/funnel/{candidate_id}")
def funnel_update(role_id: str, candidate_id: str, body: FunnelUpdateRequest, request: Request) -> dict[str, Any]:
    result = _run_stage(
        funnel_stage.update, role_id, candidate_id, body.stage.upper(),
        note=body.note, scheduled_at=body.scheduled_at, storage_backend=db_storage,
    )
    detail = body.stage.upper() + (f" (scheduled {body.scheduled_at})" if body.scheduled_at else "")
    _log(request, role_id, "moved pipeline stage", detail=detail, candidate_id=candidate_id)
    return result


@app.get("/jobs/{role_id}/funnel/report")
def funnel_report(role_id: str) -> dict[str, Any]:
    result = funnel_stage.report(role_id, storage_backend=db_storage)
    return result.model_dump()


# ── external integrations (Google Workspace / Calendly / telephony) ────
# Account-level connection status, distinct from the per-job outbound
# webhook below. None of these are actually wired up — there are no
# OAuth apps or telephony credentials in this environment — so this is
# deliberately just the honest status + architecture the real connect
# flow would slot into later, never a faked "connected" state. See each
# provider's docstring in INTEGRATION_PROVIDERS.

INTEGRATION_PROVIDERS: dict[str, dict[str, str]] = {
    "google_workspace": {
        "label": "Google Workspace",
        "env_var": "GOOGLE_OAUTH_CLIENT_ID",
        "capabilities": "Gmail, Google Calendar, Google Meet — schedule interviews and create Meet links from a candidate's record.",
    },
    "calendly": {
        "label": "Calendly",
        "env_var": "CALENDLY_CLIENT_ID",
        "capabilities": "Send a candidate a scheduling link for a screening, hiring-manager, technical, or final interview.",
    },
    "telephony": {
        "label": "Phone / telephony",
        "env_var": "TELEPHONY_PROVIDER_API_KEY",
        "capabilities": "Place outbound calls, record them, and receive an automatic transcript — today's Call button is a device (tel:) handoff, not a connected line.",
    },
}


@app.get("/integrations/status")
def integrations_status() -> list[dict[str, Any]]:
    # "environment_configured" means the provider's own credentials are
    # present in this environment's env vars — it is NOT the same as
    # "connected": no OAuth callback flow exists yet, so even a fully
    # configured environment reports not_connected until that's built.
    return [
        {
            "provider": provider,
            "label": meta["label"],
            "status": "not_connected",
            "environment_configured": bool(os.environ.get(meta["env_var"])),
            "capabilities": meta["capabilities"],
        }
        for provider, meta in INTEGRATION_PROVIDERS.items()
    ]


# ── integrations (Phase 8) ──────────────────────────────────────────────
# A per-job outbound webhook the recruiter configures themselves — see
# webhooks.py's module docstring. Config is a generic JobSection, same
# storage category as icp/calibration/etc.


@app.get("/jobs/{role_id}/integrations")
def get_integrations(role_id: str) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    integrations = db_storage.load_role(role_id).get("integrations") or {}
    return {"webhook_url": integrations.get("webhook_url", "")}


@app.post("/jobs/{role_id}/integrations/webhook")
def set_webhook(role_id: str, body: WebhookConfigRequest, request: Request) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    db_storage.merge_section(role_id, "integrations", {"webhook_url": body.webhook_url})
    _log(request, role_id, "configured webhook", detail=body.webhook_url)
    return {"webhook_url": body.webhook_url}


@app.post("/jobs/{role_id}/integrations/webhook/test")
def test_webhook(role_id: str, request: Request) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    integrations = db_storage.load_role(role_id).get("integrations") or {}
    webhook_url = integrations.get("webhook_url")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="no webhook URL configured for this job yet")
    result = webhooks.send_webhook(webhook_url, "webhook.test", {"role_id": role_id})
    _log(request, role_id, "sent test webhook", detail=result["detail"])
    return result


@app.post("/funnel/forecast")
def funnel_forecast(body: ForecastRequest) -> dict[str, Any]:
    assumptions = _run_stage(
        ForecastAssumptions,
        source=body.source,
        screen_to_hm_interview=body.screen_to_hm,
        hm_interview_to_final=body.hm_to_final,
        final_to_offer=body.final_to_offer,
        offer_to_accept=body.offer_to_accept,
        contacted_to_screen=body.contacted_to_screen,
        sourced_to_contacted=body.sourced_to_contacted,
    )
    result = funnel_stage.forecast(body.hires, body.weeks, assumptions)
    return result.model_dump()


# ── AI chat / orchestrator (Phase 3) ──────────────────────────────────
# Every route here is a thin wrapper too: orchestrator.py holds the tool
# loop, this file only persists history/pending-proposal state and turns
# a raw message list into something a chat UI can render. See
# orchestrator.py's module docstring for the confirm-before-mutate design
# — apply_hiring_profile_edit below is the only place a hiring-profile
# edit actually happens, and it's called from here, never from the model.


def _display_messages(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Collapse the raw tool-use transcript into something renderable:
    user/assistant text turns, with tool calls noted inline rather than
    shown as raw JSON. Tool-result turns (role="user" carrying
    tool_result blocks) are internal plumbing and are skipped."""
    display: list[dict[str, str]] = []
    for msg in history:
        content = msg.get("content")
        if isinstance(content, str):
            display.append({"role": msg["role"], "text": content})
            continue
        if not isinstance(content, list):
            continue
        if any(block.get("type") == "tool_result" for block in content if isinstance(block, dict)):
            continue  # tool-result carrier message, not shown
        text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        tool_notes = [
            f"[used {b.get('name')}]" for b in content if isinstance(b, dict) and b.get("type") == "tool_use"
        ]
        text = " ".join(p for p in text_parts if p)
        if tool_notes and not text:
            text = " ".join(tool_notes)
        if text:
            display.append({"role": msg["role"], "text": text})
    return display


@app.get("/jobs/{role_id}/chat")
def get_chat(role_id: str) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    state = db_storage.load_role(role_id)
    return {
        "messages": _display_messages(state.get("chat_history") or []),
        "pending_proposal": state.get("chat_pending"),
    }


@app.post("/jobs/{role_id}/chat")
def post_chat(role_id: str, body: ChatRequest) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    state = db_storage.load_role(role_id)
    history = state.get("chat_history") or []

    result = _run_stage(
        orchestrator.run_chat_turn, role_id, body.message, history, storage_backend=db_storage
    )

    db_storage.merge_section(role_id, "chat_history", result["history"])
    db_storage.merge_section(role_id, "chat_pending", result["pending_proposal"])
    return {"reply": result["reply"], "pending_proposal": result["pending_proposal"]}


@app.post("/jobs/{role_id}/chat/confirm")
def confirm_chat_proposal(role_id: str, body: ChatConfirmRequest, request: Request) -> dict[str, Any]:
    if not db_storage.job_exists(role_id):
        raise HTTPException(status_code=404, detail=f"job '{role_id}' not found")
    state = db_storage.load_role(role_id)
    pending = state.get("chat_pending")
    if not pending:
        raise HTTPException(status_code=400, detail="no pending proposal for this job")

    if body.approve:
        icp = orchestrator.apply_hiring_profile_edit(
            role_id, pending["field"], pending["action"], pending["value"], storage_backend=db_storage
        )
        note = f"Applied: {pending['description']}"
    else:
        icp = state.get("icp")
        note = f"Declined: {pending['description']}"

    db_storage.merge_section(role_id, "chat_pending", None)
    history = state.get("chat_history") or []
    history.append({"role": "assistant", "content": [{"type": "text", "text": note}]})
    db_storage.merge_section(role_id, "chat_history", history)
    _log(request, role_id, "AI chat proposal " + ("applied" if body.approve else "declined"), detail=pending["description"])

    return {"applied": body.approve, "message": note, "icp": icp}
