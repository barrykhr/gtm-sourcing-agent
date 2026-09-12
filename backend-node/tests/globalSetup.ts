// Runs once before the whole test run (not per-file). Points every test
// process at a dedicated test database — never the dev/prod one — and
// makes sure its schema is current before anything connects.
import { execSync } from "node:child_process";

const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ?? "postgresql://postgres:talyndev@localhost:5432/talyn_test";

export default function globalSetup() {
  execSync("npx prisma db push --skip-generate --accept-data-loss", {
    env: { ...process.env, DATABASE_URL: TEST_DATABASE_URL },
    stdio: "inherit",
  });
}
