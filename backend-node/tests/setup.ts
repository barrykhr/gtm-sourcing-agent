// Runs before every test file. Two jobs:
//  1. Set every env var that auth/service.ts, notifications.ts, and
//     fileStorage.ts read at module-load time (or gate on) -- must
//     happen before any test file imports app code.
//  2. Mock every module that would otherwise reach a real external
//     service (Anthropic, SMTP, S3, Google) -- see tests/mocks/*.
import { afterEach, beforeAll, vi } from "vitest";

process.env.DATABASE_URL = process.env.TEST_DATABASE_URL ?? "postgresql://postgres:talyndev@localhost:5432/talyn_test";
process.env.GTM_GOOGLE_CLIENT_ID = "test-google-client-id.apps.googleusercontent.com";
delete process.env.GTM_GOOGLE_ALLOWED_DOMAIN;
delete process.env.GTM_SIGNUP_CODE; // open signup in tests
process.env.GTM_CORS_ORIGINS = "http://localhost:3000";
process.env.GTM_FRONTEND_URL = "http://localhost:3000";
process.env.FORGOT_PASSWORD_OVERRIDE_RECIPIENT = "test-inbox@example.com";
process.env.SMTP_HOST = "smtp.test.local";
process.env.SMTP_PORT = "587";
process.env.SMTP_USERNAME = "test-smtp-user";
process.env.SMTP_PASSWORD = "test-smtp-pass";
process.env.SMTP_FROM_ADDRESS = "no-reply@talyn.test";
process.env.RESUME_STORAGE_ENDPOINT_URL = "https://fake-r2.test";
process.env.RESUME_STORAGE_BUCKET = "talyn-test-resumes";
process.env.RESUME_STORAGE_ACCESS_KEY_ID = "test-access-key";
process.env.RESUME_STORAGE_SECRET_ACCESS_KEY = "test-secret-key";
process.env.RESUME_STORAGE_REGION = "auto";

vi.mock("@anthropic-ai/sdk", async () => {
  const { FakeAnthropic } = await import("./mocks/anthropic.js");
  return { default: FakeAnthropic };
});

vi.mock("nodemailer", async () => {
  const mod = await import("./mocks/nodemailer.js");
  return { default: mod.default };
});

vi.mock("@aws-sdk/client-s3", async () => import("./mocks/awsS3.js"));

vi.mock("@aws-sdk/s3-request-presigner", async () => {
  const mod = await import("./mocks/awsS3.js");
  return { getSignedUrl: mod.getSignedUrl };
});

vi.mock("google-auth-library", async () => import("./mocks/googleAuth.js"));

let prismaClient: typeof import("../src/db/client.js").prisma;

beforeAll(async () => {
  ({ prisma: prismaClient } = await import("../src/db/client.js"));
});

// Every table, in FK-safe delete order. Runs after each test so tests
// never see another test's data -- cheaper than dropping/recreating the
// schema per test, and the schema itself doesn't change between tests.
afterEach(async () => {
  const { anthropicMock } = await import("./mocks/anthropic.js");
  anthropicMock.nextParsedOutput = undefined;
  anthropicMock.chatScript = [];
  const { sentEmails } = await import("./mocks/nodemailer.js");
  sentEmails.length = 0;
  const { s3Puts } = await import("./mocks/awsS3.js");
  s3Puts.length = 0;

  await prismaClient.$transaction([
    prismaClient.activityLog.deleteMany(),
    prismaClient.communicationLogEntry.deleteMany(),
    prismaClient.candidateEvaluation.deleteMany(),
    prismaClient.canonicalCandidate.deleteMany(),
    prismaClient.task.deleteMany(),
    prismaClient.jobRecruiter.deleteMany(),
    prismaClient.jobSection.deleteMany(),
    prismaClient.job.deleteMany(),
    prismaClient.passwordResetToken.deleteMany(),
    prismaClient.session.deleteMany(),
    prismaClient.user.deleteMany(),
    prismaClient.workspaceSettings.deleteMany(),
  ]);
});
