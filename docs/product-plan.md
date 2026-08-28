# Product Build Plan

This tracks the 7-phase product build-out proposed in the **Recruiting OS
Blueprint** (published as an artifact; ask if you need the link again) —
turning the CLI-only recruiting pipeline into a persistent, job-centric
product. It's a separate tracking document from
[`implementation-plan.md`](implementation-plan.md), which covers the
*recruiting pipeline itself* (JD → ICP → talent map → ... → funnel) and
already reached its Phase 6. Don't confuse the two "Phase 1"s — this file
is about the product/UI layer built *on top of* that pipeline, which the
pipeline's own plan never touches.

**Ground rule carried over from the Blueprint:** nothing in `prompts/*.md`
or `models/*.py` changes as part of any phase below. This is additive
product work around the existing recruiting intelligence, not a rewrite
of it.

## Phase 1 — Product shell — done, pending live-LLM acceptance

- **Done:** `db.py` + `models_orm.py` — SQLite via SQLAlchemy, two tables
  (`jobs`, `job_sections`). Mirrors `storage.py`'s one-JSON-blob-per-section
  model (row per section instead of file per role) rather than normalizing
  every nested field — that's deliberate scope discipline, see
  `models_orm.py`'s docstring. Candidate/evaluation normalization is
  Phase 2, not this phase.
- **Done:** `db_storage.py` — a drop-in backend implementing the same six
  functions as `storage.py` (`load_role`, `save_role`, `merge_section`,
  `require_section`, `merge_candidate`, `merge_prioritization`), plus
  `create_job` / `list_jobs` / `job_exists` for the product's job-shell
  concept, which the file backend never needed. `storage.py` itself is
  untouched — the CLI still runs on it, zero regression risk.
- **Done:** every `stages/*.py` function (and `pipeline.py`'s
  `status`/`next_stage`) takes an optional `storage_backend=storage` kwarg.
  Every existing call site is unaffected (same default); the API passes
  `db_storage` instead.
- **Done:** `api.py` — FastAPI service, one route per stage, 1:1 with the
  CLI. Verified booting under a real `uvicorn` process (not just
  `TestClient`) before being trusted.
- **Done:** offline test coverage for all of the above — 73 tests total,
  zero network calls, zero API key required (`test_db_storage.py`,
  `test_stage_backend_injection.py`, `test_api.py` are new; the original
  59 are untouched and still pass).
- **Done:** `frontend/` — Next.js 16 + TypeScript + Tailwind SPA. Job
  dashboard (list + create) and a job workspace with Overview, Hiring
  Intelligence, Talent Map, Sourcing, Candidates, Pipeline tabs (Outreach
  and Analytics were added in the Phase 3 correction below), each an
  action button over the matching stage endpoint plus a live view of its
  output. See `frontend/README.md`.
- **Done:** `scripts/mock_llm_server.py` — runs the real API with
  `llm_client.generate` monkeypatched to plausible canned per-stage
  responses, so the whole product (dashboard → intake → hiring profile →
  talent map → sourcing → candidates → prioritize/screen/outreach →
  pipeline) is exercisable in an actual browser without
  `ANTHROPIC_API_KEY`. Used to verify the full golden path end-to-end via
  Playwright before this phase was called done — every tab, every action
  button, screenshotted and confirmed rendering real (fabricated but
  correctly-shaped) data, not just passing offline unit tests.
- **Deferred to later phases, per the Blueprint:** auth beyond a
  single local user, the chat orchestrator, async task queues.
- **Still outstanding:** live acceptance against a real
  `ANTHROPIC_API_KEY` — everything above is verified structurally (tests,
  a real uvicorn boot, a real browser walkthrough against fabricated
  data) but not against genuine model output, same caveat as the
  recruiting pipeline itself in `implementation-plan.md`.

## Phase 2 — Candidate intelligence layer — done

- **Done:** `candidates` (canonical identity) + `candidate_evaluations`
  (per-job — achievements/evidence/tier, since evidence is inherently
  job-context-specific) tables. `db_storage.load_role()` reconstructs the
  exact same `{"candidates": {...}, "prioritizations": {...}}` shape
  Phase 1 returned, so `stages/*.py` and every existing `api.py` route
  needed **zero** changes — only `db_storage.py`'s internals moved.
- **Done:** dedup-on-add, explicit and inspectable (logged, never
  silent) — exact `source_url` match first, normalized name+company as
  fallback, else a new canonical record. No auto-merging of existing
  records after the fact.
- **Done:** `GET /candidates` (global roster) and
  `GET /candidates/{id}` (identity + per-job tier history), additive to
  the existing per-job routes.
- **Done:** a "Candidates" top-level nav item, a roster page, and a
  detail page showing cross-job tier history — the "92% fit Job A, 71%
  fit Job B" view from the build instruction's §9. Verified in a real
  browser against `scripts/mock_llm_server.py`: added the same
  `source_url` to two different jobs, confirmed the roster collapsed
  them to one canonical card reading "2 jobs," and the detail page
  listed both job titles with their tiers.
- Same outstanding caveat as Phase 1: verified structurally + via a real
  browser walkthrough against fabricated data, not live model output.

## Phase 3 — Chat orchestrator — plumbing done, tool-selection quality unverified

This phase has a fundamentally different risk profile from Phases 1–2:
its entire value is natural-language understanding, which cannot be
checked without a live model. What's below is honest about that split.

- **Done:** `orchestrator.py` — a real Claude tool-use loop
  (`client.beta.messages.tool_runner` + `@beta_tool`) over 11 tools
  wrapping the existing stage functions, job-scoped via closure (the
  model never chooses which job — that's fixed context per the
  Blueprint's §J). `_run_tool_loop` is the one function that talks to the
  Anthropic API; every tool's actual logic lives in plain `TOOL_IMPLS`
  functions tested directly, so no test in this repo depends on Anthropic
  SDK response object internals.
- **Done — the confirm-before-mutate pattern (build instruction §14):**
  `propose_hiring_profile_edit` is read-only — it validates and returns a
  proposal, never touches the ICP. `apply_hiring_profile_edit` is plain
  deterministic Python, called only from `POST /jobs/{id}/chat/confirm`
  after explicit recruiter approval — the model is never the thing that
  writes that particular change, only the thing that explains it.
- **Done:** `POST /jobs/{id}/chat`, `POST /jobs/{id}/chat/confirm`,
  `GET /jobs/{id}/chat` — history and pending-proposal persistence.
- **Done, then corrected:** chat first shipped as an "AI Chat" tab
  (Phase 1's placeholder), then was demoted to a persistent side panel —
  see "Phase 3 correction" below. The panel is the same message
  list / input / [Yes — apply] / [No] proposal card, just relocated so
  chat is never the primary interface.
- **Verified structurally and via a real browser walkthrough**, same
  discipline as Phases 1–2 — but the browser pass used a *scripted*
  stand-in for the model (`scripts/mock_llm_server.py`'s
  `_fake_run_chat_turn`: a fixed keyword trigger, explicitly documented
  as not NL understanding), proving the plumbing (message round-trip,
  tool execution, confirm/decline, ICP actually changing) rather than
  chat quality.
- **Genuinely unverified, more so than any earlier phase:** whether real
  natural language like "remove Fabric as a mandatory requirement" or
  "find me 20 more like candidate 17" actually triggers the right tool
  with the right arguments. There is no way to check this without a live
  `ANTHROPIC_API_KEY` — this is not the same caveat as "haven't run it
  yet," it's "cannot be assessed by this environment at all." Treat the
  orchestrator as unvalidated for real recruiter use until it's been run
  against genuine conversations.

### Phase 3 correction — chat demoted from a tab to a side panel

After the "AI Chat" tab shipped, the product direction was corrected:
this is an AI-powered Recruiting OS, not a recruiting chatbot — chat is
how the recruiter *commands* the product, not the product itself. The
job workspace must read as a set of dedicated work surfaces first, with
chat as a secondary, collapsible control layer over them. Concretely:

- **`components/CopilotPanel.tsx`** (new) — the chat UI extracted from
  the old tab into a slide-in overlay (`fixed inset-y-0 right-0`),
  toggled by an "AI Copilot" button in the job-workspace header. It
  renders over whichever tab is open rather than replacing it — the tab
  underneath stays visible and interactive-looking behind the panel.
  Same backend contract as before (`GET/POST /jobs/{id}/chat`,
  `POST /jobs/{id}/chat/confirm`); no API changes were needed for this
  correction, only presentation.
- **Outreach and Analytics promoted from candidate-row/pipeline
  afterthoughts to dedicated tabs.** Outreach lists every candidate with
  a drafted/no-draft status chip, a generate/regenerate action, and an
  expandable view of the drafted sequence (LinkedIn note, InMail, email,
  two follow-ups) — with an explicit banner that sending isn't built
  (no email/LinkedIn integration exists yet; drafts are copy-paste
  only). Analytics shows funnel counts, nine conversion-rate metrics,
  and the leakage insight, labeled "computed from funnel data — not a
  separate AI call" so it doesn't read as a fabricated LLM insight.
- **Candidates** rebuilt as a real table (candidate, role & company,
  tier, pipeline stage, outreach status, actions) with expandable rows,
  instead of a stacked-card list.
- **Pipeline** rebuilt as a horizontally-scrollable column board, one
  column per funnel stage, with per-candidate ‹ back / next › controls.
  Not full drag-and-drop — deliberately deferred, see below.
- A `dataVersion` counter, bumped whenever the Copilot panel completes a
  turn or a confirm, is threaded into `CandidatesTab` and `PipelineTab`
  so a copilot-driven change (e.g. "remove X as a must-have") is visibly
  reflected in the relevant tab without a manual refresh — this is what
  makes the copilot feel like it's acting *on* the product rather than
  just chatting about it.
- Verified via a 9-step Playwright walkthrough against
  `scripts/mock_llm_server.py` covering: no "AI Chat" tab exists; the
  Copilot opens as an overlay without hiding the current tab's content;
  and a copilot propose/confirm round-trip visibly updates the Hiring
  Intelligence tab's "Must have" list. Same fabricated-data caveat as
  the rest of this phase.
- **Still deferred, unchanged by this correction:** real search
  execution, async progress indicators, drag-and-drop pipeline reorder,
  dashboard-level aggregation across jobs, and the live-`ANTHROPIC_API_KEY`
  acceptance pass noted above.

## Phase 4 — Async + scale — done

Every LLM-touching route in api.py used to call the model synchronously
inside the request handler — fine against the mock (instant canned
responses) but a real problem against a live model: a slow call (real
Anthropic latency can run into the tens of seconds) ties up an HTTP
request and a server thread for its whole duration, and there was no way
to fire off several long-running actions without serializing them one
blocking call at a time.

- **Done:** a `tasks` table (`models_orm.py`) — id, role_id, kind,
  status (`pending`/`running`/`succeeded`/`failed`), args, result,
  error, timestamps. `db_storage.py` gained matching
  `create_task`/`get_task`/`list_tasks`/`update_task` CRUD, same
  pattern as every other table in this file.
- **Done:** `task_queue.py` — a single dedicated background worker
  thread pulling task ids off an in-process `queue.Queue`, one at a
  time. Deliberately not a pool and not an external broker
  (Celery/Redis): concurrent writer threads against the SQLite file
  caused real "database is locked" / "readonly database" failures
  during earlier phases' manual testing (see the Phase 3 correction's
  error notes), and a single sequential worker sidesteps that
  entirely — no WAL-mode tuning, no infra this product doesn't need
  yet at this scale. If volume ever outgrows one worker, the queue can
  be swapped for a real broker without api.py's routes changing, same
  "swap what's below, not what's above" pattern `db_storage.py`
  established in Phase 1.
- **Done:** every LLM-touching POST route (intake, calibrate, icp,
  talent-map, search-strategy, add-candidate, prioritize, screen,
  outreach) now enqueues a task and returns `202` + `task_id`
  immediately instead of blocking on the model call. New
  `GET /jobs/{role_id}/tasks/{task_id}` and `GET /jobs/{role_id}/tasks`
  for polling. Deterministic routes (funnel update/report/forecast)
  were left synchronous on purpose — there's nothing to gain by
  queueing work that never calls the model. The chat orchestrator
  (Phase 3) was also left as-is: a chat turn is inherently a
  request-and-wait exchange from the recruiter's point of view, not a
  fire-and-forget action.
- **Done:** `frontend/lib/api.ts` — each stage function (`runIcp`,
  `addCandidate`, `prioritizeCandidate`, etc.) now enqueues, then polls
  `GET .../tasks/{id}` every 250ms until the task is done, resolving
  with the real result or throwing the real error. This keeps every
  call site in `page.tsx` byte-for-byte unchanged (`await
  runIcp(job.role_id)` still just works) — what changed is underneath:
  a slow real model call no longer holds a request open, it's a
  handful of short polls instead. No fake progress bar was added; the
  existing busy-button state already reflected genuine in-flight work
  and still does.
- **Verified:** the full backend suite (107 tests, up from 105 —
  `test_prioritize_screen_outreach_are_async_tasks`,
  `test_task_404_when_missing_or_wrong_job`, and the existing
  intake/calibrate/candidate tests rewritten to poll a real task to
  completion instead of asserting on a synchronous response body).
  Also verified live in a browser two ways against
  `scripts/mock_llm_server.py` (unmodified — the monkeypatch on
  `llm_client.generate` is a module-level attribute, so the worker
  thread picks it up the same as the request thread always did): the
  full existing 9-step correction walkthrough re-run end-to-end with
  zero UI changes needed, plus a dedicated check confirming the POST
  responses are genuinely `202`, `GET .../tasks` returns real
  per-task records, and a wrong-job task lookup 404s rather than
  leaking across jobs.
- **Not built, and deliberately out of scope for this phase:** a bulk
  action (e.g. "generate outreach for every shortlisted candidate")
  that fires many tasks at once with real per-item status. The queue
  and polling infrastructure above would support it directly, but
  nothing here materialized it into a UI action — left for whenever a
  concrete bulk workflow is asked for, rather than built speculatively.
- Same outstanding caveat as every earlier phase: verified structurally
  and via a real browser walkthrough against fabricated mock data, not
  a live model — real latency, real timeouts, and real concurrent
  request volume are still unverified.

## Phase 5 — Outreach + pipeline execution — done

Before this phase, Outreach and Pipeline were disconnected from each
other and, in Pipeline's case, from data that already existed: every
funnel stage move has always been recorded with a timestamp
(`FunnelRecord.stage_history`), but nothing surfaced it — the board only
ever showed a candidate's *current* stage. And a drafted outreach
sequence had no way to become a real recruiter action; drafting and
"having reached out" were the same state.

The scope here was picked to respect the standing invariant that
nothing in this repo sends outreach (Architecture §1.4, §7) — "outreach
execution" does not mean adding real send integration. It means giving
the recruiter's own actions somewhere to go:

- **Done — "Mark as sent"** (`stages/outreach.py::mark_sent`,
  `POST /jobs/{role_id}/candidates/{candidate_id}/outreach/mark-sent`):
  records that the recruiter reached out through some channel outside
  this product (their own LinkedIn, their own email client — nothing
  here transmits anything). Requires a draft to already exist. If the
  candidate hasn't reached CONTACTED yet, deterministically advances
  them there with a `"outreach marked sent"` note on the transition —
  a direct consequence of the recruiter's own click, the same category
  of action as manually dragging a pipeline card, never further than
  CONTACTED and never backward. Deterministic bookkeeping, not a model
  call, so — like the funnel routes — it's synchronous, not
  task-queued.
- **Done — stage notes**: `StageTransition` gained an optional `note`
  field; the funnel update route and the Pipeline board's next/back
  controls now accept one (e.g. "HM loved the resume," "SMB-only
  background, passing for now"). Purely recruiter-authored — nothing
  here generates a note.
- **Done — the Pipeline board surfaces its own history**: each
  candidate card now shows "Xd in stage" (computed from the last
  transition's timestamp) and, on click, the full stage-history
  timeline with timestamps and notes. All of this data already existed
  in `job.state.funnel` from Phase 1 onward; Phase 5 is entirely UI —
  no new storage was needed for it.
- **Done — Outreach ↔ Pipeline are now visibly connected**: the
  Outreach tab's status chip is now a real three-state progression (No
  draft → Drafted → Sent, gray → amber → green) instead of a binary
  drafted/not, and marking sent immediately shows up as a stage move on
  the Pipeline board — verified live, not just asserted from the
  API layer.
- **Verified:** backend suite at 113 tests (up from 107 — new
  `stages/outreach.py::mark_sent` tests covering "no draft yet" (400,
  not 500), the CONTACTED auto-advance, and that an already-further-
  along candidate is never pulled backward; a `note`-on-transition
  test; an API-level test for the new route). Live in a browser against
  `scripts/mock_llm_server.py`: the full existing 9-step correction
  walkthrough re-run with zero regressions, plus a dedicated 5-step
  walkthrough — generate a draft, mark it sent, confirm the pipeline
  card lands on CONTACTED with an "outreach marked sent" history entry,
  then move it forward with a custom note and confirm that note is the
  one that shows up in the timeline.
- **Not built, deliberately out of scope:** drag-and-drop pipeline
  reordering (still just next/back — unchanged since the Phase 3
  correction that first noted this deferral); a dedicated "needs
  follow-up" / stalled-candidates view (the per-card "Xd in stage"
  signal covers the same need at a glance without a separate panel);
  per-channel sent-tracking (LinkedIn vs. email vs. InMail) — a single
  sent timestamp per candidate was judged sufficient for this phase.
- Same outstanding caveat as every earlier phase: verified structurally
  and via a real browser walkthrough against fabricated mock data, not
  live model output.

## Phase 6 — Analytics + recruiter memory — done

Scope here started from a concrete, pre-existing gap rather than a
blank slate: `CandidatePrioritization.recruiter_decision` has existed
since Phase 1 (the model docstring, `prioritization.py`'s explicit
`result.recruiter_decision = None  # only the recruiter sets this`, and
even the candidate-detail page's `{e.recruiter_decision && ...}`
rendering all reference it) — but no route and no UI control anywhere
ever set it. It was fully wired to display a value that could never
exist. "Recruiter memory" is what filling that in turns out to mean:
giving the recruiter's own past judgment on a candidate somewhere to
live, and surfacing it back to them.

- **Done — the write path itself**
  (`stages/prioritization.py::set_recruiter_decision`,
  `POST /jobs/{role_id}/candidates/{candidate_id}/decision`):
  deterministic, not a model call — same category as `outreach.mark_sent`
  and `funnel.update`. Requires the candidate to already be prioritized
  (there's no decision to attach to a tier that doesn't exist yet).
  Read-modify-write on the existing prioritization record, so it never
  touches tier/why-they-fit/evidence. Passing an empty string clears a
  previously recorded decision.
- **Done — the UI**: the Candidates tab's expanded row gets a
  "Recruiter decision" card with three quick-pick buttons (Pursue / Pass
  for now / Revisit later — the same examples the model's own docstring
  uses) plus a free-text override and a Clear action. Free text, not a
  hard enum — matching what the field was already documented to accept.
- **Done — cross-job memory, surfaced inline**: Phase 2's canonical-
  candidate dedup and cross-job evaluation summary
  (`GET /candidates/{id}`) already contained everything needed for
  this — no new backend work, only a new frontend consumer. When a
  candidate's row is expanded, the tab fetches their canonical profile
  and, if they've been evaluated on another job, shows a "Seen before"
  card: which job, their tier there, and — now that it can actually be
  set — the decision recorded on them. Verified live: the same person
  (matched by identical `source_url`, same dedup heuristic as Phase 2)
  added to a second job immediately surfaces "Tier A ·
  'pass for now'" from the first.
- **Done — cross-job analytics** (`db_storage.analytics_overview`,
  `GET /analytics/overview`): deterministic counting across every job
  — total jobs, canonical candidates, evaluations, a tier distribution,
  and decisions-recorded vs. still-pending — the same discipline
  `funnel.report()` uses for a single job's conversion math, just
  aggregated across all of them. Surfaced as a compact stat strip on
  the Jobs dashboard (hidden until there's at least one job, so an
  empty account isn't greeted with a wall of zeros). Distinct from the
  per-job Analytics tab, which is one role's funnel conversion — this
  is the dashboard-level aggregation explicitly called out as deferred
  back in the Phase 3 correction.
- **Verified:** backend suite at 120 tests (up from 113 — new
  `set_recruiter_decision` tests covering the "not prioritized yet"
  error, that it doesn't disturb the rest of the record, and that it
  can be cleared; `analytics_overview` tests for both a populated and
  an empty account; API-level tests for both new routes). Live in a
  browser against `scripts/mock_llm_server.py`: the full existing
  9-step correction walkthrough re-run with zero regressions, plus a
  dedicated 4-step walkthrough — record a decision via quick-pick,
  confirm it persists and highlights the selected option, add the same
  candidate (same `source_url`) to a second job and confirm "Seen
  before" surfaces the first job's tier and decision, then confirm the
  dashboard's stat strip matches (2 jobs, 1 candidate, 2 evaluations,
  1/1 decisions recorded).
- **Not built, deliberately out of scope:** decision analytics beyond
  counting (e.g. time-from-decision-to-hire); any attempt to have the
  model suggest a recruiter_decision — that field stays recruiter-only
  by design, unchanged from Phase 1's invariant.
- Same outstanding caveat as every earlier phase: verified structurally
  and via a real browser walkthrough against fabricated mock data, not
  live model output — though this phase's core value (the write path,
  the cross-job surfacing, the aggregation) is itself model-independent
  deterministic bookkeeping, so it's less exposed to that caveat than
  most phases before it.

## Phase 7 — Auth — done

Scoped deliberately small: this is a locally-run, single-recruiter tool
with no real domain or hosting, not a multi-tenant SaaS — so "auth
hardening" means session-based email+password auth with exactly one
account, not OAuth/SSO or a user-management system nothing here needs
yet. Every route this product exposes was reachable by anyone who could
reach the port before this phase; now it isn't.

- **Done:** `users` + `sessions` tables (`models_orm.py`) and a new
  `auth.py` module — `account_exists`, `create_user` (refuses a second
  account), `verify_credentials`, `create_session`,
  `get_user_from_session`, `delete_session`. Passwords are salted
  PBKDF2-HMAC-SHA256 (stdlib `hashlib`, 600k iterations, no new
  dependency) — a deliberately conservative choice: correct hashing
  beats no hashing, and swapping in bcrypt/argon2 later touches nothing
  above this module, same "swap what's below" pattern `db_storage.py`
  established in Phase 1.
- **Done:** `AuthMiddleware` in `api.py` — every route requires a valid
  session cookie except `/health`, `/auth/signup`, `/auth/login`,
  `/auth/status`. Enforced once via middleware rather than a per-route
  dependency, so a new route can never be accidentally left unguarded.
  New `POST /auth/signup` (200 once, 400 on every attempt after — there
  is only ever one account), `/auth/login`, `/auth/logout`,
  `GET /auth/me`, `GET /auth/status`. Session token lives in an
  HTTP-only, `SameSite=Lax` cookie; `secure` is off by default for local
  HTTP dev and flips on via `GTM_COOKIE_SECURE=true` for a real HTTPS
  deployment. CORS now sets `allow_credentials=True` so the cookie
  actually flows cross-origin between the Next.js dev server and the API.
- **Done — frontend:** a `/login` page that shows a signup form on first
  run and a login form ever after (driven by `GET /auth/status`); an
  `AuthProvider`/`useAuth()` context shared by an `AuthGate` (redirects
  to `/login` on a 401, shown nowhere else) and an `AccountMenu` in the
  header (logged-in email + log out). Every `fetch` now sends
  `credentials: "include"`.
- **Verified:** backend suite at 130 tests (up from 120 — new
  `test_auth.py` covering signup/login/logout, the second-account
  refusal, wrong-password and unknown-email rejection, and that a
  protected route 401s with no session). The two existing TestClient
  fixtures (`test_api.py`, `test_chat_api.py`) now sign up and log in as
  part of their one shared `isolated_db` fixture, so none of the ~50
  existing test functions across both files needed to change when auth
  was added. Live in a browser: unauthenticated `/` redirects to
  `/login`; sign up lands on the dashboard with the account email in the
  header; a page reload keeps the session (the cookie, not client
  state); log out returns to `/login`; log back in works. Then the full
  existing 9-step correction walkthrough and the Phase 4/5 verification
  walkthroughs were all re-run end-to-end against the now-authenticated
  app with zero regressions.
- **Not built, deliberately out of scope:** multi-user accounts, roles/
  permissions, password reset (single local account — if you forget it,
  reset the SQLite file), OAuth/SSO. All real gaps for a multi-recruiter
  or hosted version of this product, not for what it is today.
- Same outstanding caveat as every earlier phase for the rest of the
  product (mock LLM data, not live model output) — but this phase's own
  correctness (hashing, session validation, the middleware allowlist) is
  independent of that caveat, verified directly.

## Phase 8 — In-product training + next-layer recruiter workflow — done

Two rounds of work once the core 7-phase pipeline stood on its own: first
an in-product Guide so a new recruiter doesn't need this doc to learn the
tool, then six workflow layers recruiters using the product day-to-day
would actually miss — the kind of gap that only shows up once you're
running real pipelines, not building the first version of the pipeline.

- **Done — in-product Guide (`/guide`):** a step-by-step walkthrough of
  every stage (intake through outreach and pipeline), each with what it
  does, how to use it, and a real screenshot captured live from the
  running app (not mocked mockups) via a Playwright screenshot pass. A
  genuine screen-recorded `.webm` walkthrough (`record_video.py`, using
  Playwright's `record_video_dir`, not a synthetic slideshow) is embedded
  on the page — a real recording of a real session against the mock LLM
  server, end to end.
- **Done — bulk actions:** "Prioritize all" / "Draft outreach for all" on
  the Candidates and Outreach tabs, appearing only when there's unscored/
  undrafted work. Frontend-only — `Promise.allSettled` over the existing
  per-candidate task-queue endpoints, so no new backend route or
  concurrency model; a partial-failure count surfaces if any individual
  candidate call fails rather than the whole batch aborting silently.
- **Done — interview scheduling:** `StageTransition` gained an optional
  `scheduled_at`, set by the recruiter (never inferred) alongside a stage
  move — distinct from `at`, which is when the move itself happened, and
  not sticky across moves (each transition carries its own schedule or
  none). Pipeline cards show a "Scheduled: …" badge; history entries show
  which past move had a schedule attached.
- **Done — cross-job "Attention needed":** `db_storage.attention_needed()`
  scans every job's funnel deterministically (no new table — reuses
  `load_role()`) for two things: candidates sitting `>= 3` days in an
  awaiting-response stage (`CONTACTED` through `FINAL_INTERVIEW`) with no
  next move recorded, and any upcoming scheduled interview. Surfaced as a
  two-column section on the dashboard, each item a direct link into the
  job it belongs to.
- **Done — exportable reports:** `GET /jobs/{role_id}/candidates/export.csv`
  (stdlib `csv`/`io`, no new dependency) for a spreadsheet-ready candidate
  list, and a print-friendly `/jobs/{role_id}/print` page (hiring profile,
  candidate table, funnel counts) using the browser's own
  `window.print()` → Save as PDF rather than a server-side PDF library —
  deliberately no new dependency for something every browser already does
  well.
- **Done — multi-recruiter accounts:** Phase 7's "exactly one account"
  constraint is gone. `auth.create_user` now checks per-email uniqueness
  instead of "does any account exist", and an optional `GTM_SIGNUP_CODE`
  env var gates signup with an invite code when set (open signup by
  default, matching local/dev use). This is still **not** multi-tenant —
  every account shares the same one workspace, sees the same jobs and
  candidates; it's multiple people logging into one shared recruiting
  desk, not data isolation between them. The `/login` page now shows an
  explicit Log in / Create account toggle instead of silently switching
  modes based on whether an account already exists.
- **Done — resume/file upload:** `POST /jobs/{role_id}/candidates/upload`
  accepts a PDF/DOCX/TXT file, extracts plain text
  (`resume_extraction.py` — `pypdf`/`python-docx`/stdlib `.decode()`,
  extraction only, no field parsing here), and feeds it into the exact
  same async add-candidate task path a pasted-text submission already
  uses — candidate_analysis.py, the model call, and the resulting
  candidate record are all unchanged. The "Add candidate" form on the
  Candidates tab now has a Paste text / Upload file toggle.
- **Verified:** backend suite at 144 tests (up from 130 — new
  `test_resume_extraction.py`, rewritten `test_auth.py` for multi-account
  semantics, plus new coverage for scheduling, attention-needed, CSV
  export, and upload). Frontend typecheck/lint/build all clean. Live in a
  browser end to end: signed up a fresh account, created a job, uploaded
  a `.txt` resume through the file-upload form and watched it turn into a
  candidate row, added a second candidate by paste, ran "Prioritize all",
  confirmed the CSV export link and the print report page both render,
  expanded a pipeline card, set a scheduled interview time and moved the
  candidate a stage, then confirmed that scheduled interview appeared on
  the dashboard's "Upcoming interviews" section.
- **Not built, deliberately out of scope:** per-user data isolation
  (still one shared workspace — see above), resume parsing beyond text
  extraction (structured field extraction is still the model's job, not
  this module's), calendar-system integration for scheduling (the
  `scheduled_at` field is a recruiter-entered date the product displays,
  not a synced calendar event), PDF generation beyond the browser's own
  print-to-PDF.
- Same outstanding caveat as every earlier phase: everything above was
  verified against the mock LLM server (`scripts/mock_llm_server.py`),
  not live model output — the pipeline logic and every deterministic code
  path (extraction, scheduling, CSV/print rendering, auth, attention
  scanning) are fully exercised regardless, but candidate quality and
  outreach copy quality themselves are still unverified against the real
  model.

## Phase 9 — World-class layer: templates, tuning, audit, comparison, digest, integrations — done

Seven more features, chosen from a "what's still missing for a recruiter
running this daily" pass after Phase 8 shipped, each scoped to fit this
product's existing invariants rather than bolted on:

- **Done — outreach → email handoff:** an "Open in email" link next to
  each outreach draft, building a `mailto:` URI (subject + the drafted
  body pre-filled) via the browser, not a server-side send. Candidates
  don't have a captured email address — this product never scrapes or
  fabricates contact info (Architecture §7) — so the recipient is left
  for the recruiter to fill in themselves; still real value, since the
  copy arrives pre-filled in their own client.
- **Done — role templates:** `db_storage.clone_role()` copies a job's
  hiring strategy (JD, calibration, ICP, talent map/search strategy)
  into a freshly created job; `POST /jobs/{role_id}/clone`. Deliberately
  never copies candidates, pipeline, or outreach state — a template is
  "how to hire for this kind of role again," not "this specific search,
  replayed." A "Clone as new role" button sits in the job header.
- **Done — rubric tuning:** `icp.update_criteria()` lets the recruiter
  directly add/remove ICP must-have/nice-to-have items — deterministic,
  no model call, same category as `set_recruiter_decision` — distinct
  from the AI Copilot's propose/apply flow (that's for AI-*suggested*
  edits; this is the recruiter's own hand on their own criteria, so it
  skips confirmation). `PATCH /jobs/{role_id}/icp/criteria`. The Hiring
  Intelligence tab's Must-have/Nice-to-have cards became inline editable
  lists with add/remove and a Save button.
- **Done — activity/audit log:** a new `activity_log` table
  (`models_orm.ActivityLog`) plus `db_storage.log_activity`/
  `list_activity`. Written from `api.py`'s route handlers — the one
  layer that has the authenticated user via `request.state.user` — right
  after each mutation (job creation, cloning, stage moves, decisions,
  outreach sent, criteria edits, webhook config/test, chat-proposal
  apply/decline), never from `stages/*.py`. Best-effort by design: a
  logging failure is caught and never breaks the real action it's
  attached to. `GET /jobs/{role_id}/activity`; rendered as a "Recent
  activity" feed on the Overview tab.
- **Done — candidate comparison:** checkboxes on the Candidates table
  feed a "Compare selected" view — a table of tier/why-they-fit/
  what's-unknown/to-validate/decision/concerns for 2+ candidates side by
  side. Entirely frontend, reusing `listCandidates`'s existing response;
  no new backend route.
- **Done — daily digest email handoff:** an "Email digest" `mailto:`
  link on the dashboard, built entirely from data the dashboard already
  fetches (`getAnalyticsOverview` + `getAttentionNeeded`) — no new
  backend endpoint. Same pattern as the outreach handoff: a real
  pre-filled draft summarizing job/candidate counts and every
  needs-follow-up/upcoming-interview item, recipient left for the
  recruiter.
- **Done — JSON export + outbound webhook:**
  `GET /jobs/{role_id}/candidates/export.json` for structured,
  ATS-shaped output (the CSV export's sibling). A new `webhooks.py`
  module (`httpx`, 5s timeout) sends a real HTTP POST to a URL the
  recruiter configures for their own job — same pattern as a Slack
  incoming webhook, never a fabricated "delivered" state:
  `send_webhook()` never raises, every outcome (success, non-2xx,
  connection failure) comes back as a `{ok, detail}` result the caller
  logs to the activity feed. Fires automatically on a "pursue" decision
  (`_maybe_fire_decision_webhook` in `api.py`); a "Send test payload"
  button on the Analytics tab's new Integrations card fires it on
  demand. Delivery is always best-effort — a bad or unreachable URL
  never blocks the decision-setting call it rides along with.
- **Verified:** backend suite at 170 tests (up from 144 — new
  `test_icp.py`, `test_webhooks.py` — mocked at `send_webhook_request`,
  the one real network call, same pattern as mocking `llm_client.generate`
  — plus new `db_storage`/`api` coverage for clone, criteria edit,
  activity log, JSON export, and the decision→webhook trigger). Frontend
  typecheck/lint/build all clean — lint caught a real bug during this
  work: the Integrations card's mount-time webhook-URL fetch could
  resolve after the recruiter started typing and silently stomp their
  edit back to the old value; fixed with an `editedRef` guard rather
  than suppressing the lint rule. Live in a browser end to end: edited
  and saved ICP criteria, watched them appear in the Overview activity
  feed, cloned the job and confirmed the edited criteria carried over
  while candidates didn't, added and compared two candidates side by
  side, confirmed both export links, opened an outreach draft's mailto
  link, configured a webhook and sent a real test payload (a genuine
  network attempt — this sandbox's egress policy returned a 403, which
  surfaced correctly as "could not reach webhook URL" rather than a fake
  success), set a "pursue" decision and confirmed both the decision and
  the resulting webhook delivery attempt landed in the activity log, and
  confirmed the dashboard's digest link appears (with a correctly
  populated mailto body) once there's an actual attention item.
- **Not built, deliberately out of scope:** automatic delivery of the
  daily digest (it's a one-click mailto handoff, not a scheduled send —
  this product has no outbound email/SMTP capability and won't fake
  one); webhook retries/backoff (a single best-effort attempt, visible
  in the activity log either way); numeric rubric *weights* feeding the
  scoring prompt (tuning here means editing the criteria text itself,
  not a weighted formula — the model still makes the tier judgment from
  the criteria as given).
- Same outstanding caveat as every earlier phase: verified against the
  mock LLM server, not live model output. The webhook module is the one
  exception worth calling out explicitly — its network behavior was
  verified against a real (if sandbox-blocked) HTTP request, not mocked
  at the HTTP layer, so that particular piece's correctness doesn't
  depend on the mock-LLM caveat at all.

## Phase 10 — Workspace at scale: job lifecycle, search, notes, ownership — done

The gaps that only show up once a workspace has dozens of jobs and more
than one recruiter in it: a job needs to be closeable, a growing roster
needs to be searchable, a recruiter needs somewhere to jot a private
impression that isn't the model's evidence and isn't the structured
decision, and "whose req is this" needs an answer.

- **Done — job lifecycle status:** `Job.lifecycle_status`
  (`models_orm.py`) — one of `OPEN`/`ON_HOLD`/`FILLED`/`CANCELLED`,
  defaulting to `OPEN`, validated in `db_storage.set_job_lifecycle()`
  against `JOB_LIFECYCLE_STATUSES`. Deterministic, recruiter-authored,
  never set by a stage or the model — same category as
  `set_recruiter_decision`, but for the job as a whole.
  `PATCH /jobs/{role_id}/lifecycle`. Named `lifecycle_status`, not
  `status`, so it's never confused with `pipeline.status()`'s per-stage
  dict or `Task.status`'s pending/running/succeeded/failed. A select on
  the job page changes it; the dashboard hides `FILLED`/`CANCELLED` jobs
  by default behind a "Show closed jobs" toggle.
- **Done — job ownership / "My jobs":** `Job.owner_email`, defaulted to
  whoever created the job (`request.state.user["email"]`) but
  reassignable via `PATCH /jobs/{role_id}/owner`. A clone inherits the
  *cloning* recruiter as owner, not the source job's owner — cloning is
  its own new claim on the work. The dashboard's "My jobs" toggle filters
  to `owner_email === <current user>`; job cards show the owner's email
  when it isn't the viewer.
- **Done — private candidate notes:** a `note` column on
  `CandidateEvaluation`, deliberately its own column rather than a key
  inside `data` — `data` is the model's evidence-labeled output
  (Architecture §1.2) and a recruiter's private impression ("seemed
  distracted on the call") is neither evidence nor something the model
  produced. `PATCH /jobs/{role_id}/candidates/{candidate_id}/note`.
  Nothing reads this back — no stage, no export, no prompt — it's purely
  a place for the recruiter to jot something down for themselves.
- **Done — global search:** `GET /search?q=` — `db_storage.search()` does
  a plain SQLite `LIKE` over `Job.title`/`Job.role_id` and
  `CanonicalCandidate.name`, capped at 10 results each. No full-text
  index — deliberately dependency-free, plenty fast at this scale. A
  debounced search box in the header (visible only once logged in) shows
  a dropdown of matching jobs and candidates; clicking either navigates
  straight there.
- **Verified:** backend suite at 197 tests (up from 170 — new coverage
  for lifecycle transitions and validation, owner defaulting/
  reassignment/clearing, note persistence and its separation from `data`,
  and search matching/case-insensitivity/empty-query behavior). Frontend
  typecheck/lint/build all clean — lint caught a second real bug this
  round: the search box's debounce effect was calling `setState`
  synchronously in the effect body for the empty-query case; fixed by
  recognizing the state didn't need clearing at all (the dropdown is
  already gated on a non-empty query, so a stale result is never shown)
  rather than adding a guard. Live in a browser end to end: created a job
  and confirmed it defaulted to `OPEN`/owned-by-me, changed its status to
  `ON_HOLD` then `FILLED`, confirmed the dashboard hid it by default and
  the "Show closed jobs" toggle revealed it again, reassigned its owner
  and confirmed "My jobs" correctly excluded it afterward, added a
  candidate and saved a private note on them, then searched for both that
  candidate and the job by partial name and got both back in the
  dropdown.
- **Not built, deliberately out of scope:** full-text/fuzzy search
  (substring `LIKE` is enough at this scale — revisit if the roster grows
  into the thousands), a lifecycle audit trail beyond the existing
  activity log entry, per-owner permissions (ownership here is a label
  for filtering and accountability, not an access-control boundary — see
  auth.py's module docstring on why this product still isn't
  multi-tenant).
- Same outstanding caveat as every earlier phase: verified against the
  mock LLM server, not live model output — none of this phase's work
  touches the model at all, so that caveat doesn't really apply to it
  either.

## Phase 11 — Design pass: enterprise SaaS visual system — done

Not a new feature — a visual overhaul of the frontend chrome, done after
nine phases of feature work had left the UI functional but visually flat
(plain borders, no elevation, and — a real bug found in the process — the
Geist font import was never actually wired to `body`, so the whole app
had quietly been rendering in plain Arial the entire time). Direction:
Stripe Dashboard × Linear.

- **Done — typography:** Inter, properly wired this time
  (`app/layout.tsx` → `--font-inter` → `globals.css`'s `@theme inline`
  → `body`'s `font-family`), replacing the dead Geist Sans import.
- **Done — design tokens:** `globals.css` gained CSS custom properties
  for background/surface/foreground/border/accent and a 3-step shadow
  scale (`--shadow-sm/md/lg`), each redefined under
  `prefers-color-scheme: dark`, plus a global focus-visible treatment
  (an offset ring for buttons/links, a softer glow for text inputs so it
  doesn't fight their existing `focus:border-*` styling).
- **Done — sidebar navigation:** a persistent left sidebar
  (`components/Sidebar.tsx`) replaced the top-bar-only nav — the
  structural pattern Linear/Vercel/Retool/Notion converged on. Account
  menu moved to the sidebar footer (now an avatar chip + email + a
  logout icon button, `components/AccountMenu.tsx`); `NavLinks.tsx` is
  gone, folded into the sidebar. `components/AppShell.tsx` decides the
  chrome: `/login` gets a bare centered canvas, everything else gets the
  full sidebar shell.
- **Done — command palette:** `components/CommandPalette.tsx` replaced
  the Phase 10 header search box with a ⌘K/Ctrl+K-triggered modal
  overlay — same `search()` API underneath, different container. A
  visible "Search…　⌘K" trigger button lives at the top of the sidebar
  for anyone who doesn't know the shortcut yet.
- **Done — accent color + elevation:** every `teal-*` Tailwind class
  (100 occurrences across 8 files) became `indigo-*` — a plain,
  mechanical shade-preserving swap (same numeric suffixes, so every
  existing light/dark pairing kept working unchanged), verified by a
  full rebuild afterward. The shared `Card` component and every other
  bordered white surface (`bg-white` + `dark:bg-zinc-900`, 7 occurrences)
  now use the `bg-surface` token plus a subtle `shadow-sm`, giving cards
  real depth instead of a flat border. The login page became an actual
  centered auth card with a brand mark, instead of bare form fields
  floating on the page background.
- **Fixed — print report regression:** the sidebar restructure removed
  the `<header>` element the print page's `@media print` rule used to
  hide (`header, .no-print { display: none !important; }`) — caught by
  screenshotting the print page under emulated print media before
  calling this phase done, not by assumption. Fixed by adding `aside` to
  that selector.
- **New dependency:** `lucide-react` — small, tree-shakeable icon set,
  used for sidebar nav icons, the search/briefcase/user icons in the
  command palette, and the logout icon.
- **Verified:** backend suite still at 197 tests (nothing here touches
  the backend). Frontend typecheck/lint/build all clean — lint caught
  two more real `setState`-in-effect issues during this pass (the
  command palette's open-and-reset logic, fixed with a ref-tracked
  `openPalette()` helper instead of a side-effecting state updater).
  Live in a browser: re-ran the full Phase 9 and Phase 10 Playwright
  regression suites (rubric tuning, role cloning, candidate comparison,
  outreach email handoff, webhook config/test, job lifecycle, ownership,
  notes, search) against the redesigned UI end to end — all still pass,
  confirming the visual pass didn't touch any functional behavior.
  Screenshotted every major screen (login, dashboard empty/populated,
  every job-workspace tab, command palette open, guide, global
  candidates, print report in both screen and print media) for visual
  QA.
- **Known follow-up, not done here:** the Guide page's embedded
  screenshots and walkthrough video (built in Phase 8) still show the
  old top-nav/teal UI — they're static assets from before this pass and
  now visually mismatch the live product. Refreshing them means
  re-running the screenshot/video capture pipeline from Phase 8, which
  is its own scoped effort, not a quick edit; flagged here rather than
  silently left stale.
- **Not built, deliberately out of scope:** a component library/design-
  system package (Button/Input/etc. as reusable exported components) —
  this pass worked by swapping shared tokens and the few truly-shared
  components (`Card`, `StatusChip`, `AccountMenu`) rather than
  refactoring every inline `className` string in the ~1700-line job
  workspace page; a real component library is a larger, separate
  investment. Also out of scope: a light/dark theme *toggle* (the app
  already respects OS-level `prefers-color-scheme` via the token system,
  same as every earlier phase — no in-app switch was added).

## Running the product layer locally

```bash
cd gtm-sourcing-agent
source .venv/bin/activate       # after the Quick start in README.md
pip install -e ".[dev]"          # picks up fastapi/uvicorn/sqlalchemy

export ANTHROPIC_API_KEY=...     # stage endpoints still need this
uvicorn gtm_sourcing_agent.api:app --reload --port 8000
```

`GET /health` for a liveness check, `GET /jobs` for the dashboard's data,
interactive API docs at `/docs` (FastAPI's built-in Swagger UI). The
SQLite file lives at `data/gtm_sourcing_agent.db`, relative to the
installed package (gitignored, same reasoning as `workspace/*.json`).
`GTM_CORS_ORIGINS` (comma-separated) controls which frontend origins may
call the API — defaults to `http://localhost:3000`.

Then, in a second terminal, the frontend:

```bash
cd gtm-sourcing-agent/frontend
npm install
npm run dev
```

Open `http://localhost:3000` — **not** `http://127.0.0.1:3000`, see
`frontend/README.md`'s note on `allowedDevOrigins`.

### Without an API key — the mock LLM dev server

To exercise the whole product (every tab, every action button) without a
real `ANTHROPIC_API_KEY`, run the mock server instead of `uvicorn`
directly:

```bash
cd gtm-sourcing-agent
source .venv/bin/activate
python scripts/mock_llm_server.py     # same port 8000, no API key needed
```

Every response is fabricated (see the script's docstring) — never use it
for anything but local UI development.

### Deploying a public demo (split-host: frontend + backend on different domains)

The frontend (Next.js) and backend (FastAPI) are ordinary, separately
deployable services — there's no coupling beyond HTTP. A natural split is
Vercel for the frontend and any host that runs a persistent Python
process for the backend (Render, Railway, Fly.io — anything that isn't
serverless-only, since the task queue's worker thread and SQLite file
both need one long-lived process).

Putting frontend and backend on **different domains** makes the session
cookie a cross-site cookie from the browser's point of view, which needs
different settings than local dev:

- `GTM_COOKIE_SAMESITE=none` (backend env var) — `SameSite=Lax`, the
  local-dev default, is not sent on cross-origin `fetch()` calls at all;
  `None` is required for the frontend's calls to carry the cookie.
  Setting this also forces `secure=True` regardless of
  `GTM_COOKIE_SECURE`, since browsers reject a `SameSite=None` cookie
  that isn't `Secure` — both requirements come from browser cookie
  semantics, not this app's own choice.
- `GTM_CORS_ORIGINS=https://<your-frontend-domain>` (backend env var) —
  must be the exact deployed frontend origin (scheme + host, no
  trailing slash); wide open (`*`) doesn't work here since
  `allow_credentials=True` requires an explicit origin.
- `NEXT_PUBLIC_API_URL=https://<your-backend-domain>` (frontend build-time
  env var) — every API call in `lib/api.ts` is relative to this.
- The backend binds `$PORT`/`0.0.0.0` automatically when `$PORT` is set
  (`scripts/mock_llm_server.py`) — the convention most Python-hosting
  platforms use to tell a service which port to listen on.

Same-domain deployments (frontend and backend both under one domain, via
a reverse proxy or platform-level rewrite) don't need any of this —
`SameSite=Lax` already works when there's no cross-site request in the
first place.

One limitation worth knowing going in: most free hosting tiers for a
persistent Python process use an **ephemeral filesystem** — the SQLite
file is wiped on every redeploy, and often on every restart after a
period of inactivity. Fine for a demo (it just starts with an empty
workspace again); not a substitute for a real database if this ever
needs to hold data across restarts.
