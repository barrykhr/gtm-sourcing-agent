import { defineConfig } from "@playwright/test";
import path from "path";

/**
 * The first committed Playwright config/test in this repo (audit flags
 * every prior Playwright run as an ad-hoc scratch script — see
 * docs/TALYN_V2_AUDIT.md §9 / TALYN_V2_ARCHITECTURE.md §10). Spins up a
 * real backend (isolated SQLite file, no ANTHROPIC_API_KEY needed for
 * the CRUD paths this suite covers) and the real Next dev server, and
 * drives them through an actual browser — no mocks.
 *
 * Deliberately does NOT cover the AI-extraction-through-chat path: that
 * needs a live Anthropic API key, which this repo's CI doesn't carry.
 * The AI-dependent paths (extraction, Copilot chat) are covered by the
 * backend's own mocked-llm_client tests instead (see
 * tests/test_role_intelligence_extraction.py, tests/test_orchestrator_role_intelligence.py,
 * tests/test_role_intelligence_eval_fixtures.py) — this suite covers
 * the deterministic, no-LLM-involved UI<->API<->DB round trip:
 * creating a role and editing its requirements directly.
 */

const E2E_DB_PATH = path.join(__dirname, ".e2e-data", "e2e.db");
const API_PORT = 8311;
const WEB_PORT = 3311;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false, // one shared SQLite file across the whole run
  retries: 0,
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "on-first-retry",
    // CI/sandbox images in this repo's dev environment pin a specific
    // Chromium build pre-fetched outside of Playwright's own install
    // step; PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH lets that match without
    // forcing every contributor's machine onto the same pinned path.
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : undefined,
  },
  webServer: [
    {
      command:
        `rm -f "${E2E_DB_PATH}" && mkdir -p "${path.dirname(E2E_DB_PATH)}" && ` +
        `cd .. && .venv/bin/uvicorn gtm_sourcing_agent.api:app --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        PYTHONPATH: "src",
        DATABASE_URL: `sqlite:///${E2E_DB_PATH}`,
        GTM_CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
        GTM_FRONTEND_URL: `http://localhost:${WEB_PORT}`,
        GTM_COOKIE_SAMESITE: "none",
      },
    },
    {
      command: `npx next dev -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        NEXT_PUBLIC_API_URL: `http://localhost:${API_PORT}`,
      },
    },
  ],
});
