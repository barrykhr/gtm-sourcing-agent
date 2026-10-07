# TALYN V2 — Architecture

Companion to `TALYN_V2_AUDIT.md`. That document is descriptive (what exists, with
a KEEP/REFACTOR/REBUILD/DEPRECATE/UNKNOWN call on every area). This document is
prescriptive: what we build, in what order, and why — scoped to **Feature 01
(Create Role + Role Intelligence + Contextual Talyn)** only. Nothing past
Feature 01 is designed here beyond the minimum shape needed so Feature 01
doesn't paint us into a corner (multi-tenancy, evidence vocabulary, agent
tool pattern).

No destructive changes. No Feature 02. No implementation starts from this
document alone — it is scoped for approval, per the master prompt's §48.

---

## 1. Current architecture (recap)

One FastAPI monolith (`api.py`, 98 routes) → Postgres via SQLAlchemy ORM
(`models_orm.py`, 18 tables, Alembic-migrated) → single in-process task queue
for long-running AI work. Frontend is Next.js 16 / React 19 / Tailwind v4, one
AppShell with a 4-item sidebar, a 2,000-line per-job workspace page with 9
tabs. AI runs through `orchestrator.py`: a typed-tool Claude agent
(`USER → CONVERSATION LAYER → TALYN AGENT → TYPED TOOLS → APPLICATION
SERVICES → DATABASE`) already structurally close to what the master prompt
asks for. Single shared workspace, not multi-tenant. See audit §1 for the
full account.

The architecture below is written as a diff against this, not a replacement
of it. Every "proposed" piece below names the existing piece it extends or
the gap it fills.

## 2. Proposed architecture

Three decisions carry the whole design:

1. **Extend `orchestrator.py`'s tool pattern — do not replace it.** It
   already enforces "LLM never touches SQL" (audit §5). Feature 01 adds new
   typed tools to the same registry; it does not introduce a second agent
   framework.
2. **Make new tables tenant-aware now, enforce tenancy later.** Multi-tenancy
   is audit's single largest gap (§9), but building full org/RBAC is not
   Feature 01's job and would violate "build one feature at a time" (master
   prompt §47). Compromise: every new table Feature 01 introduces carries an
   `organization_id` column from day one (nullable FK to a new, minimal
   `Organization` table seeded with one row for the existing single
   workspace). No enforcement logic (no RBAC, no cross-org isolation checks)
   ships in Feature 01. This costs one column and one seed row now, and
   avoids an N-table migration later when multi-tenancy actually gets built.
3. **Extend the evidence vocabulary to 4 states where Feature 01 introduces
   new evidence-bearing fields; leave the existing 3-state `EvidenceLevel`
   untouched where it's already used (candidate competency scoring).**
   Changing `EvidenceLevel` itself would touch candidate code outside
   Feature 01's scope and risks live data. Instead, Feature 01 defines its
   own `RequirementEvidenceLevel = CONFIRMED | INFERRED | NOT_STATED |
   CONFLICTING` for role requirements specifically. Reconciling the two
   vocabularies into one shared enum is a follow-up decision, not Feature
   01's.

## 3. Product architecture (Feature 01 only)

Feature 01 replaces today's "intake → calibration" flow (a linear, form-plus-AI-summary
sequence, audit §2) for one role-creation path:

- **Create Role**: recruiter pastes/writes a JD (or starts blank). Talyn
  extracts structured requirements with evidence, rather than producing one
  opaque "hiring profile" summary (today's `build_hiring_profile` output).
- **Role Intelligence**: the requirements list, ICP, and ambiguities become
  first-class, individually editable objects — not fields buried in a
  free-text profile. Each requirement shows CONFIRMED/INFERRED/NOT
  STATED/CONFLICTING + source span + confidence, per the master prompt's
  evidence vocabulary (§ "Evidence vocabulary").
- **Contextual Talyn**: the existing role-scoped Copilot (`CopilotPanel`,
  audit §3/§5) gains the new typed tools below and becomes the only way to
  mutate role requirements — typed commands ("make Databricks mandatory"),
  not a disconnected chat window. No new standalone chatbot surface is
  introduced.

What is explicitly out of scope here (per master prompt §47): sourcing,
talent maps, screening, outreach — all unchanged, still fed by the *existing*
hiring-profile pipeline until a later feature migrates them onto the new
requirement model.

## 4. UX architecture (Feature 01 only)

- Today's job-workspace page (`app/jobs/[role_id]/page.tsx`, 2,000 lines, 9
  tabs — audit §3/§9) is not rebuilt wholesale in Feature 01. Only the tab(s)
  covering intake/calibration/hiring-profile are replaced with a new "Role
  Intelligence" view: a requirements list (grouped by category, each row
  showing value + priority + evidence badge + source), an ICP summary panel,
  and an ambiguities panel, each independently editable. This is the first
  concrete step toward audit's "REBUILD (structurally)" verdict on the
  job-workspace page, taken narrowly rather than as a full rewrite.
- Contextual Talyn: `CopilotPanel` already renders inline in the job
  workspace (audit §3). Feature 01 adds the new tool-backed commands to it;
  no new panel/route/surface.
- No new sidebar items. No IA change. The master prompt is explicit that
  sidebar/IA changes are earned by workflow evidence, not assumed up front
  (§ "long-term IA").
- Design tokens, typography, dark theme: unchanged (audit §4 verdict: KEEP).
  New UI is built with existing primitives (`Card`, `Button`, `ProgressBar`,
  `StatusChip`) plus whatever small set of new primitives the
  requirements-list/evidence-badge UI needs — not a shadcn/ui migration.
  Adopting shadcn/Framer Motion/TanStack Query wholesale is a larger, separate
  decision (audit §9 lists it as a stack gap, not a Feature 01 blocker); Feature
  01 does not require it and does not block on it.

## 5. AI architecture

- **LLM abstraction**: reuse `llm_client.generate()` (structured-output
  Anthropic calls, already in place — audit §5). No new LLM client.
- **Observability gap (audit §5/§9) gets a minimal fix inside Feature 01's
  scope, not a general solution**: every new typed tool call and every
  `llm_client.generate()` call made for role-extraction is written to a new
  `agent_run` / `agent_action` table pair (see §7) — request id, org id
  (nullable for now), user id, role id, tool name, input/output summary,
  model, input/output tokens, latency, error if any. This gives Feature 01
  real audit trail and cost tracking without building the full
  Sentry/OpenTelemetry/PostHog pipeline the master prompt describes as
  future work (§ "Observability").
- **Hallucination guardrail**: every extracted requirement must cite a
  source span from the submitted JD text, or be explicitly marked
  `INFERRED`/`NOT_STATED` with no fabricated quote. This mirrors the existing
  discipline already enforced for candidate evidence (audit §10 — "evidence-
  labeling discipline... worth preserving").
- **No chain-of-thought exposure**: tool responses return a concise
  rationale string per the master prompt's ask, never raw model reasoning.

## 6. Agent architecture

Extends `orchestrator.py` directly. New `@beta_tool`-wrapped functions,
following the existing pattern (thin wrapper around a plain, directly
testable function in `TOOL_IMPLS`, same as today's 11 tools — audit §5):

| Tool | Mutating? | Backing service |
|---|---|---|
| `get_role` | no | reads `Job` + new `RoleRequirement` rows |
| `get_requirements` | no | reads `RoleRequirement` |
| `add_requirement` | **yes** | inserts `RoleRequirement`, writes `RoleVersion` |
| `update_requirement` | **yes** | updates `RoleRequirement`, writes `RoleVersion` |
| `remove_requirement` | **yes** | soft-deletes `RoleRequirement`, writes `RoleVersion` |
| `change_requirement_priority` | **yes** | updates `RoleRequirement.priority`, writes `RoleVersion` |
| `get_icp` | no | reads `RoleICP` |
| `update_icp` | **yes** | updates `RoleICP`, writes `RoleVersion` |
| `get_ambiguities` | no | reads `RoleAmbiguity` |
| `resolve_ambiguity` | **yes** | resolves `RoleAmbiguity`, may call `add_requirement`/`update_requirement` |
| `generate_search_strategy` | no (AI call, no DB write) | reads requirements + ICP, returns a strategy object — does not persist (out of scope until the sourcing feature) |
| `get_role_history` | no | reads `RoleVersion` |

**Mutation-safety rung**: every mutating tool follows the existing
propose/confirm split (audit §5 — today's one working instance, on
`hiring_profile` edits). Each mutating tool has a `propose_*` variant that
returns a diff + impact description with no DB write, and an `apply_*`
variant that performs the actual mutation — called only after explicit
recruiter confirmation, exactly like today's `POST
/jobs/{role_id}/chat/confirm` flow. This is "EXECUTE WITH APPROVAL" (master
prompt's autonomy ladder) applied to the new tools; Feature 01 does not
reach for "EXECUTE WITH GUARDRAILS" or "AUTONOMOUS" — those are explicitly
future rungs, not this feature's.

The LLM never writes SQL and never calls a DB session directly — every tool
call goes through these typed functions, exactly as today.

## 7. Data model

New tables (Postgres, Alembic-migrated, additive only — no existing table
altered except as noted):

```
organization            -- id, name, created_at
                         -- seeded with exactly one row for the existing
                         -- single workspace; no FK enforcement added to
                         -- existing tables in Feature 01

role_requirement         -- id, role_id (FK Job), organization_id (nullable FK),
                          -- category (skill/experience/location/comp/other),
                          -- value, priority (must_have/nice_to_have),
                          -- evidence_level (CONFIRMED/INFERRED/NOT_STATED/CONFLICTING),
                          -- source_span, confidence (0-1), created_by (user|ai),
                          -- is_deleted, created_at, updated_at

role_icp                 -- id, role_id (FK Job, 1:1), organization_id (nullable FK),
                          -- summary fields (company profile, candidate
                          -- persona, comp band, etc.), evidence per field
                          -- same vocabulary as role_requirement

role_ambiguity            -- id, role_id (FK Job), organization_id (nullable FK),
                          -- description, candidate_resolutions (json),
                          -- status (open/resolved), resolved_requirement_id (nullable FK)

role_version              -- id, role_id (FK Job), organization_id (nullable FK),
                          -- before (json snapshot), after (json snapshot),
                          -- changed_by (user_id or 'ai'), changed_at, reason

agent_run                 -- id, organization_id (nullable FK), user_id, role_id (nullable),
                          -- agent_name, started_at, finished_at, status, error

agent_action              -- id, agent_run_id (FK), tool_name, input_summary,
                          -- output_summary, model, input_tokens, output_tokens,
                          -- latency_ms, created_at
```

No existing table is altered. `Job` (the existing role-shell table) is read
by the new tools but not modified. This keeps the migration strictly
additive, satisfying "do not make destructive changes."

Role versioning captures before/after/who/when/why exactly as the master
prompt requires (§ "Role versioning"), via `role_version`, not by mutating
`role_requirement` in place.

## 8. Feature 01 implementation plan (sequencing only — not started)

1. **Migration**: add the 6 tables above via Alembic; seed the single
   `organization` row. No application code changes yet. Fully reversible,
   zero behavior change until tools are wired up.
2. **Application services**: plain Python functions (no FastAPI, no LLM)
   implementing requirement/ICP/ambiguity/version CRUD + the propose/apply
   split for each mutating operation. Unit-testable in isolation, same
   pattern as today's `db_storage.py` functions.
3. **Typed tools**: wrap each service function as a `@beta_tool` per §6,
   added to `orchestrator.py`'s existing registry. Extraction tool
   (JD → requirements/ICP/ambiguities with evidence) built as a new stage
   module, same shape as `stages/analyze_jd.py`/`build_hiring_profile.py`.
4. **API routes**: thin REST wrappers over the application services (role
   requirement CRUD, ICP get/update, ambiguity list/resolve, role history) —
   additive routes on the existing `api.py`, not a new service.
5. **Frontend**: new Role Intelligence view (requirements list + ICP panel +
   ambiguities panel) replacing the relevant tab(s) in the job workspace;
   Contextual Talyn gets the new commands surfaced in `CopilotPanel`.
6. **AI evaluation fixtures**: messy/contradictory/incomplete/ambiguous/
   implicit-requirement JD fixtures, testing extraction accuracy,
   hallucination rate, schema validity, evidence quality, and persistence —
   per master prompt's testing section — before this ships against real JDs.
7. **Integration + Playwright E2E**: create role → see extracted
   requirements with evidence → edit via UI → edit via Talyn command with
   confirm → verify role_version history.

This order follows the master prompt's build philosophy (DESIGN →
FUNCTIONALITY → INTEGRATION → TESTING → REAL DATA → REFINEMENT →
ACCEPTANCE) — migration and services first (functionality), UI last, tests
before real data.

## 9. Migration strategy

- Purely additive schema (§7) — no backfill required, no existing row
  touched. Existing roles simply have zero `role_requirement` rows until a
  recruiter re-runs extraction against them (opt-in, not automatic).
- No destructive change to `Job`, `JobSection`, or any existing table.
- Old hiring-profile summary (`JobSection`-based) continues to work
  unmodified for every role that hasn't adopted Feature 01's flow — the two
  coexist. Migrating existing roles' data into the new requirement model is
  explicitly a later decision, not part of Feature 01.
- Rollback: dropping the 6 new tables fully reverts Feature 01 with zero
  impact on existing data or functionality.

## 10. Testing strategy

- **Unit**: application-service functions (CRUD, propose/apply pairs,
  version-diff construction) — pure Python, no LLM, no HTTP, mirrors
  existing `tests/test_db_storage.py` style.
- **Tool-level**: each new `@beta_tool`'s underlying `TOOL_IMPLS` function
  tested directly (existing pattern per audit §5 — tests never call the
  SDK-wrapped closures).
- **AI evaluation fixtures**: a fixture set of real-world-shaped JDs
  (messy, contradictory, incomplete, ambiguous, implicit requirements),
  asserting extraction accuracy, hallucination rate (no fabricated source
  spans), schema validity, evidence-level correctness, and that persistence
  round-trips correctly.
- **API**: new routes tested against the existing FastAPI `TestClient`
  pattern (`tests/test_api.py`).
- **E2E**: Playwright, create-role-through-confirm-edit flow (per §8 step 7)
  — the first *committed* Playwright test in the repo (audit §9 flags that
  all prior Playwright verification has been ad hoc scratch scripts; this
  is the first one checked in).
- Full existing 465-test suite must stay green throughout — it is the
  regression safety net (audit §10).

## 11. Risks

- **Two parallel "what does this role need" models** (old `JobSection`
  hiring-profile text vs. new `role_requirement` rows) coexist until a
  later migration unifies them. Risk: sourcing/screening/outreach stages
  still read the old model, so Role Intelligence edits won't yet flow
  downstream. Mitigated by scoping Feature 01 explicitly to
  create/view/edit requirements only — downstream wiring is a named
  follow-up, not a silent gap.
- **Evidence-vocabulary fork** (3-state `EvidenceLevel` for candidates vs.
  4-state `RequirementEvidenceLevel` for roles) is a deliberate short-term
  inconsistency to avoid touching candidate code. Risk: two "evidence"
  concepts in the codebase look like an oversight if undocumented — this
  document and the audit both call it out so it reads as a decision.
  Reconciling them is future work.
- **Nullable `organization_id` with no enforcement** means Feature 01 adds
  tenant-shaped columns that do nothing yet. Risk: a future multi-tenancy
  build still has to retrofit RBAC/isolation checks on top; the column
  only saves a migration, not the harder enforcement work.
- **Extraction quality on messy JDs** is the core product risk — this is
  exactly why §10's AI evaluation fixtures gate real data use, per the
  master prompt's explicit build philosophy (test before real data).
- **Scope creep into Candidate Intelligence/Sourcing**: the typed-tool
  pattern makes it tempting to keep going once Feature 01's tools exist.
  Master prompt §47 is explicit this must not happen without separate
  approval.
