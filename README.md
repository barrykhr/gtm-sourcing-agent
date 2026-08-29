# Talyn

An AI-assisted recruiting workflow for GTM (sales, CS, SDR/BDR, KAM) and
adjacent roles. It turns a job description into a structured, evidence-based
sourcing operation: ideal candidate profile → talent-market map → search
strategy → candidate evidence → prioritization → screening questions →
outreach → funnel tracking.

**The recruiter is always the final decision-maker.** The system never
auto-rejects a candidate, never hides a candidate from the recruiter, and
never sends outreach without recruiter review. Every AI output that touches
a candidate is labeled `VERIFIED`, `NOT STATED`, or `INFERRED` so evidence
and speculation are never mixed.

> Status: pipeline is wired end-to-end (all stages call the Anthropic API
> with structured outputs) but not yet live-tested against a real API key
> in this environment, and funnel tracking/forecasting (no LLM involved)
> is fully implemented and tested. See
> [`docs/implementation-plan.md`](docs/implementation-plan.md) for the
> phase-by-phase status and what acceptance testing is still outstanding.
>
> A product layer (SQLite persistence, a FastAPI service, and a React
> frontend) is now being built on top of this same pipeline — see
> [`docs/product-plan.md`](docs/product-plan.md). The CLI and everything
> above stays exactly as-is; the product layer is additive.

## Why this exists

Sourcing quality degrades under volume pressure: recruiters either spend too
long per role doing manual research, or move fast and lose evidence
discipline. This tool doesn't replace recruiter judgment — it removes the
mechanical bottlenecks (JD parsing, boolean generation, candidate note
structuring, screening-question drafting, outreach drafting, funnel math) so
the recruiter's time goes to the judgment calls that actually require it:
which candidates to pursue, how to calibrate with the hiring manager, and
which offer to make.

## How it works (pipeline)

```
Job Description
      │
      ▼
1. Role Intake & Deconstruction   →  structured JD + flagged ambiguities/contradictions
      │
      ▼
2. Hiring Manager Calibration     →  must-haves, red flags, "looks good but reject" list
      │
      ▼
3. Ideal Candidate Profile (ICP)  →  must / nice-to-have / transferable / disqualifier
      │
      ▼
4. Talent-Market Map              →  Tier 1/2/3 companies, title intelligence
      │
      ▼
5. Search Strategy                →  boolean strings, X-ray queries, per search channel
      │
      ▼
6. Candidate Evidence Capture     →  structured candidate record, evidence-labeled
      │
      ▼
7. Prioritization (A/B/C/D)       →  why-fit / unknowns / what-to-validate — never auto-reject
      │
      ▼
8. Screening Questions            →  must-ask / nice-to-ask / red-flag follow-ups
      │
      ▼
9. Outreach Drafting              →  personalized, evidence-only, recruiter-reviewed before send
      │
      ▼
10. Funnel Tracking & Forecasting →  stage conversion, leakage, hire-backwards forecasting
```

Every stage after (3) is a checkpoint: its output is written to the role's
workspace file for recruiter review/edit before the next stage runs. Nothing
downstream is generated silently on stale or unapproved upstream output.

## Project layout

```
gtm-sourcing-agent/
├── README.md                  this file
├── ARCHITECTURE.md            design, data flow, invariants, LLM strategy
├── requirements.txt / pyproject.toml
├── docs/
│   └── implementation-plan.md phased build plan
├── src/gtm_sourcing_agent/
│   ├── models/                Pydantic schemas — the contract for every stage
│   ├── prompts/                per-stage prompt templates (editable, versioned)
│   ├── stages/                 one module per pipeline stage
│   ├── pipeline.py             orchestrator + checkpoint gating
│   ├── llm_client.py           thin Claude API wrapper
│   ├── storage.py              per-role workspace read/write (JSON)
│   └── cli.py                  command-line entry point
├── workspace/                  per-role working data (gitignored)
└── tests/
```

## Quick start

```bash
cd gtm-sourcing-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...   # or `ant auth login`

python -m gtm_sourcing_agent.cli intake path/to/jd.txt --role-id acme-ae-2026
python -m gtm_sourcing_agent.cli calibrate acme-ae-2026
python -m gtm_sourcing_agent.cli icp acme-ae-2026
python -m gtm_sourcing_agent.cli talent-map acme-ae-2026
python -m gtm_sourcing_agent.cli search-strategy acme-ae-2026
python -m gtm_sourcing_agent.cli status acme-ae-2026        # what's run, what's next
python -m gtm_sourcing_agent.cli show acme-ae-2026 icp      # inspect one section as JSON
python -m gtm_sourcing_agent.cli show acme-ae-2026          # dump the whole workspace file

python -m gtm_sourcing_agent.cli candidate add acme-ae-2026 \
    --source-path path/to/candidate-notes.txt --role-family sales
python -m gtm_sourcing_agent.cli candidate list acme-ae-2026   # roster + tier + recruiter decision
python -m gtm_sourcing_agent.cli prioritize acme-ae-2026 <candidate_id>
python -m gtm_sourcing_agent.cli screen acme-ae-2026 <candidate_id>
python -m gtm_sourcing_agent.cli outreach acme-ae-2026 <candidate_id>

python -m gtm_sourcing_agent.cli funnel update acme-ae-2026 <candidate_id> CONTACTED
python -m gtm_sourcing_agent.cli funnel report acme-ae-2026
python -m gtm_sourcing_agent.cli funnel forecast 5 12 --source market_default

# -v/--verbose on any command shows llm_client's per-stage token-usage logs
python -m gtm_sourcing_agent.cli -v icp acme-ae-2026
```

Every command that calls a stage fails with a one-line `Error: ...` message
and exit code 1 — not a raw traceback — when an upstream checkpoint is
missing (e.g. `calibrate` before `intake`) or the LLM call fails.

The pipeline stages (`intake` through `outreach`) call the Anthropic API and
need a working credential. `status`, `show`, `candidate list`, and
`funnel update`/`report`/`forecast` are pure Python — no credential or
network call needed, and are covered by `tests/test_cli.py`. This has been verified to
import cleanly and match the installed `anthropic` SDK's method signature,
but has not yet been run end-to-end against a live API key in this
environment — see `docs/implementation-plan.md` for outstanding acceptance
testing.
