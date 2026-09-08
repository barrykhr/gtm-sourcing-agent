/**
 * Phase 5 validation: runs the full AI stage pipeline (intake through
 * conversation intelligence) against a local mock Anthropic HTTP server
 * (no real ANTHROPIC_API_KEY available in this sandbox) and asserts the
 * results land correctly in the real Postgres instance via storage.ts --
 * the same wiring the real routes will use. Also exercises the
 * talentMap/interviewQuestions retry-on-shortfall paths and the
 * interview-question generation-history append + repeat-detection logic
 * for real, not just by reading the code.
 */
import http from "node:http";
import { prisma } from "../src/db/client.js";
import * as storage from "../src/db/storage.js";

const ROLE_ID = "phase5-test-role";

let failures = 0;
function check(label: string, ok: boolean, detail?: unknown) {
  if (ok) console.log(`PASS: ${label}`);
  else { console.log(`FAIL: ${label}`, detail ?? ""); failures++; }
}

// Queue of canned response bodies (each a JS object matching the
// expected output schema for that call, in call order) plus optional
// stop_reason override.
let queue: Array<{ body: any; stopReason?: string }> = [];
let requestCount = 0;

const server = http.createServer((req, res) => {
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    requestCount++;
    const reqBody = JSON.parse(raw);
    const next = queue.shift();
    if (!next) {
      res.writeHead(500);
      res.end(JSON.stringify({ error: "mock queue empty" }));
      return;
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({
      id: `msg_${requestCount}`, type: "message", role: "assistant", model: reqBody.model,
      content: next.stopReason === "refusal" ? [] : [{ type: "text", text: JSON.stringify(next.body) }],
      stop_reason: next.stopReason ?? "end_turn", stop_sequence: null,
      usage: { input_tokens: 100, output_tokens: 50 },
    }));
  });
});

function targetCompany(n: number) {
  return {
    name: `Company ${n}`, tier: ((n % 3) + 1), why_relevant: "matches ICP",
    match_dimensions: ["product"], roles_to_target: ["AE"],
  };
}

async function main() {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as any).port;
  process.env.ANTHROPIC_BASE_URL = `http://127.0.0.1:${port}`;
  process.env.ANTHROPIC_API_KEY = "sk-test-not-real";

  // Clean slate for this test role.
  await prisma.activityLog.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.communicationLogEntry.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.candidateEvaluation.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.canonicalCandidate.deleteMany({ where: { firstSeenJobId: ROLE_ID } });
  await prisma.jobRecruiter.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.jobSection.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.job.deleteMany({ where: { roleId: ROLE_ID } });

  const intakeStage = await import("../src/stages/intake.js");
  const calibrationStage = await import("../src/stages/calibration.js");
  const icpStage = await import("../src/stages/icp.js");
  const talentMapStage = await import("../src/stages/talentMap.js");
  const searchStrategyStage = await import("../src/stages/searchStrategy.js");
  const candidateAnalysisStage = await import("../src/stages/candidateAnalysis.js");
  const prioritizationStage = await import("../src/stages/prioritization.js");
  const screeningStage = await import("../src/stages/screening.js");
  const outreachStage = await import("../src/stages/outreach.js");
  const interviewQuestionsStage = await import("../src/stages/interviewQuestions.js");
  const conversationSummaryStage = await import("../src/stages/conversationSummary.js");

  await storage.createJob(ROLE_ID, { title: "Phase 5 Test Role", ownerEmail: "nodetest@example.com" });

  // ── 1. intake ──
  queue = [{ body: {
    raw_jd_text: "(mock) JD text", company: "Acme", role_title: "Enterprise AE", function: "Sales",
    seniority: "Senior", geography: "US", role_objective: "Own net-new logos",
    must_have_requirements: ["5+ yrs closing SaaS"],
  } }];
  const jd = await intakeStage.run(ROLE_ID, "raw jd text goes here");
  check("intake.run writes job_description via mergeSection", jd.company === "Acme");
  const afterIntake = await storage.loadRole(ROLE_ID);
  check("job_description persisted and readable back", (afterIntake as any).job_description?.company === "Acme");

  // ── 2. calibration ──
  queue = [{ body: {
    must_have_criteria: ["Closed $1M+ deals"], evaluation_criteria: ["Discovery quality"],
    strong_candidate_definition: "Consistently over quota",
  } }];
  const calibration = await calibrationStage.run(ROLE_ID);
  check("calibration.run writes calibration section", calibration.must_have_criteria.length === 1);

  // ── 3. icp ──
  queue = [{ body: { target_background: "Enterprise SaaS AE", relevant_titles: ["Enterprise AE"] } }];
  const icp = await icpStage.run(ROLE_ID);
  check("icp.run writes icp section", icp.target_background === "Enterprise SaaS AE");

  // ── 4. talent_map, with a shortfall-triggered retry ──
  queue = [
    { body: { target_companies: [targetCompany(1), targetCompany(2)] } }, // only 2 -- triggers retry
    { body: { target_companies: Array.from({ length: 16 }, (_, i) => targetCompany(i + 1)) } },
  ];
  const talentMap = await talentMapStage.run(ROLE_ID);
  check("talentMap.run retries on shortfall and keeps the better result", talentMap.target_companies.length === 16, talentMap.target_companies.length);
  check("talentMap.run made exactly 2 LLM calls for the retry (3 prior + 2 here)", requestCount === 5, requestCount);

  // ── 5. search_strategy (independent regen, must not clobber target_companies) ──
  queue = [{ body: { search_strategies: [
    { name: "Naukri broad", search_type: "broad", purpose: "cast a wide net", naukri_search: "title:AE" },
  ] } }];
  const withStrategies = await searchStrategyStage.run(ROLE_ID);
  check("searchStrategy.run adds search_strategies", withStrategies.search_strategies.length === 1);
  check("searchStrategy.run preserves target_companies from talent_map.run", withStrategies.target_companies.length === 16, withStrategies.target_companies.length);

  // ── 6. candidate_analysis (dedup-relevant fields included) ──
  queue = [{ body: {
    candidate_id: "", name: "Jamie Rivera", email: "jamie@example.com", phone: "+1-555-0199",
    current_company: "Globex", current_title: "Senior AE", source_url: "",
  } }];
  const candidate = await candidateAnalysisStage.run(ROLE_ID, "Jamie Rivera resume text...", "sales", {
    sourceUrl: "https://example.com/jamie",
  });
  check("candidateAnalysis.run auto-slugifies a blank candidate_id", candidate.candidate_id === `${ROLE_ID}-jamie-rivera`, candidate.candidate_id);
  check("candidateAnalysis.run fills source_url from the arg when the model left it blank", candidate.source_url === "https://example.com/jamie");
  const afterCandidate = await storage.loadRole(ROLE_ID);
  const storedCandidate = (afterCandidate as any).candidates[candidate.candidate_id];
  check("candidateAnalysis.run auto-populates contact info via setCandidateContact", storedCandidate?.phone === "+1-555-0199" && storedCandidate?.email === "jamie@example.com", storedCandidate);

  // ── 7. prioritization ──
  queue = [{ body: {
    candidate_id: "", tier: "A", fit_score: 88, fit_rating: "GREEN", why_they_fit: ["Strong quota history"],
  } }];
  const prioritization = await prioritizationStage.run(ROLE_ID, candidate.candidate_id);
  check("prioritization.run sets candidate_id and tier", prioritization.candidate_id === candidate.candidate_id && prioritization.tier === "A");
  check("prioritization.run defaults recruiter_decision/placed on first run", prioritization.recruiter_decision === null && prioritization.placed === false);

  // Re-run prioritization after a recruiter decision was set -- must carry it forward, not wipe it.
  await prioritizationStage.setRecruiterDecision(ROLE_ID, candidate.candidate_id, "pursue");
  queue = [{ body: { candidate_id: "", tier: "A", fit_score: 91, fit_rating: "GREEN", why_they_fit: ["Even stronger on re-read"] } }];
  const reprioritized = await prioritizationStage.run(ROLE_ID, candidate.candidate_id);
  check("prioritization.run re-rank preserves an existing recruiter_decision", reprioritized.recruiter_decision === "pursue", reprioritized);

  // ── 8. screening ──
  queue = [{ body: { candidate_id: "", must_ask: ["Walk me through your largest deal"] } }];
  const screening = await screeningStage.run(ROLE_ID, candidate.candidate_id);
  check("screening.run sets candidate_id and persists must_ask", screening.candidate_id === candidate.candidate_id && screening.must_ask.length === 1);

  // ── 9. outreach draft ──
  queue = [{ body: { candidate_id: "", email: "Hi Jamie, ...", personalization_basis: ["Closed $1M+ deals at Globex"] } }];
  const outreach = await outreachStage.run(ROLE_ID, candidate.candidate_id);
  check("outreach.run drafts and stores under outreach[candidate_id]", outreach.email.startsWith("Hi Jamie"));
  const markSentResult = await outreachStage.markSent(ROLE_ID, candidate.candidate_id);
  check("outreach.markSent advances funnel stage to CONTACTED", markSentResult.funnel_stage === "CONTACTED", markSentResult);

  // ── 10. interview questions, generation 1 with a shortfall retry ──
  const fewQuestions = { core_questions: [{ question: "Tell me about a deal you lost", why_it_matters: "resilience" }], role_specific_questions: [], red_flag_questions: [] };
  const enoughQuestions = {
    core_questions: Array.from({ length: 4 }, (_, i) => ({ question: `Core Q${i + 1}`, why_it_matters: "x" })),
    role_specific_questions: Array.from({ length: 4 }, (_, i) => ({ question: `Role Q${i + 1}`, why_it_matters: "x" })),
    red_flag_questions: Array.from({ length: 3 }, (_, i) => ({ question: `Flag Q${i + 1}`, why_it_matters: "x" })),
  };
  queue = [{ body: fewQuestions }, { body: enoughQuestions }];
  const historyGen1 = await interviewQuestionsStage.run(ROLE_ID);
  check("interviewQuestions.run retries on <10 questions and keeps the better generation", historyGen1.generations.length === 1 && historyGen1.generations[0]!.core_questions.length === 4);

  // Generation 2: repeats "Core Q1" verbatim -- must be flagged in repeated_questions, not silently hidden.
  const gen2WithRepeat = {
    core_questions: [{ question: "Core Q1", why_it_matters: "x" }, ...Array.from({ length: 3 }, (_, i) => ({ question: `New Core Q${i + 2}`, why_it_matters: "x" }))],
    role_specific_questions: Array.from({ length: 4 }, (_, i) => ({ question: `New Role Q${i + 1}`, why_it_matters: "x" })),
    red_flag_questions: Array.from({ length: 3 }, (_, i) => ({ question: `New Flag Q${i + 1}`, why_it_matters: "x" })),
  };
  queue = [{ body: gen2WithRepeat }];
  const historyGen2 = await interviewQuestionsStage.run(ROLE_ID);
  check("interviewQuestions.run is append-only across generations", historyGen2.generations.length === 2, historyGen2.generations.length);
  check("interviewQuestions.run flags a verbatim repeat from generation 1", historyGen2.generations[1]!.repeated_questions.includes("Core Q1"), historyGen2.generations[1]);

  // ── 11. conversation summary + intelligence (needs a real logged communication first) ──
  await storage.logCommunication(ROLE_ID, candidate.candidate_id, {
    channel: "email", direction: "outbound", content: "Reaching out about the Enterprise AE role.",
    contactUsed: "jamie@example.com", loggedBy: "nodetest@example.com",
  });
  queue = [{ body: { summary: "Initial outreach sent, no response yet.", open_items: ["Awaiting reply"] } }];
  const summary = await conversationSummaryStage.run(ROLE_ID, candidate.candidate_id);
  check("conversationSummary.run persists via setConversationSummary", summary.summary.includes("Initial outreach"));
  const afterSummary = await storage.getConversationSummary(ROLE_ID, candidate.candidate_id);
  check("conversation summary readable back from storage", afterSummary.summary === summary.summary, afterSummary);

  queue = [{ body: { current_compensation: "", interest_level: "Insufficient evidence", recommendation: "Follow up in a week" } }];
  const intelligence = await conversationSummaryStage.runIntelligence(ROLE_ID, candidate.candidate_id);
  check("conversationSummary.runIntelligence persists via setConversationIntelligence", intelligence.recommendation === "Follow up in a week");
  const afterIntelligence = await storage.loadRole(ROLE_ID);
  check("conversation_intelligence readable back from candidate state", (afterIntelligence as any).candidates[candidate.candidate_id]?.conversation_intelligence?.recommendation === "Follow up in a week");

  // ── 12. error path: requireSection throws when a checkpoint is missing ──
  await prisma.job.create({ data: { roleId: "phase5-empty-role", title: "Empty" } }).catch(() => {});
  let threw = false;
  try {
    await calibrationStage.run("phase5-empty-role");
  } catch (e: any) {
    threw = e?.constructor?.name === "StorageError" && /has no 'job_description'/.test(e.message);
  }
  check("calibration.run on a role with no job_description throws StorageError (matches Python's require_section)", threw);

  server.close();
  await prisma.job.deleteMany({ where: { roleId: "phase5-empty-role" } });
  console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
  process.exit(failures === 0 ? 0 : 1);
}

main().finally(() => prisma.$disconnect());
