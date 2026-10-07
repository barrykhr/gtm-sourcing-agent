# Talyn V2 — Audit of the Existing Product

Snapshot taken at commit `01bb27b` (branch `claude/talent-sourcing-recruiting-516rp9`), working tree clean, 465/465 backend tests green. This document is purely descriptive — no judgment calls about what to build next live here; those are in `TALYN_V2_ARCHITECTURE.md`. Every claim below was verified against the actual code, not recalled from memory or prior docs.

---

## 1. Current architecture

- **Split-host deployment**: FastAPI backend (Python 3.11, SQLAlchemy 2.0, Pydantic v2, Alembic, in-process task queue) on Render; Next.js 16 / React 19 / Tailwind v4 frontend on Vercel. Cross-site session cookie (`SameSite=None; Secure` in production).
- **One monolithic API module** — `src/gtm_sourcing_agent/api.py` defines all 98 REST routes directly on one FastAPI `app`, no sub-routers, no API versioning (`/jobs/...`, not `/v1/jobs/...`).
- **Background jobs**: every LLM-touching call is enqueued to a single in-process `queue.Queue` with one dedicated worker thread (`task_queue.py`). Deliberately single-process — the module docstring is explicit that horizontal scaling would break it (two processes would each have their own in-memory queue and both write-race the same DB). Tasks are polled by the frontend via `GET /jobs/{role_id}/tasks/{task_id}` (job-scoped) or `GET /team/tasks/{task_id}` (roster-scoped, added for the weekly-effort-planning feature).
- **Persistence**: Postgres in production via `DATABASE_URL` (SQLite fallback for local dev). 9 Alembic migrations, run automatically on every process start (`db.py::_run_migrations`) — no manual release-command step.
- **Single shared workspace — NOT multi-tenant.** There is no `organization`/`tenant` concept anywhere in the schema. Every signed-up account (email+password or Google) sees the exact same jobs, candidates, revenue, everything. `User`'s own docstring states this directly: *"this is a locally-run, single-recruiter tool... not a multi-tenant SaaS."* This is the single largest structural gap relative to an "agency workspace" / sell-to-multiple-agencies product.
- **A second, incomplete backend exists**: `backend-node/` is a parallel Node.js/TypeScript port (Fastify, Prisma, Zod) of the entire Python backend. Its own `package.json` description says *"kept alongside the Python backend until validated; not yet the deployed backend."* Last commit touching it predates the last four weeks of feature work on the Python side. It references a `docs/migration.md` that does not exist in the repo. Reads as a paused migration attempt, not active infrastructure.
- **Testing**: 465 backend pytest tests (all green), run by hand each session — **no CI pipeline** (no `.github/workflows` anywhere). **No committed frontend test suite** — every browser verification this project has ever had was an ad hoc Playwright script in a scratch directory, never checked into `frontend/`.

## 2. Current product functionality

**Core pipeline** (one JD → hire, the product's spine):
JD intake (paste, or PDF/DOCX/TXT upload) → hiring-manager calibration → ideal candidate profile (ICP) → talent-market map (Tier 1/2/3 target companies against 4 match dimensions: product/business_segment/customer_base/industry) → search strategy (Naukri + LinkedIn, structured target profiles) → candidate capture (paste, upload, bulk CSV, resume auto-extraction of contact info) → prioritization (A/B/C/D tier + 0-100 fit score + **5-dimension competency scoring** — technical/role-motivation/team/communication/compensation alignment, each with its own rationale) → screening questions → outreach drafting → pipeline/funnel tracking with hire-backwards forecasting.

Every stage is checkpoint-gated: output is written for recruiter review, nothing regenerates silently on stale upstream data.

**Recruiting workspace**: multi-recruiter roles (primary + contributors), role cloning/templates, lifecycle status (OPEN/ON_HOLD/FILLED/CANCELLED), sequential position IDs (`POS-0001`) and client IDs (`CLI-0001`, backed by a real `Client` table), urgency (low/normal/high/critical) + deterministic TAT (turnaround time, days open or days-to-close) + optional client deadline with dashboard prioritization sort, and an AI-generated weekly effort-allocation recommendation ("This week's focus" — given the recruiter's stated available days and their roster's urgency/TAT/deadline/pipeline state, never an automated schedule).

**Candidates**: global cross-job roster + per-role tab, side-by-side comparison, private notes, client-visibility toggle, explicit recruiter decisions (pursue/pass/revisit — never automatic), placement/fee tracking, resume file retention (S3/R2-compatible object storage).

**Communications & interviews**: structured WhatsApp/call logging with a rolling AI-generated conversation summary; in-browser interview audio recording → AssemblyAI transcription → competency-evidence scoring against the role's must-haves → "Ask Talyn" Q&A grounded in the transcript.

**Revenue**: `role_value` (always manually entered, never AI-inferred) × 8.33% margin = expected revenue; firm-wide and per-recruiter revenue dashboards (realized vs. pipeline), each recruiter's share of firm total.

**Team/analytics** (admin-gated — see §7): usage + velocity/conversion reports, cross-job "attention needed" (stalled candidates, upcoming interviews), daily digest email, CSV/JSON export, browser print view, client-facing read-only share links (token-based, no login).

**AI Copilot**: persistent role-scoped side-panel chat — see §5 for its real tool architecture.

**Auth/admin**: email+password + Google Sign-In, forgot-password via SMTP, `admin`/`recruiter` roles actually enforced (8 routes gated on `require_role("admin")`); `client`/`interviewer` exist in the role enum but are **not assignable or enforced anywhere** — pure scaffolding. One-time admin-bootstrap escape hatch for an unreachable admin account. Activity/audit log (who did what, when, per role).

## 3. Current UX architecture

- **Navigation**: a 4-item persistent sidebar (Jobs, Candidates, Team, Guide) + `Cmd+K` command palette + top-bar search + account menu. No client-portal surface exists (nothing for the `client` role to log into).
- **Job workspace**: one route (`/jobs/[role_id]`) with a 9-tab strip — Overview, Hiring Intelligence, Interview Questions, Talent Map, Sourcing, Candidates, Outreach, Pipeline, Analytics — **all rendered from a single ~2,000-line `page.tsx` file**. This is the biggest concrete UX/code-structure debt: every tab's logic, state, and markup live in one file rather than one component per tab.
- **AppShell**: renders an ambient `GradientMesh` SVG backdrop + the persistent Copilot slide-over panel, gated behind `AuthGate`.
- **Motion**: CSS transitions only (120ms ease-in/out on hover/focus states), no animation library. No skeleton loaders — busy states are text/spinner-based, scoped to the control that triggered them (this part already matches the "local busy state, not a global spinner" principle).
- **Responsiveness**: Tailwind responsive classes used throughout, not formally audited against a design spec.

**Current component inventory** (`frontend/components/`): `AppShell`, `Sidebar`, `TopBar`, `AccountMenu`, `AuthGate`, `CommandPalette`, `CopilotPanel`, `CommunicationsCard`, `InterviewsCard`, `IntelligenceCard`, `CompetencyScorePanel`, `WeeklyFocusCard`, `StatusChip`; `components/ui/`: `Button`, `Card`, `ProgressBar`, `AIActivity`, `GradientMesh`, `PreviewFrame`.

## 4. Current design system

- **Tokens** live in one `frontend/app/globals.css` `@theme inline` block: an ink-900/paper-100/signal (`#ff4d1c`) palette (pulled from the talyntlabs.com marketing site's own compiled CSS, not invented), a Geist / Geist Mono / Newsreader typeface trio, a full `signal-50`..`signal-950` Tailwind-style ramp, a hairline-border formula (`color-mix(in oklab, ...)`), a shadow scale, and a radius scale.
- **Dark is the forced default** (flipped from light-default two weeks prior to this audit) — no user-facing light/dark toggle exists.
- **No component library** — every primitive is hand-rolled; no shadcn/ui, no Radix primitives underneath.
- **Evidence vocabulary is 3-state today**: `VERIFIED` / `NOT_STATED` / `INFERRED` (`models/candidate.py::EvidenceLevel`). No `CONFLICTING` state and no numeric confidence score exist anywhere in the schema — flagging explicitly since a V2 redesign brief asks for a 4-state vocabulary (`CONFIRMED`/`INFERRED`/`NOT_STATED`/`CONFLICTING`) plus confidence.

## 5. Existing AI capabilities

- Every pipeline stage calls `llm_client.generate(prompt, output_model, stage=...)` — a real Anthropic `messages.parse()` call enforcing a Pydantic schema via structured outputs. Never fabricated; a missing/invalid API key fails the route cleanly rather than faking output.
- **`orchestrator.py` (the AI Copilot) already implements almost exactly the typed-tool-over-application-services pattern** a from-scratch "agent architecture" would ask for: 11 `@beta_tool`-wrapped functions (`analyze_jd`, `build_hiring_profile`, `build_talent_map`, `create_sourcing_strategy`, `list_candidates`, `get_candidate`, `prioritize_candidate`, `generate_screening_questions`, `generate_outreach`, `get_funnel_report`, `propose_hiring_profile_edit`), each backed by a plain, directly-testable function — the LLM never touches SQL, it only calls these functions. This is the project's own existing answer to "USER → CONVERSATION LAYER → AGENT → TYPED TOOLS → APPLICATION SERVICES → DATABASE."
- **The mutation-safety pattern already exists and is exactly right**: changing a hiring-profile requirement goes through `propose_hiring_profile_edit` (read-only — returns a proposal + its downstream impact) and a *separate* `apply_hiring_profile_edit` (plain deterministic Python) that only runs when the recruiter clicks confirm in `POST /jobs/{role_id}/chat/confirm`. The LLM is never the thing that writes that specific kind of change. This is the "EXECUTE WITH APPROVAL" autonomy rung, already built, for exactly one action type.
- **Copilot is role-scoped only** — `CopilotPanel` takes a `roleId` prop and nothing else; there is no `candidateId` context. Opening the Copilot from a candidate's detail view does not tell it which candidate you're looking at. "If on a candidate, Talyn knows the candidate" is not true today.
- **No per-field confidence or CONFLICTING state** on extracted requirements — `EvidencedFact` carries `fact` + `evidence_level` (3-state) + `source` (free-text string), nothing numeric, nothing resolvable as an "ambiguity" with its own lifecycle.
- **No requirement-level versioning or history.** The ICP is a single flat Pydantic object, regenerated wholesale (`stages/icp.py::run`) or hand-edited in bulk via `PATCH /jobs/{role_id}/icp/criteria` (a full must-have/nice-to-have list replace). There is no `role_versions`-style table recording "Databricks: Preferred → Must-have, by whom, when, why."
- **No structured AI observability.** `llm_client.generate` logs `input_tokens`/`output_tokens` per call via `logger.info` (`llm_client.py:116`) — real numbers, but only as unstructured server log text. Nothing is persisted to a table, nothing is queryable as cost/latency/error-rate from the product itself. Only the confirm/decline outcome of a Copilot proposal is written to `ActivityLog` (`api.py:1863`) — individual tool calls (e.g. `list_candidates`) are not logged anywhere.

## 6. Existing data model

18 tables today (`src/gtm_sourcing_agent/models_orm.py`):

| Table | Purpose |
|---|---|
| `Client` | External client entity, stable sequential ID, found-or-created by name |
| `Job` | A role/mandate — title, lifecycle, owner, urgency, TAT inputs, position/client IDs, role_value |
| `JobRecruiter` | Multi-recruiter attribution (primary/contributor) |
| `JobSection` | Generic per-role keyed JSON blob — how most pipeline-stage output is stored (icp, talent_map, search_strategy, interview_questions, funnel, etc.) |
| `CanonicalCandidate` | Cross-job candidate identity (dedup anchor) |
| `CandidateEvaluation` | One job's evaluation of one candidate — the evidence-labeled record + prioritization |
| `Task` | Background job queue row (nullable `role_id` for non-job-scoped tasks) |
| `User` / `Session` / `PasswordResetToken` | Auth |
| `ActivityLog` | Audit trail (role-scoped, action + detail + optional candidate) |
| `CommunicationLogEntry` | WhatsApp/call log entries |
| `WorkspaceSettings` | Outreach automation config (singleton-ish, not per-tenant) |
| `InterviewSession` / `TranscriptSegment` / `InterviewCompetency` / `InterviewEvidence` / `FollowUpQuestion` | Interview recording → transcript → competency-evidence pipeline |

No `organization`, `role_requirement` (granular, resolvable), `role_version`, `agent_run`, `agent_action`, `conversation`/`conversation_message` (as first-class tables — chat history today lives inside a `JobSection` blob, not normalized), or `candidate_memory` tables exist.

## 7. Existing APIs

98 REST routes on one FastAPI app, roughly: job CRUD + lifecycle/ownership/urgency/client/value (~20), candidates (~15), interviews (~10), outreach/communications (~10), team/revenue/analytics (~10, several `admin`-gated), auth (~8), Copilot chat (2), tasks (4), search/integrations/misc (rest). No OpenAPI tagging/grouping beyond FastAPI's auto-generated default. No route versioning.

## 8. Existing integrations

- **Google Sign-In** — real, working (`google-auth` token verification).
- **AssemblyAI** — real, working (interview transcription), fails cleanly without a key.
- **SMTP** (forgot-password, admin notifications) — real, working when configured; silent no-op otherwise, by design.
- **S3/R2-compatible object storage** — real, working for resume + interview-recording retention.
- **Outbound webhook** (per-role, recruiter-configured) — real, working, includes a test-send action.
- **Google Workspace, Calendly, telephony** — `GET /integrations/status` reports all three as `not_connected` *by design*: env vars exist only to report whether credentials are present, but **no OAuth callback flow exists for any of them**. Today's "Call" button is a `tel:` device handoff, not a connected line.

## 9. Existing technical debt

1. **No multi-tenancy** — see §1. Blocking for any "sell to multiple agencies" direction.
2. **`backend-node/`** — a paused, undocumented parallel backend. Either finish it or delete it; as-is it's a trap for a future contributor.
3. **No CI** — nothing enforces tests passing before merge.
4. **No committed frontend tests** — zero regression protection on the UI layer between sessions.
5. **One 2,000-line `page.tsx`** for the entire job workspace — every tab's state/logic/markup co-located in one file.
6. **One 98-route, unversioned `api.py`** — no sub-router structure.
7. **Stale `README.md`** — still describes the project's original CLI-only phase, doesn't mention the FastAPI/Next.js product at all.
8. **PRD/reality drift**: `docs/TALYN_PRD.md` Principle #5 states "no admin/role tiers, every recruiter sees the same data" — the real app already has 8 admin-gated routes. The PRD needs updating, not the product.
9. **Copilot has no candidate-level context** (§5) and **no cross-role memory** — every conversation starts fresh per role, nothing persists about a candidate across roles.
10. **No token/cost/latency observability table** (§5) despite the raw numbers already being computed.

## 10. Existing functionality worth preserving

Everything in §2 is real, tested, and in active use — none of it is a mockup or fake AI output. The things most worth protecting through a redesign specifically:
- The **evidence-labeling discipline** itself (even if the vocabulary grows from 3 states to 4) — this is the product's actual trust mechanism, not decoration.
- The **checkpoint-gated pipeline** (nothing regenerates silently on stale upstream output).
- The **propose/confirm mutation pattern** in the Copilot — this is exactly the "EXECUTE WITH APPROVAL" rung a V2 agent architecture needs, already proven.
- The **async task-queue pattern** (enqueue → poll → surface failure, never a blocking request or an infinite spinner).
- The **"never AI-infer revenue" rule** (`role_value` always manual) — already a hard product principle, correctly enforced.
- **465 passing backend tests** — the safety net for everything above.

---

## Classification summary

| Area | Classification | Why |
|---|---|---|
| 10-stage pipeline (intake → funnel) | **KEEP** | Real, tested, checkpoint-gated. Redesign the UI around it, don't rebuild the logic. |
| Evidence-labeling model (`EvidenceLevel`) | **REFACTOR** | Sound mechanism, thin vocabulary (3 states, no confidence, no CONFLICTING). Extend, don't replace. |
| AI Copilot / `orchestrator.py` tool architecture | **KEEP, then EXTEND** | Already the typed-tools-not-SQL pattern a V2 agent needs. Add candidate-level context and more tools; don't rebuild the pattern. |
| Hiring-profile propose/confirm mutation pattern | **KEEP** | Exactly right; template this pattern for every future AI-driven mutation. |
| Async task queue (`task_queue.py`) | **KEEP** | Correct pattern, correctly scoped limitation (single-process, documented). Revisit only if scaling past one backend instance. |
| Candidate data model (`CanonicalCandidate` + `CandidateEvaluation`) | **KEEP** | Dedup/cross-job identity already solved correctly. |
| Job workspace tab architecture (one 2,000-line file) | **REBUILD (structurally)** | Logic/data stays; file/component structure needs to split per tab as part of any UX redesign. |
| Design tokens (ink/paper/signal, type trio, shadow/radius scale) | **KEEP** | Premium, considered, already close to the "restraint" brief. Don't discard. |
| Component primitives (`components/ui/`) | **REFACTOR** | Functional but hand-rolled with no shared behavior layer (focus management, variants) — a real component-system pass (shadcn or equivalent) would consolidate these, not replace the visual language. |
| Sidebar/nav (4 items) | **REFACTOR** | Fine today; will need real rework once Clients/Submissions/Analytics-as-destinations exist. |
| Multi-tenancy / organizations | **REBUILD (net-new)** | Doesn't exist at all. Required before any "sell to other agencies" step. |
| `client`/`interviewer` auth roles | **REBUILD (net-new)** | Scaffolded in the enum, zero real access logic behind either. |
| Role requirement granularity (per-field CRUD, versioning, ambiguity resolution) | **REBUILD (net-new)** | ICP is flat and wholesale-regenerated today; Feature 01 needs per-requirement add/update/remove/resolve with history. |
| AI observability (token/cost/latency as data, not log lines) | **REBUILD (net-new)** | Numbers are already computed; nothing persists them. |
| `backend-node/` | **DEPRECATE (decide and act)** | Paused, undocumented, not deployed. Finish or delete — don't leave it ambiguous. |
| Google Workspace / Calendly / telephony integrations | **UNKNOWN (business decision)** | Scaffolded honestly (no fake "connected" state), but whether/which to actually build is a product-priority call, not an audit finding. |
| Client-facing share link (read-only, no login) | **KEEP** | Real, working, exactly the right trust level for today's "no client login" state. |
| CI / committed frontend tests | **REBUILD (net-new)** | Doesn't exist; needed regardless of which product direction wins. |
