# Implementation Plan

Phased so nothing gets built before the piece it depends on exists, and so
each phase ships something the recruiter can actually use. "Done" for a
phase means: models validated, stage runs end-to-end against a real JD,
output manually reviewed for evidence-discipline compliance.

## Phase 0 — Scaffolding (this change)

- Repo layout, architecture doc, data models (schemas only, no LLM calls
  wired up yet), prompt templates, stage function *signatures* (stubs),
  CLI skeleton, storage read/write for the workspace JSON, `.gitignore`,
  dependency manifest.
- No network calls. No Anthropic API key required to run tests.

## Phase 1 — Intake + Calibration (first real pipeline slice) — code done, acceptance outstanding

- `llm_client.py` is wired to the Anthropic API: `client.messages.parse(model="claude-opus-5", output_format=<pydantic model>, ...)`
  enforces structured output server-side, so every stage's `.parsed_output`
  is already a validated model instance — no hand-parsing, no tool-use
  boilerplate. Verified against the installed `anthropic` SDK's actual
  `messages.parse` signature (not guessed from memory).
- `stages/intake.py` and `stages/calibration.py` (and every other stage
  module) already called `llm_client.generate()` from Phase 0 scaffolding,
  so wiring `llm_client.py` makes them runnable — no further code change
  needed here.
- CLI: `intake`, `calibrate` — runnable now given credentials.
- **Not yet done: acceptance testing against a real API key.** This dev
  environment has no `ANTHROPIC_API_KEY` / `ant auth` credential, so the
  call path is verified structurally (imports, SDK signature match, full
  offline test suite green) but not exercised live. Before trusting this
  in a real sourcing workflow, run it against 3 real JDs spanning
  different role families (e.g. AE, CSM, SWE) and confirm
  contradiction/ambiguity flagging actually fires on a JD that has them —
  don't just test the happy path.

## Phase 2 — ICP + Talent Map + Search Strategy — code done, acceptance outstanding

- `stages/icp.py`, `stages/talent_map.py`, `stages/search_strategy.py`
  were wired against `llm_client.generate()` in Phase 0 and are runnable
  now that Phase 1 wired the client — same "not yet live-tested" caveat
  as Phase 1 applies.
- CLI: `icp`, `talent-map`, `search-strategy`.
- Acceptance: search strategy output includes multiple distinct strategies
  (broad/targeted/competitor/adjacent/geo/seniority) per §6 of the brief,
  not one boolean string; talent map explains *why* each company is
  relevant rather than listing competitor names.

## Phase 3 — Candidate Evidence Capture + Prioritization — code done, acceptance outstanding

- `stages/candidate_analysis.py`: takes recruiter-supplied candidate
  source text/notes (not scraped — see "explicitly out of scope" below)
  and structures it into `models/candidate.py`, with evidence labeling
  enforced at the schema level (every achievement/metric carries a label).
- `stages/prioritization.py`: A/B/C/D tiering with why-fit / unknowns /
  validate-next, against the ICP from Phase 2. No delete/reject path.
- CLI: `candidate add`, `candidate list`, `prioritize`.
- Acceptance: run against a batch of candidates including at least one
  deliberately weak match; confirm it's tiered D with rationale, not
  silently dropped from output.

## Phase 4 — Screening Questions + Outreach Drafting — code done, acceptance outstanding

- `stages/screening.py`, `stages/outreach.py`.
- Outreach generation must refuse (raise, not silently fabricate) if a
  candidate record has no verified facts to personalize against —
  generic outreach is a recruiter's explicit fallback, not a silent
  default.
- CLI: `screen`, `outreach`.
- Acceptance: spot-check that outreach never states an inferred fact as
  verified; must-ask screening questions target the specific unknowns
  flagged in that candidate's prioritization record, not generic
  role-family questions.

## Phase 5 — Funnel Tracking + Forecasting — done

- `models/funnel.py` stage-transition log; `stages/funnel.py` computes
  conversion rates and flags the largest leakage stage.
- Forecasting mode (§13 of the brief): given hires + timeline + either
  recruiter-supplied historical conversion rates or explicit
  market-default assumptions, back-calculate required volume at each
  stage — output must visibly label which rates are historical vs.
  assumed.
- CLI: `funnel update <candidate> <stage>`, `funnel report`,
  `funnel forecast --hires N --weeks W [--rates <file>]`.

## Phase 6 — Hardening / operational polish — partially done

- ~~Prompt-output validation-repair loop~~ — turned out unnecessary:
  `client.messages.parse(output_format=...)` enforces the schema
  server-side, so a malformed response isn't something our code needs to
  detect and retry — `response.parsed_output` is guaranteed valid or the
  call raises. Removed from scope rather than left as dead planning.
- Done: structured logging of every `llm_client.generate()` call (stage,
  model, output model, prompt size, then input/output token usage on
  success) via the standard `logging` module — `logger =
  logging.getLogger(__name__)` in `llm_client.py`. The CLI's `-v/--verbose`
  flag turns it on (`logging.basicConfig(level=INFO)` in `cli.py`'s
  `@app.callback()`); still stdout-only, no `--log-file` yet.
- Done: CLI recruiter-facing polish — `_friendly_errors` decorator turns
  a checkpoint-gating `ValueError` or an `llm_client` `RuntimeError` into
  a one-line `Error: ...` + exit code 1 instead of a Python traceback;
  `jd_path`/`--source-path` are validated to exist before a stage runs
  (Typer `exists=True`) instead of failing deep inside `.read_text()`;
  added `show` (dump a role's workspace state or one section as JSON,
  for reviewing/editing stage output without opening the file by hand)
  and `candidate list` (roster view with tier + recruiter decision).
  Covered by `tests/test_cli.py` (12 tests, `typer.testing.CliRunner`,
  no network calls).
- Done: `tests/test_stages.py` — 12 tests covering every stage's
  orchestration logic (checkpoint gating via `require_section`, storage
  merge/preserve behavior, candidate-id slugification, the
  `recruiter_decision` field never being settable by the model) against
  a mocked `llm_client.generate`, so this runs in CI with no API key and
  no network call. Full suite is 44 tests, all offline.
- Still outstanding: live acceptance testing against a real API key (see
  Phases 1-4 above) — mocked tests prove our orchestration code is
  correct, not that the prompts produce good output.
- Still outstanding: revisit whether a database or UI is needed yet
  (only if real usage says so — see Architecture §7).

## Explicitly deferred (not yet scheduled)

- **Automated candidate sourcing** (actually querying LinkedIn/Naukri/
  GitHub programmatically). Most of these have ToS restrictions on
  automated scraping; the search-strategy stage produces query strings
  for the recruiter to run by hand. Revisit only with the user's explicit
  direction on which channels/APIs are actually licensed for automated
  access.
- **Sending outreach automatically.** Draft-only by design (Architecture
  §1.4). Would require email/LinkedIn integration and, more importantly,
  a deliberate decision about where human send-approval lives.
- **Multi-recruiter / hosted deployment.**

## How to track progress

Each phase above should land as its own PR/branch slice against this
scaffolding, not as one large change. Update this file's checkmarks (or
convert to a table with status) as phases land — this file is the map,
not a status snapshot, so keep it current rather than re-deriving plan
state from git history.
