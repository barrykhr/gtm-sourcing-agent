/**
 * Phase 4 validation: exercise src/db/storage.ts's ported functions
 * against the real Postgres instance (the same one Python and the
 * Phase 2/3 scripts have been writing to), not a mock or fresh DB.
 *
 * Covers: workspace state load/save, candidate dedup merge, evaluation
 * prioritization, cross-job analytics, tasks, activity log, revenue,
 * search, and outreach settings/due-followups -- the highest-risk
 * pieces being the Prisma compound-unique-key lookups
 * (roleId_sectionKey, roleId_candidateEvaluationId) used by
 * saveRole/mergeCandidate/mergePrioritization, which have not been
 * runtime-verified before this script.
 */
import { prisma } from "../src/db/client.js";
import * as storage from "../src/db/storage.js";

const ROLE_ID = "test-role";
const OWNER = "nodetest@example.com";

let failures = 0;
function check(label: string, ok: boolean, detail?: unknown) {
  if (ok) {
    console.log(`PASS: ${label}`);
  } else {
    console.log(`FAIL: ${label}`, detail ?? "");
    failures++;
  }
}

async function main() {
  // ── 1. loadRole / mergeSection round-trip ──
  const state = await storage.loadRole(ROLE_ID);
  check("loadRole returns role_id", state.role_id === ROLE_ID, state.role_id);

  await storage.mergeSection(ROLE_ID, "job_description", { raw_text: "Node phase4 check", parsed: { title: "X" } });
  const afterMerge1 = await storage.loadRole(ROLE_ID);
  check(
    "mergeSection upserts a section (roleId_sectionKey) and loadRole reads it back",
    (afterMerge1 as any).job_description?.raw_text === "Node phase4 check",
    (afterMerge1 as any).job_description
  );

  // mergeSection replaces the whole section value (matches Python's merge_section == wholesale overwrite)
  await storage.mergeSection(ROLE_ID, "job_description", { raw_text: "Node phase4 check", extra_field: "merged-in" });
  const afterMerge2 = await storage.loadRole(ROLE_ID);
  check(
    "mergeSection overwrite reads back correctly on a second write",
    (afterMerge2 as any).job_description?.extra_field === "merged-in",
    (afterMerge2 as any).job_description
  );

  // ── 2. candidate dedup: mergeCandidate twice under different candidate_ids, same source_url ──
  const sourceUrl = "https://example.com/candidate/node-phase4-test";
  const candidateIdA = "phase4-cand-a";
  const candidateIdB = "phase4-cand-b";
  const stateA = await storage.mergeCandidate(ROLE_ID, candidateIdA, {
    name: "Phase Four Candidate",
    current_company: "Acme Corp",
    source_url: sourceUrl,
    evidence_of_fit: "initial pass",
  });
  const stateB = await storage.mergeCandidate(ROLE_ID, candidateIdB, {
    name: "Phase Four Candidate",
    current_company: "Acme Corp",
    source_url: sourceUrl + "/", // trailing slash, should still dedup to the same canonical candidate
    evidence_of_fit: "second pass, different candidate_id but same canonical person",
  });
  const canonicalA = stateA.candidates[candidateIdA]?.canonical_candidate_id;
  const canonicalB = stateB.candidates[candidateIdB]?.canonical_candidate_id;
  check(
    "mergeCandidate dedups on source_url (case/trailing-slash-insensitive) -- same canonical id",
    !!canonicalA && canonicalA === canonicalB,
    { canonicalA, canonicalB }
  );
  const canonicalCount = await prisma.canonicalCandidate.count({ where: { name: "Phase Four Candidate" } });
  check("dedup did not create a second CanonicalCandidate row", canonicalCount === 1, canonicalCount);

  // ── 3. mergePrioritization + analyticsOverview tier counting ──
  const beforeAnalytics = await storage.analyticsOverview();
  await storage.mergePrioritization(ROLE_ID, candidateIdA, { tier: "A", rationale: "strong fit" });
  const afterAnalytics = await storage.analyticsOverview();
  check(
    "mergePrioritization writes tier, analyticsOverview reflects it (roleId_candidateEvaluationId upsert)",
    afterAnalytics.tier_distribution.A > beforeAnalytics.tier_distribution.A,
    { before: beforeAnalytics.tier_distribution.A, after: afterAnalytics.tier_distribution.A }
  );

  // ── 4. recruiter decision + placement -> revenue ──
  await storage.mergePrioritization(ROLE_ID, candidateIdA, {
    tier: "A", rationale: "strong fit",
    recruiter_decision: "shortlist",
    placed: true,
    placement_fee: 5000,
  });
  const revenue = await storage.revenueOverview();
  check("revenueOverview counts the placement fee just written", revenue.realized_revenue >= 5000, revenue);
  const recruiterRev = await storage.recruiterRevenue();
  const ownerRow = recruiterRev.find((r: any) => r.email === OWNER);
  check("recruiterRevenue attributes it to the job owner", !!ownerRow, recruiterRev);

  // ── 5. tasks ──
  const task = await storage.createTask(ROLE_ID, "test_stage", {});
  check("createTask returns a pending task", task.status === "pending", task);
  await storage.updateTask(task.task_id, { status: "succeeded", result: { ok: true } });
  const fetchedTask = await storage.getTask(task.task_id);
  check("getTask reflects the update", fetchedTask?.status === "succeeded", fetchedTask);

  // ── 6. activity log ──
  await storage.logActivity(ROLE_ID, OWNER, "phase4_check", { detail: "verification run" });
  const activity = await storage.listActivity(ROLE_ID);
  check("logActivity + listActivity round-trips", activity.some((a: any) => a.action === "phase4_check"), activity.length);

  // ── 7. search ──
  const results = await storage.search("Test Role");
  check("search finds the job by title", results.jobs.some((j: any) => j.role_id === ROLE_ID), results.jobs);

  // ── 8. outreach settings / due followups (should not throw even with sparse data) ──
  const settings = await storage.getWorkspaceSettings();
  check("getWorkspaceSettings returns an object with a template", typeof settings.followup_template === "string", settings);
  const due = await storage.dueFollowups();
  check("dueFollowups executes without throwing", Array.isArray(due), due);

  console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
  process.exit(failures === 0 ? 0 : 1);
}

main().finally(() => prisma.$disconnect());
