# Architecture

## 1. Design invariants (non-negotiable)

These constraints come directly from the operating brief and shape every
design decision below. They are not aspirational — the code should make
violating them structurally awkward, not just discouraged by convention.

1. **No automated rejection.** No stage may delete, hide, auto-archive, or
   silently downgrade a candidate. Prioritization produces a tier (A/B/C/D)
   and a rationale; a human sets any terminal disposition.
2. **Evidence discipline.** Every candidate-facing fact is labeled
   `VERIFIED` (stated in a source), `NOT STATED` (absent from sources), or
   `INFERRED` (a reasonable read that is not explicitly stated). The system
   must never present an inferred fact as verified, and must never invent
   facts to fill a gap.
3. **Recruiter is the checkpoint, not the audience.** Every stage writes
   structured output back to the role workspace *before* the next stage can
   run against it. The recruiter can edit that file between stages — the
   pipeline reads the current file state, not a cached in-memory value, so
   edits are never silently overwritten.
4. **Outreach requires explicit send confirmation.** The system drafts
   outreach; it does not have a code path that dispatches it. Sending is a
   separate, deliberate action outside this repo's scope for now (see
   Implementation Plan, Phase 6).
5. **Assumptions are labeled as assumptions.** Forecasting and funnel-rate
   calculations must distinguish a recruiter-supplied historical rate from a
   market-default assumption used in its absence.

## 2. Why a pipeline of typed stages (not one big prompt)

A single mega-prompt that takes a JD and returns "candidates + outreach"
fails the brief in two specific ways: it can't be checkpointed (the
recruiter can't correct the ICP before it propagates into search strings),
and it can't be audited (you can't tell whether a claim about a candidate
came from evidence or from the model bridging a gap). Splitting into
stages — each with a narrow input, a narrow output schema, and a single
prompt — fixes both:

- **Checkpointing**: each stage reads/writes a section of the role's
  workspace file. The recruiter can hand-edit any section; the next stage
  consumes whatever is on disk.
- **Auditability**: each stage's output is validated against a Pydantic
  model at the model boundary. A stage that produces malformed output (e.g.
  a candidate achievement with no evidence label) fails validation instead
  of silently propagating.
- **Replaceability**: `search_strategy` can be re-run after `icp` is
  corrected without re-running `intake` or `calibration`. Cost and latency
  scale with what actually changed.

## 3. Data flow

```
                         ┌─────────────────────────────┐
                         │   workspace/<role_id>.json    │
                         │   (single source of truth)    │
                         └───────────────┬───────────────┘
                                          │ read current section
                                          ▼
JD text ──▶ [intake] ──▶ [calibration] ──▶ [icp] ──▶ [talent_map] ──▶ [search_strategy]
                                                                             │
                candidate source ──▶ [candidate_analysis] ◀─────────────────┘
                                          │
                                          ▼
                                   [prioritization]  (A/B/C/D + rationale, never deletes)
                                          │
                              ┌───────────┴───────────┐
                              ▼                        ▼
                       [screening]              [outreach]  (draft only)
                              │                        │
                              └───────────┬────────────┘
                                          ▼
                                    [funnel] (stage transitions, conversion, forecast)
```

Every bracketed stage is: `prompt template (prompts/*.md) + Pydantic output
model (models/*.py) + a stage function (stages/*.py) that calls llm_client,
validates the response, and merges it into storage.py's workspace file`.

## 4. Storage: why a flat JSON file per role, not a database

At this stage, the unit of work is "one recruiter, one role, tens to low
hundreds of candidates" — not multi-tenant concurrent write load. A single
`workspace/<role_id>.json` per role:

- is trivially diffable in git if the recruiter wants version history,
- is directly human-editable (the checkpoint model in §1.3 depends on this),
- needs no migration story while the schema is still moving.

`storage.py` is the only module that touches the filesystem, so swapping
this for SQLite/Postgres later (once concurrent multi-recruiter use is
real) is a storage-layer change, not a pipeline rewrite.

**Update (Phase 1 of the product build, `docs/product-plan.md`):** that
swap has happened, additively. `db_storage.py` implements the same six
functions against SQLite instead of files, and every `stages/*.py`
function takes a `storage_backend=storage` kwarg so the CLI keeps using
the file backend unchanged while the new API (`api.py`) passes
`db_storage`. `storage.py` itself was not modified — this section's
prediction held, and the two backends now run side by side rather than
one replacing the other.

## 5. LLM layer

`llm_client.py` wraps the Anthropic Messages API behind one function:
`generate(prompt: str, output_model: type[BaseModel]) -> BaseModel`. It
calls `client.messages.parse(..., output_format=output_model)`, which
enforces the Pydantic model's JSON schema server-side and returns an
already-validated `response.parsed_output` — stage code never hand-parses
free text. Model choice (default `claude-opus-5`) and error handling live
here, not scattered across stages. Retries for transient failures
(429/5xx/connection errors) are handled by the SDK's built-in
`max_retries`; a non-retryable failure (auth, bad request, refusal) is
raised as a `RuntimeError` with the cause attached, for the caller to
surface to the recruiter rather than silently produce empty output.

## 6. Role-specific evaluation

Section 9 of the operating brief (sales / SDR / CS / KAM / product /
engineering evaluation criteria) is not hard-coded per role type in Python.
It lives in `prompts/candidate_analysis.md` and `prompts/prioritization.md`
as a role-family lookup the prompt applies contextually, because the set of
role families and their metrics will grow faster than it's worth encoding
as a type system. If a role family's evaluation criteria need to be testable
in code (e.g. quota-attainment math), that becomes a typed helper called
from the stage function — not a schema change.

## 7. What's deliberately out of scope right now

- **Sending outreach** (email/LinkedIn API integration) — drafting only.
- **Sourcing channel integrations** (LinkedIn Recruiter, Naukri, GitHub
  search APIs) — the search-strategy stage produces query strings for the
  recruiter to run manually; it does not execute them.
- **A web UI** — CLI + JSON files first; a UI is a presentation layer on
  top of the same workspace files once the pipeline is proven.
- **Multi-recruiter / multi-tenant concerns** (auth, shared DB) — single
  recruiter, local-first, for now.

These are sequencing decisions, not rejections — see the implementation
plan for when each becomes worth building.
