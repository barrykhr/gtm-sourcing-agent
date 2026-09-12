import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globalSetup: ["./tests/globalSetup.ts"],
    setupFiles: ["./tests/setup.ts"],
    testTimeout: 15000,
    hookTimeout: 20000,
    pool: "forks", // one process per file -- keeps the shared Postgres test DB from racing itself
    poolOptions: { forks: { singleFork: true } },
  },
});
