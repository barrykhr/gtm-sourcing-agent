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

This repository holds the whole product: a Python/FastAPI backend, a
SQLite-backed data layer, and a Next.js frontend, plus a standalone Python
CLI for the underlying sourcing pipeline.

## Project layout

```
gtm-sourcing-agent/
├── README.md                  this file
├── ARCHITECTURE.md            design, data flow, invariants, LLM strategy
├── requirements.txt           Python runtime dependencies
├── pyproject.toml             Python package metadata (used for local dev / CLI install)
├── scripts/
│   └── mock_llm_server.py     runnable FastAPI app — see "Running the backend" below
├── docs/
│   ├── implementation-plan.md phased CLI/pipeline build plan
│   └── product-plan.md        phased product (API + frontend) build plan
├── src/gtm_sourcing_agent/
│   ├── api.py                  FastAPI app: routes, auth, CORS
│   ├── models/                 Pydantic schemas — the contract for every stage
│   ├── prompts/                per-stage prompt templates (editable, versioned)
│   ├── stages/                 one module per pipeline stage
│   ├── db.py / db_storage.py   SQLite persistence layer
│   ├── llm_client.py           thin Claude API wrapper
│   └── cli.py                  command-line entry point (pipeline as a CLI)
├── frontend/                   Next.js app (the web UI)
├── workspace/                  per-role CLI working data (gitignored)
└── tests/                      pytest suite (backend)
```

## Running the backend locally

The backend ships with a **demo mode** entry point that runs the real
FastAPI app with AI responses replaced by realistic canned data — no
Anthropic API key required, $0 cost, safe to click around in:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/mock_llm_server.py
```

This starts the API on `http://127.0.0.1:8000` (or on `$PORT` if that
environment variable is set, which is how hosted platforms like Render
tell the process which port to listen on).

> Demo mode is for exploring the product only — every AI-shaped response
> it returns is fabricated sample data, not real analysis. See
> `scripts/mock_llm_server.py`'s module docstring for exactly what it
> fakes.

To run the real backend against live Claude API calls instead, set
`ANTHROPIC_API_KEY` and run `uvicorn gtm_sourcing_agent.api:app` after
`pip install -e .` (installs the package so its real, non-mocked imports
resolve). Every pipeline stage will then make a genuine Anthropic API call
and incur normal API usage cost.

## Running the frontend locally

```bash
cd frontend
npm install
npm run dev
```

By default the frontend talks to `http://localhost:8000`. Set
`NEXT_PUBLIC_API_URL` to point it at a different backend URL (see
"Deploying this app" below).

## Running the pipeline as a CLI (no web UI)

The sourcing pipeline is also usable directly from the terminal, independent
of the API/frontend:

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...

python -m gtm_sourcing_agent.cli intake path/to/jd.txt --role-id acme-ae-2026
python -m gtm_sourcing_agent.cli calibrate acme-ae-2026
python -m gtm_sourcing_agent.cli icp acme-ae-2026
python -m gtm_sourcing_agent.cli status acme-ae-2026        # what's run, what's next
python -m gtm_sourcing_agent.cli show acme-ae-2026           # dump the whole workspace file
```

Every command that calls a stage fails with a one-line `Error: ...` message
and exit code 1 — not a raw traceback — when an upstream checkpoint is
missing or the LLM call fails. See `ARCHITECTURE.md` for the full pipeline
shape and `docs/implementation-plan.md` for phase-by-phase CLI status.

## Deploying this app (split-host: frontend + backend on different domains)

The frontend (Next.js) and backend (FastAPI) deploy separately — e.g.
**Vercel** for the frontend and **Render** (or any host that runs a
persistent Python process — the backend needs one long-lived process for
its SQLite file and background task worker) for the backend.

**Backend (Render or similar):**
- Build command: `pip install -r requirements.txt`
- Start command: `python scripts/mock_llm_server.py`
- Environment variables:
  - `GTM_COOKIE_SAMESITE=none` — required whenever the frontend and
    backend are on different domains, so the browser sends the session
    cookie on the frontend's cross-origin requests at all.
  - `GTM_CORS_ORIGINS=https://<your-frontend-domain>` — must be the
    exact deployed frontend origin (scheme + host, no trailing slash).

**Frontend (Vercel or similar):**
- Root directory: `frontend`
- Environment variable: `NEXT_PUBLIC_API_URL=https://<your-backend-domain>`
  — every API call in `frontend/lib/api.ts` is relative to this.

One limitation worth knowing going in: most free hosting tiers for a
persistent Python process use an **ephemeral filesystem** — the SQLite
file is wiped on every redeploy, and often on every restart after a period
of inactivity. That's fine for a demo (it just starts with an empty
workspace again) but isn't a substitute for a real database if this ever
needs to hold data across restarts.

See `docs/product-plan.md`'s "Deploying a public demo" section for more
detail on the cross-site cookie/CORS mechanics.

## Design principles

- **The recruiter decides, always.** Nothing is auto-rejected, hidden, or
  sent without explicit recruiter action.
- **Evidence discipline.** Every fact about a candidate is labeled
  `VERIFIED`, `INFERRED`, or `NOT STATED` — speculation is never presented
  as fact.
- **No fabricated capabilities.** Outreach is drafted, never auto-sent;
  "mark as sent" only records the recruiter's own action. The one
  exception, clearly labeled, is the demo-mode backend described above,
  which exists purely so the product can be explored without a paid API
  key.

See `ARCHITECTURE.md` for the full design rationale and data flow.
