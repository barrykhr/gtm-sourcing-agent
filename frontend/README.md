# GTM Sourcing Agent — frontend

The job dashboard and job workspace UI for the [GTM Sourcing Agent](../README.md)
product layer (Phase 1 — see [`../docs/product-plan.md`](../docs/product-plan.md)).
A React/Next.js SPA calling the FastAPI service (`../src/gtm_sourcing_agent/api.py`)
directly from the browser — no server-side data fetching, no proxying.

## What's here

- `app/page.tsx` — the job dashboard: list jobs, create a new one.
- `app/jobs/[role_id]/page.tsx` — the job workspace: Overview, Hiring
  Profile, Talent Map, Sourcing, Candidates, Pipeline tabs, each an
  action button over the matching pipeline stage plus a live view of
  what that stage produced.
- `lib/api.ts` — the only file that knows the API's URL shape. Every
  page calls through here, never `fetch()` directly.

Analytics, Activity, and AI Chat tabs aren't here yet — they're Phase 3/6
per the product plan, not stubbed-in placeholders.

## Running it

```bash
npm install
npm run dev            # http://localhost:3000
```

Needs the FastAPI service running and reachable at
`NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`) — see
`../docs/product-plan.md` for how to start it, and use
`../scripts/mock_llm_server.py` instead of the real API if you want to
exercise the UI without an `ANTHROPIC_API_KEY`.

**Use `http://localhost:3000`, not `http://127.0.0.1:3000`** — Next's
dev server only allows the `localhost` origin by default
(`allowedDevOrigins` in `next.config.ts`), and requests from `127.0.0.1`
get a silent 403 on some asset chunks that leaves the page looking
loaded but non-interactive.

`npm run build && npm run lint` before committing — both are checked in
this repo's history and should stay clean.
