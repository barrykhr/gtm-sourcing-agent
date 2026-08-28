/**
 * Typed client for the FastAPI service (gtm-sourcing-agent/src/gtm_sourcing_agent/api.py).
 * One function per route, matching the API 1:1 — this file has no business
 * logic of its own, it's a thin wire-format boundary, mirroring how
 * stages/*.py has no HTTP knowledge. Every call throws ApiError with the
 * backend's `detail` message on a non-2xx response, so pages can show the
 * same one-line, no-jargon error the CLI shows instead of a stack trace.
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include", // Phase 7: every route but /health and /auth/* needs the session cookie
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // non-JSON error body — fall back to statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
const get = <T>(path: string) => request<T>(path);
const patch = <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

// Every stage response is validated server-side against a Pydantic schema
// (see models/*.py) — the frontend doesn't re-declare each one, since the
// UI only reads a handful of fields per response (see the typed shapes
// below for the ones it does). `Json` is the escape hatch for the rest.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = Record<string, any>;

// ── auth (Phase 7, multi-account in Phase 8) ────────────────────────────
// Session-cookie auth, any number of accounts sharing one workspace — see
// api.py's auth section and auth.py's module docstring for why this
// isn't OAuth/SSO or per-user data isolation.

export type AuthUser = { id: string; email: string };
export type AuthStatus = { signup_requires_code: boolean };

export const getAuthStatus = () => get<AuthStatus>("/auth/status");
export const getMe = () => get<AuthUser>("/auth/me");
export const signup = (email: string, password: string, signupCode?: string) =>
  post<AuthUser>("/auth/signup", { email, password, signup_code: signupCode ?? null });
export const login = (email: string, password: string) => post<AuthUser>("/auth/login", { email, password });
export const logout = () => post<{ status: string }>("/auth/logout");

// ── types (only the fields the UI actually reads) ─────────────────────────

export type PipelineStatus = {
  intake: boolean;
  calibration: boolean;
  icp: boolean;
  talent_map: boolean;
  search_strategy: boolean;
};

export const JOB_LIFECYCLE_STATUSES = ["OPEN", "ON_HOLD", "FILLED", "CANCELLED"] as const;
export type JobLifecycleStatus = (typeof JOB_LIFECYCLE_STATUSES)[number];
export const JOB_LIFECYCLE_LABELS: Record<JobLifecycleStatus, string> = {
  OPEN: "Open", ON_HOLD: "On hold", FILLED: "Filled", CANCELLED: "Cancelled",
};
// "Closed" = no longer an active req — both the dashboard's default
// hide-closed-jobs filter and the job page badge's color use this.
export const CLOSED_LIFECYCLE_STATUSES: JobLifecycleStatus[] = ["FILLED", "CANCELLED"];

export type JobSummary = {
  role_id: string;
  title: string;
  role_family: string | null;
  lifecycle_status: JobLifecycleStatus;
  owner_email: string | null;
  created_at: string;
  updated_at: string;
  status: PipelineStatus;
  next_stage: string | null;
};

export type JobDetail = JobSummary & {
  state: Json;
};

export type EvidencedFact = { fact: string; evidence_level: "VERIFIED" | "NOT_STATED" | "INFERRED"; source: string };

export type Candidate = {
  candidate_id: string;
  canonical_candidate_id: string;
  name: string;
  current_company: string;
  current_title: string;
  location: string;
  relevant_experience_summary: string;
  achievements: EvidencedFact[];
  metrics: EvidencedFact[];
  concerns: string[];
  recommended_next_action: string;
  source_url: string;
  note: string;
  prioritization: {
    tier: "A" | "B" | "C" | "D";
    why_they_fit: string[];
    what_is_unknown: string[];
    what_to_validate: string[];
    recruiter_decision: string | null;
  } | null;
};

export type CandidateEvaluationSummary = {
  role_id: string;
  job_title: string;
  candidate_evaluation_id: string;
  tier: "A" | "B" | "C" | "D" | null;
  why_they_fit: string[] | null;
  recruiter_decision: string | null;
};

export type CanonicalCandidate = {
  candidate_id: string;
  name: string;
  current_company: string;
  current_title: string;
  location: string;
  source_url: string;
  evaluations: CandidateEvaluationSummary[];
};

// ── jobs ────────────────────────────────────────────────────────────────

export const listJobs = () => get<JobSummary[]>("/jobs");

export const createJob = (title: string, role_family = "", role_id?: string) =>
  post<JobSummary>("/jobs", { title, role_family, role_id });

export const getJob = (roleId: string) => get<JobDetail>(`/jobs/${roleId}`);

// Role templates (Phase 8): start a new job from an existing one's
// hiring strategy instead of a blank intake — see db_storage.clone_role's
// docstring for exactly what carries over (never candidates/pipeline).
export const cloneJob = (roleId: string, title: string, roleFamily = "", newRoleId?: string) =>
  post<JobSummary>(`/jobs/${roleId}/clone`, { title, role_family: roleFamily, role_id: newRoleId });

// Who did what, when (Phase 8) — once more than one account can touch
// the same shared workspace, this is the only place that's visible.
export type ActivityEntry = {
  id: number;
  role_id: string;
  user_email: string;
  action: string;
  detail: string;
  candidate_id: string | null;
  created_at: string;
};

export const getActivity = (roleId: string) => get<ActivityEntry[]>(`/jobs/${roleId}/activity`);

// Job lifecycle + ownership (Phase 10) — both deterministic,
// recruiter-authored, never set by a stage or the model.
export const setJobLifecycle = (roleId: string, lifecycleStatus: JobLifecycleStatus) =>
  patch<JobSummary>(`/jobs/${roleId}/lifecycle`, { lifecycle_status: lifecycleStatus });

export const setJobOwner = (roleId: string, ownerEmail: string | null) =>
  patch<JobSummary>(`/jobs/${roleId}/owner`, { owner_email: ownerEmail });

// Global search (Phase 10) — jobs by title/role_id, candidates by name.
export type SearchResult = {
  jobs: { role_id: string; title: string }[];
  candidates: { candidate_id: string; name: string; current_title: string; current_company: string }[];
};

export const search = (q: string) => get<SearchResult>(`/search?q=${encodeURIComponent(q)}`);

// ── background tasks (Phase 4) ────────────────────────────────────────
// Every LLM-touching stage route below enqueues a task and returns 202
// immediately (see task_queue.py) instead of blocking on the model call.
// waitForTask() polls the real status to completion so call sites below
// keep the exact shape they had before Phase 4 (`await runIcp(...)`
// resolves with the stage result, or throws the real error) — what
// changed underneath is that a slow real model call no longer ties up
// an HTTP request/server thread for its whole duration, it's a handful
// of short polls instead.

export type TaskStatus = "pending" | "running" | "succeeded" | "failed";

export type Task = {
  task_id: string;
  role_id: string;
  kind: string;
  status: TaskStatus;
  args: Json;
  result: Json | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};

export const getTask = (roleId: string, taskId: string) => get<Task>(`/jobs/${roleId}/tasks/${taskId}`);
export const listTasks = (roleId: string) => get<Task[]>(`/jobs/${roleId}/tasks`);

const TASK_POLL_INTERVAL_MS = 250;

async function waitForTask<T>(roleId: string, task: Task, onStatus?: (t: Task) => void): Promise<T> {
  let current = task;
  onStatus?.(current);
  while (current.status === "pending" || current.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, TASK_POLL_INTERVAL_MS));
    current = await getTask(roleId, current.task_id);
    onStatus?.(current);
  }
  if (current.status === "failed") {
    throw new ApiError(502, current.error ?? "Task failed.");
  }
  return current.result as T;
}

// ── role-level stages ──────────────────────────────────────────────────

export const runIntake = async (roleId: string, jdText: string) =>
  waitForTask<Json>(roleId, await post<Task>(`/jobs/${roleId}/intake`, { jd_text: jdText }));

export const runCalibrate = async (roleId: string) =>
  waitForTask<Json>(roleId, await post<Task>(`/jobs/${roleId}/calibrate`));

export const runIcp = async (roleId: string) =>
  waitForTask<Json>(roleId, await post<Task>(`/jobs/${roleId}/icp`));

// Rubric tuning (Phase 8) — the recruiter's own direct edit to the ICP's
// must-have/nice-to-have criteria, not an AI-suggested one (that's the
// AI Copilot's propose/apply flow, unrelated to this). Deterministic, no
// task to poll. Pass undefined for a list to leave it unchanged.
export const updateIcpCriteria = (roleId: string, mustHave?: string[], niceToHave?: string[]) =>
  patch<Json>(`/jobs/${roleId}/icp/criteria`, { must_have: mustHave, nice_to_have: niceToHave });

export const runTalentMap = async (roleId: string) =>
  waitForTask<Json>(roleId, await post<Task>(`/jobs/${roleId}/talent-map`));

export const runSearchStrategy = async (roleId: string) =>
  waitForTask<Json>(roleId, await post<Task>(`/jobs/${roleId}/search-strategy`));

// ── candidates ─────────────────────────────────────────────────────────

export const listCandidates = (roleId: string) => get<Candidate[]>(`/jobs/${roleId}/candidates`);

export const addCandidate = async (roleId: string, sourceText: string, roleFamily: string, sourceUrl = "") =>
  waitForTask<Candidate>(
    roleId,
    await post<Task>(`/jobs/${roleId}/candidates`, {
      source_text: sourceText,
      role_family: roleFamily,
      source_url: sourceUrl,
    })
  );

// Resume upload (Phase 8) — multipart, so it bypasses `post`'s forced
// application/json header; the browser sets its own multipart boundary
// when Content-Type is left unset. Extraction happens server-side
// (resume_extraction.py) and then joins the same add-candidate task path.
async function postForm<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", credentials: "include", body: formData });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // non-JSON error body — fall back to statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const uploadCandidate = async (roleId: string, file: File, roleFamily: string, sourceUrl = "") => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("role_family", roleFamily);
  formData.append("source_url", sourceUrl);
  return waitForTask<Candidate>(roleId, await postForm<Task>(`/jobs/${roleId}/candidates/upload`, formData));
};

export const prioritizeCandidate = async (roleId: string, candidateId: string) =>
  waitForTask<Json>(roleId, await post<Task>(`/jobs/${roleId}/candidates/${candidateId}/prioritize`));

export const screenCandidate = async (roleId: string, candidateId: string) =>
  waitForTask<Json>(roleId, await post<Task>(`/jobs/${roleId}/candidates/${candidateId}/screen`));

export const outreachCandidate = async (roleId: string, candidateId: string) =>
  waitForTask<Json>(roleId, await post<Task>(`/jobs/${roleId}/candidates/${candidateId}/outreach`));

// Records that the recruiter actually reached out through some channel
// outside this product — never sends anything itself (Architecture
// §1.4, §7). Deterministic bookkeeping, so no task to poll: same
// request/response shape as before Phase 4's async routes.
export type MarkSentResult = { candidate_id: string; sent_at: string; funnel_stage: string };

export const markOutreachSent = (roleId: string, candidateId: string) =>
  post<MarkSentResult>(`/jobs/${roleId}/candidates/${candidateId}/outreach/mark-sent`);

// The only thing that can move a candidate out of the active pool
// (Architecture §1.1) — always recruiter-authored, never set by any
// stage. Requires the candidate to already be prioritized. Pass "" to
// clear a previously recorded decision. Deterministic, not a task.
export type DecisionResult = { candidate_id: string; recruiter_decision: string | null };

export const setRecruiterDecision = (roleId: string, candidateId: string, decision: string) =>
  post<DecisionResult>(`/jobs/${roleId}/candidates/${candidateId}/decision`, { decision });

// A recruiter's own private impression, separate from the structured
// decision above and from the model's evidence-labeled output — nothing
// else in the product reads this (Phase 10).
export const setCandidateNote = (roleId: string, candidateId: string, note: string) =>
  patch<{ candidate_id: string; note: string }>(`/jobs/${roleId}/candidates/${candidateId}/note`, { note });

// ── integrations / outbound webhook (Phase 8) ──────────────────────────
// A real HTTP POST to a URL the recruiter configures for their own job —
// see webhooks.py's module docstring. Fires automatically on a "pursue"
// decision; the test button below fires it on demand for any URL.

export const getWebhookConfig = (roleId: string) => get<{ webhook_url: string }>(`/jobs/${roleId}/integrations`);

export const setWebhookConfig = (roleId: string, webhookUrl: string) =>
  post<{ webhook_url: string }>(`/jobs/${roleId}/integrations/webhook`, { webhook_url: webhookUrl });

export const testWebhook = (roleId: string) =>
  post<{ ok: boolean; detail: string }>(`/jobs/${roleId}/integrations/webhook/test`);

// ── global candidate roster (Phase 2) ─────────────────────────────────

export const listCandidatesGlobal = () => get<CanonicalCandidate[]>("/candidates");

export const getCandidateGlobal = (candidateId: string) =>
  get<CanonicalCandidate>(`/candidates/${candidateId}`);

// ── cross-job analytics (Phase 6) ──────────────────────────────────────
// Dashboard-level view across every job — distinct from a single job's
// Analytics tab (getFunnelReport), which is one role's funnel conversion.

export type AnalyticsOverview = {
  total_jobs: number;
  total_candidates: number;
  total_evaluations: number;
  tier_distribution: { A: number; B: number; C: number; D: number; not_prioritized: number };
  decisions_recorded: number;
  decisions_pending: number;
  decision_breakdown: Record<string, number>;
};

export const getAnalyticsOverview = () => get<AnalyticsOverview>("/analytics/overview");

// Two lists a recruiter would otherwise only notice by checking every
// job's Pipeline tab themselves (Phase 8).
export type AttentionItem = {
  role_id: string;
  job_title: string;
  candidate_id: string;
  candidate_name: string;
  current_stage: string;
};
export type NeedsFollowUpItem = AttentionItem & { days_in_stage: number };
export type UpcomingInterviewItem = AttentionItem & { scheduled_at: string };
export type AttentionNeeded = {
  needs_follow_up: NeedsFollowUpItem[];
  upcoming_interviews: UpcomingInterviewItem[];
};

export const getAttentionNeeded = () => get<AttentionNeeded>("/analytics/attention");

// ── AI chat (Phase 3) ─────────────────────────────────────────────────
// Real natural-language routing is unverified without a live API key —
// see docs/product-plan.md Phase 3. What's verified here is the plumbing:
// history persistence and the confirm-before-mutate flow for hiring-
// profile edits.

export type ChatMessage = { role: "user" | "assistant"; text: string };

export type PendingProposal = {
  field: string;
  action: string;
  value: string;
  description: string;
  impact: string;
  role_id: string;
};

export const getChat = (roleId: string) =>
  get<{ messages: ChatMessage[]; pending_proposal: PendingProposal | null }>(`/jobs/${roleId}/chat`);

export const postChat = (roleId: string, message: string) =>
  post<{ reply: string; pending_proposal: PendingProposal | null }>(`/jobs/${roleId}/chat`, { message });

export const confirmChatProposal = (roleId: string, approve: boolean) =>
  post<{ applied: boolean; message: string; icp: Json }>(`/jobs/${roleId}/chat/confirm`, { approve });

// ── funnel ─────────────────────────────────────────────────────────────

export const updateFunnelStage = (
  roleId: string, candidateId: string, stage: string, note = "", scheduledAt?: string
) => post<Json>(`/jobs/${roleId}/funnel/${candidateId}`, { stage, note, scheduled_at: scheduledAt ?? null });

export const getFunnelReport = (roleId: string) => get<Json>(`/jobs/${roleId}/funnel/report`);

export const FUNNEL_STAGES = [
  "IDENTIFIED", "REVIEWED", "SHORTLISTED", "CONTACTED", "RESPONDED", "INTERESTED",
  "RECRUITER_SCREEN", "HM_INTERVIEW", "FINAL_INTERVIEW", "OFFER", "ACCEPTED", "JOINED",
] as const;
