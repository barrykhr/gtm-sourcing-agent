/**
 * Phase 2 validation: prove the hand-written Prisma schema reads the
 * real database the Python backend created (not a new one), and that
 * Node's crypto.pbkdf2Sync reproduces the exact same password hash
 * Python's hashlib.pbkdf2_hmac computed for a real account created via
 * the real Python auth.create_user() — see docs/migration.md §6.
 *
 * Not a unit test with a mock — this connects to the actual Postgres
 * instance both backends will share and reads rows Python wrote.
 */
import { PrismaClient } from "@prisma/client";
import crypto from "node:crypto";

const prisma = new PrismaClient();

const PBKDF2_ITERATIONS = 600_000;
const KNOWN_PASSWORD = "correct-horse-battery"; // set via the real Python auth.create_user() call

function hashPassword(password: string, saltHex: string): string {
  const salt = Buffer.from(saltHex, "hex");
  return crypto.pbkdf2Sync(password, salt, PBKDF2_ITERATIONS, 32, "sha256").toString("hex");
}

async function main() {
  let failures = 0;

  // ── 1. Read a real user Python created, verify the hash algorithm matches ──
  const user = await prisma.user.findUnique({ where: { email: "nodetest@example.com" } });
  if (!user) {
    console.log("FAIL: could not find the Python-created test user at all");
    failures++;
  } else {
    console.log(`Found user via Prisma: id=${user.id} email=${user.email} role=${user.role}`);
    const computed = hashPassword(KNOWN_PASSWORD, user.passwordSalt);
    if (computed === user.passwordHash) {
      console.log("PASS: Node.js PBKDF2 hash matches Python's stored hash exactly, byte-for-byte");
    } else {
      console.log("FAIL: hash mismatch");
      console.log("  stored (Python):", user.passwordHash);
      console.log("  computed (Node):", computed);
      failures++;
    }
    // First account on a fresh DB -> should be admin, same rule as Python
    if (user.role !== "admin") {
      console.log(`FAIL: expected role 'admin' for the first account, got '${user.role}'`);
      failures++;
    } else {
      console.log("PASS: first-account-becomes-admin rule read correctly");
    }
  }

  // ── 2. Read a real job Python created, verify every field round-trips ──
  const job = await prisma.job.findUnique({ where: { roleId: "test-role" } });
  if (!job) {
    console.log("FAIL: could not find the Python-created test job");
    failures++;
  } else {
    console.log(`Found job via Prisma: ${JSON.stringify(job, null, 2)}`);
    const checks: [string, boolean][] = [
      ["title", job.title === "Test Role"],
      ["roleFamily", job.roleFamily === "sales"],
      ["lifecycleStatus", job.lifecycleStatus === "OPEN"],
      ["ownerEmail", job.ownerEmail === "nodetest@example.com"],
      ["roleValue", job.roleValue === 200000],
    ];
    for (const [field, ok] of checks) {
      if (ok) console.log(`PASS: Job.${field} matches Python-written value`);
      else {
        console.log(`FAIL: Job.${field} does not match`);
        failures++;
      }
    }
    // Expected revenue is computed, not stored -- verify the same formula
    // (role_value * 8.33%) independently in TS, matching revenue.py exactly.
    const REVENUE_MARGIN_PERCENTAGE = 8.33;
    const expected = Math.round((job.roleValue! * (REVENUE_MARGIN_PERCENTAGE / 100)) * 100) / 100;
    if (expected === 16660) {
      console.log(`PASS: revenue formula reproduces Python's expected_revenue (${expected})`);
    } else {
      console.log(`FAIL: revenue formula gave ${expected}, Python computed 16660`);
      failures++;
    }
  }

  // ── 3. Confirm the primary-recruiter sync row (JobRecruiter) Python wrote ──
  const recruiterRow = await prisma.jobRecruiter.findFirst({
    where: { roleId: "test-role", email: "nodetest@example.com" },
  });
  if (recruiterRow && recruiterRow.assignment === "primary") {
    console.log("PASS: JobRecruiter primary-sync row (written by Python's create_job) reads correctly");
  } else {
    console.log("FAIL: expected a primary JobRecruiter row for the job owner, got:", recruiterRow);
    failures++;
  }

  console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
  process.exit(failures === 0 ? 0 : 1);
}

main().finally(() => prisma.$disconnect());
