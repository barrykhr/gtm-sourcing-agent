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
export type AuthStatus = { signup_requires_code: boolean; google_client_id: string | null };

export const getAuthStatus = () => get<AuthStatus>("/auth/status");
export const getMe = () => get<AuthUser>("/auth/me");
export const signup = (email: string, password: string, signupCode?: string) =>
  post<AuthUser>("/auth/signup", { email, password, signup_code: signupCode ?? null });
export const login = (email: string, password: string) => post<AuthUser>("/auth/login", { email, password });
export const googleLogin = (credential: string) => post<AuthUser>("/auth/google", { credential });
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
  client_name: string | null;
  share_token: string | null;
  lifecycle_status: JobLifecycleStatus;
  owner_email: string | null;
  // Revenue basis (see revenue.py) — recruiter-entered, never AI-inferred.
  // expected_revenue is role_value * REVENUE_MARGIN_PERCENTAGE, computed
  // server-side; null (not 0) when role_value isn't set.
  role_value: number | null;
  expected_revenue: number | null;
  created_at: string;
  updated_at: string;
  status: PipelineStatus;
  next_stage: string | null;
};

export type JobDetail = JobSummary & {
  state: Json;
};

export type EvidencedFact = { fact: string; evidence_level: "VERIFIED" | "NOT_STATED" | "INFERRED"; source: string };

export type FitRating = "RED" | "YELLOW" | "GREEN";

export type Candidate = {
  candidate_id: string;
  canonical_candidate_id: string;
  name: string;
  current_company: string;
  current_title: string;
  location: string;
  current_ctc: string;
  expected_ctc: string;
  notice_period: string;
  relevant_experience_summary: string;
  achievements: EvidencedFact[];
  metrics: EvidencedFact[];
  concerns: string[];
  recommended_next_action: string;
  source_url: string;
  note: string;
  phone: string;
  email: string;
  conversation_summary: string;
  conversation_summary_updated_at: string | null;
  conversation_summary_entry_count: number;
  prioritization: {
    tier: "A" | "B" | "C" | "D";
    fit_score: number;
    fit_rating: FitRating;
    why_they_fit: string[];
    weaknesses: string[];
    what_is_unknown: string[];
    what_to_validate: string[];
    recruiter_decision: string | null;
    placed: boolean;
    placement_fee: number;
    placed_at: string | null;
  } | null;
};

export type CandidateEvaluationSummary = {
  role_id: string;
  job_title: string;
  candidate_evaluation_id: string;
  tier: "A" | "B" | "C" | "D" | null;
  fit_rating: FitRating | null;
  why_they_fit: string[] | null;
  recruiter_decision: string | null;
  phone: string;
  email: string;
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

export const createJob = (
  title: string,
  role_family = "",
  role_id?: string,
  client_name = "",
  role_value?: number | null,
) => post<JobSummary>("/jobs", { title, role_family, role_id, client_name, role_value: role_value ?? null });

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

// Multi-recruiter assignment — a role's owner_email is kept in sync as
// the "primary" row here by the backend; contributors are purely
// additive. See db_storage.py's _sync_primary_recruiter.
export type RecruiterAssignment = "primary" | "contributor";
export type RoleRecruiter = { email: string; assignment: RecruiterAssignment; added_at: string };

export const getRecruiters = (roleId: string) => get<RoleRecruiter[]>(`/jobs/${roleId}/recruiters`);
export const addRecruiter = (roleId: string, email: string) =>
  post<RoleRecruiter[]>(`/jobs/${roleId}/recruiters`, { email });
export const removeRecruiter = (roleId: string, email: string) =>
  request<RoleRecruiter[]>(`/jobs/${roleId}/recruiters/${encodeURIComponent(email)}`, { method: "DELETE" });

export const setJobClient = (roleId: string, clientName: string | null) =>
  patch<JobSummary>(`/jobs/${roleId}/client`, { client_name: clientName });

export const setJobValue = (roleId: string, roleValue: number | null) =>
  patch<JobSummary>(`/jobs/${roleId}/value`, { role_value: roleValue });

// Revenue intelligence (Batch: 8.33% model) — cumulative Expected/
// Pipeline/Realized across the whole roster. Realized is never a
// re-derivation of role_value — it's the sum of actual placement_fee
// values already tracked per candidate.
export type RevenueOverview = {
  open_roles: number;
  open_roles_priced: number;
  expected_revenue: number;
  pipeline_revenue: number;
  realized_revenue: number;
  margin_percentage: number;
};

export const getRevenueOverview = () => get<RevenueOverview>("/revenue/overview");

// Per-recruiter revenue contribution — every recruiter attributed to a
// role (primary or contributor) is credited in full for that role's
// revenue, not a split; share_of_firm is against the true firm total
// from RevenueOverview, so shares aren't guaranteed to sum to 100% once
// contributors are in use. See db_storage.recruiter_revenue()'s
// docstring for the full rationale.
export type RecruiterRevenue = {
  email: string;
  roles: number;
  expected_revenue: number;
  realized_revenue: number;
  total_revenue: number;
  share_of_firm: number;
};

export const getRevenueByRecruiter = () => get<RecruiterRevenue[]>("/revenue/by-recruiter");

// Client-facing share link (Batch B) — a rotatable token behind
// /public/roles/{token}, the one API surface with no auth requirement.
export const generateShareLink = (roleId: string) => post<JobSummary>(`/jobs/${roleId}/share-link`);
export const revokeShareLink = (roleId: string) =>
  request<JobSummary>(`/jobs/${roleId}/share-link`, { method: "DELETE" });

export type PublicRoleSummary = {
  role_id: string;
  title: string;
  client_name: string | null;
  lifecycle_status: JobLifecycleStatus;
  updated_at: string;
  total_candidates: number;
  counts_by_stage: Record<string, number>;
};

export const getPublicRoleSummary = (shareToken: string) => get<PublicRoleSummary>(`/public/roles/${shareToken}`);

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
// Real model calls take seconds, not minutes — 3 minutes of continuous
// pending/running is a task that will never resolve on its own (a wedged
// worker, a crashed process). Surfacing a real error beats an infinite
// spinner that reads as "nothing happened" if the recruiter looks away
// and comes back.
const TASK_STALE_AFTER_MS = 3 * 60 * 1000;

async function waitForTask<T>(roleId: string, task: Task, onStatus?: (t: Task) => void): Promise<T> {
  let current = task;
  const startedAt = Date.now();
  onStatus?.(current);
  while (current.status === "pending" || current.status === "running") {
    if (Date.now() - startedAt > TASK_STALE_AFTER_MS) {
      throw new ApiError(
        504,
        "This is taking much longer than expected and may be stuck. Refresh and try again — if it keeps happening, the server may need attention.",
      );
    }
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

// Role-level interview questions — generated once from the ICP and
// calibration, varies per role. Distinct from screening questions, which
// validate one specific candidate's own record.
export type InterviewQuestion = { question: string; why_it_matters: string };
export type RoleInterviewQuestions = {
  core_questions: InterviewQuestion[];
  role_specific_questions: InterviewQuestion[];
  red_flag_questions: InterviewQuestion[];
};
// A single call to the LLM is one generation; regenerating appends a new
// one rather than overwriting — see interview_questions.py's docstring.
export type InterviewQuestionGeneration = RoleInterviewQuestions & {
  generated_at: string;
  repeated_questions: string[];
};
export type InterviewQuestionHistory = { generations: InterviewQuestionGeneration[] };

export const runInterviewQuestions = async (roleId: string) =>
  waitForTask<InterviewQuestionHistory>(roleId, await post<Task>(`/jobs/${roleId}/interview-questions`));

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

// Bulk CSV import (Batch B) — one add_candidate task per row, same task
// the paste/upload routes above enqueue, just triggered N times from one
// upload. Each id needs to be polled to completion separately (see
// pollTaskUntilDone) since the server returns the queued ids, not results.
export type BulkImportResult = { task_ids: string[]; queued: number; skipped_empty_rows: number };

export const bulkImportCandidates = async (roleId: string, file: File, roleFamily: string) => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("role_family", roleFamily);
  return postForm<BulkImportResult>(`/jobs/${roleId}/candidates/bulk-import`, formData);
};

export async function pollTaskUntilDone(roleId: string, taskId: string): Promise<Task> {
  let current = await getTask(roleId, taskId);
  while (current.status === "pending" || current.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, TASK_POLL_INTERVAL_MS));
    current = await getTask(roleId, taskId);
  }
  return current;
}

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

// Placement/fee tracking (Batch B) — the one outcome tracked in dollar
// terms. placed=false clears the fee/timestamp too, so an "unplaced"
// record never shows a stale figure.
export type PlacementResult = {
  candidate_id: string;
  placed: boolean;
  placement_fee: number;
  placed_at: string | null;
};

export const setPlacement = (roleId: string, candidateId: string, placed: boolean, fee = 0) =>
  post<PlacementResult>(`/jobs/${roleId}/candidates/${candidateId}/placement`, { placed, fee });

// A recruiter's own private impression, separate from the structured
// decision above and from the model's evidence-labeled output — nothing
// else in the product reads this (Phase 10).
export const setCandidateNote = (roleId: string, candidateId: string, note: string) =>
  patch<{ candidate_id: string; note: string }>(`/jobs/${roleId}/candidates/${candidateId}/note`, { note });

// ── conversation history (email/WhatsApp/call demo) ────────────────────
// This app never sends anything itself — WhatsApp/call "sending" means
// the wa.me/tel: device handoff the UI opens; logging happens the moment
// the recruiter confirms, not on delivery, since there's no messaging/
// telephony backend to confirm delivery with. See api.py's route
// docstring for the honest framing this mirrors.
export type CommunicationChannel = "email" | "whatsapp" | "call" | "note";
export type CommunicationDirection = "outbound" | "inbound";
export type CommunicationLogEntry = {
  id: number;
  channel: CommunicationChannel;
  direction: CommunicationDirection;
  content: string;
  transcript: string | null;
  contact_used: string;
  logged_by: string;
  created_at: string;
};
export type ConversationHistory = {
  entries: CommunicationLogEntry[];
  summary: string;
  updated_at: string | null;
  based_on_entries: number;
};

export const setCandidateContact = (roleId: string, candidateId: string, phone?: string, email?: string) =>
  patch<{ candidate_id: string; phone: string; email: string }>(
    `/jobs/${roleId}/candidates/${candidateId}/contact`, { phone, email },
  );

export const getCommunications = (roleId: string, candidateId: string) =>
  get<ConversationHistory>(`/jobs/${roleId}/candidates/${candidateId}/communications`);

// The summary regeneration is async (an LLM call) — logging itself is
// synchronous and returns immediately with the created entry; the
// caller polls summary_task if it wants to know when the refreshed
// summary is ready, same task-polling pattern as every other AI stage.
export const logCommunication = async (
  roleId: string, candidateId: string,
  body: { channel: CommunicationChannel; direction?: CommunicationDirection; content: string; transcript?: string; contact_used?: string },
) => {
  const resp = await post<{ entry: CommunicationLogEntry; summary_task: Task }>(
    `/jobs/${roleId}/candidates/${candidateId}/communications`, body,
  );
  return resp;
};

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
  total_placements: number;
  total_placement_fees: number;
};

export const getAnalyticsOverview = () => get<AnalyticsOverview>("/analytics/overview");

// ── team usage ───────────────────────────────────────────────────────────
// Every recruiter's activity across the shared workspace — "is everyone
// actually using this," not one recruiter's own view of their own work.
// Visible to any authenticated user; there's no admin/recruiter
// distinction anywhere else in the app either (see api.py's /team/usage).

export type RecruiterUsage = {
  email: string;
  joined_at: string;
  jobs_owned: number;
  candidates_added: number;
  total_actions: number;
  last_active: string | null;
  placements: number;
  placement_fees: number;
  open_jobs: number;
  active_candidates: number;
};
export type TeamUsage = { total_users: number; recruiters: RecruiterUsage[] };

export const getTeamUsage = () => get<TeamUsage>("/team/usage");

// Velocity/conversion (Batch B) — is the effort converting, and where
// does it stall, per role and per recruiter. Distinct from team usage's
// activity counts: this is about outcomes and cycle time, not volume.
export type ConversionCounts = { sourced: number; tiered_a: number; pursued: number; placed: number };
export type VelocityEntry = {
  conversion: ConversionCounts;
  avg_days_in_stage: Record<string, number>;
};
export type RoleVelocity = VelocityEntry & { role_id: string; title: string };
export type RecruiterVelocity = VelocityEntry & { email: string };
export type VelocityReport = { by_role: RoleVelocity[]; by_recruiter: RecruiterVelocity[] };

export const getTeamVelocity = () => get<VelocityReport>("/team/velocity");

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
