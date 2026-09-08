/**
 * Verifies orchestrator.ts's tool-use loop end-to-end against a real
 * local HTTP server standing in for the Anthropic tool-calling protocol
 * (request has `tools`, no `output_config`) -- distinct from
 * llmClient.ts's structured-output protocol, so this needs its own mock:
 * a scripted, keyword-triggered "fake assistant" (same honesty as
 * Python's mock_llm_server.py's _fake_run_chat_turn -- not natural
 * language understanding, just enough to prove the real SDK tool loop,
 * real tool execution against real Postgres via storage.ts, and
 * real pending_proposal extraction all wire together correctly).
 */
import http from "node:http";
import { prisma } from "../src/db/client.js";
import * as storage from "../src/db/storage.js";

const ROLE_ID = "orchestrator-test-role";

let failures = 0;
function check(label: string, ok: boolean, detail?: unknown) {
  if (ok) console.log(`PASS: ${label}`);
  else { console.log(`FAIL: ${label}`, detail ?? ""); failures++; }
}

function lastUserText(messages: any[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "user") continue;
    if (typeof m.content === "string") return m.content;
    return "";
  }
  return "";
}

function isToolResultTurn(messages: any[]): { toolUseId: string; content: string } | null {
  const last = messages[messages.length - 1];
  if (last?.role === "user" && Array.isArray(last.content)) {
    const block = last.content.find((b: any) => b.type === "tool_result");
    if (block) return { toolUseId: block.tool_use_id, content: block.content };
  }
  return null;
}

let msgCounter = 0;
function toolUseResponse(model: string, name: string, input: any) {
  const id = `toolu_${msgCounter++}`;
  return {
    id: `msg_${msgCounter}`, type: "message", role: "assistant", model,
    content: [{ type: "tool_use", id, name, input }],
    stop_reason: "tool_use", stop_sequence: null,
    usage: { input_tokens: 50, output_tokens: 20 },
  };
}
function textResponse(model: string, text: string) {
  return {
    id: `msg_${msgCounter++}`, type: "message", role: "assistant", model,
    content: [{ type: "text", text }],
    stop_reason: "end_turn", stop_sequence: null,
    usage: { input_tokens: 50, output_tokens: 20 },
  };
}

const server = http.createServer((req, res) => {
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    const body = JSON.parse(raw);
    const messages = body.messages ?? [];
    const toolResult = isToolResultTurn(messages);
    let response: any;

    if (toolResult) {
      // Second turn: we already got a tool result back -- summarize it in plain text.
      response = textResponse(body.model, `Here's what I found: ${toolResult.content}`);
    } else {
      const userText = lastUserText(messages).toLowerCase();
      if (userText.includes("list") && userText.includes("candidate")) {
        response = toolUseResponse(body.model, "list_candidates", {});
      } else if (userText.includes("remove") && userText.includes("must")) {
        response = toolUseResponse(body.model, "propose_hiring_profile_edit", {
          field: "must_have", action: "remove", value: "5+ years closing enterprise SaaS",
        });
      } else {
        response = textResponse(body.model, "(mock) I don't have a tool for that.");
      }
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(response));
  });
});

async function main() {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as any).port;
  process.env.ANTHROPIC_BASE_URL = `http://127.0.0.1:${port}`;
  process.env.ANTHROPIC_API_KEY = "sk-test-not-real";

  await prisma.activityLog.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.candidateEvaluation.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.canonicalCandidate.deleteMany({ where: { firstSeenJobId: ROLE_ID } });
  await prisma.jobRecruiter.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.jobSection.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.job.deleteMany({ where: { roleId: ROLE_ID } });

  const orchestrator = await import("../src/orchestrator.js");

  await storage.createJob(ROLE_ID, { title: "Orchestrator Test Role", ownerEmail: "nodetest@example.com" });
  await storage.mergeSection(ROLE_ID, "icp", { must_have: ["5+ years closing enterprise SaaS"], nice_to_have: [] });
  await storage.mergeCandidate(ROLE_ID, "orch-cand-1", { name: "Taylor Kim", current_company: "Initech", current_title: "AE" });

  // ── 1. a tool call that reads real data (list_candidates) ──
  const turn1 = await orchestrator.runChatTurn(ROLE_ID, "Please list the candidates for this role.", []);
  check("runChatTurn drives a real tool_use round-trip through the Anthropic SDK's tool loop",
    turn1.reply.includes("Taylor Kim"), turn1.reply);
  check("history now contains at least 3 turns (user, assistant tool_use, tool_result, assistant text)",
    turn1.history.length >= 4, turn1.history.length);
  check("no pending_proposal for a non-proposal tool call", turn1.pending_proposal === null);

  // ── 2. a tool call that produces a proposal (propose_hiring_profile_edit) ──
  const turn2 = await orchestrator.runChatTurn(
    ROLE_ID, "Please remove the must-have about 5+ years closing enterprise SaaS.", turn1.history
  );
  check("pending_proposal is extracted from propose_hiring_profile_edit's tool result",
    turn2.pending_proposal?.field === "must_have" && turn2.pending_proposal?.action === "remove", turn2.pending_proposal);
  check("pending_proposal carries role_id", turn2.pending_proposal?.role_id === ROLE_ID);

  const icpBefore = await storage.requireSection(ROLE_ID, "icp");
  check("propose_hiring_profile_edit is read-only -- ICP unchanged until confirmed",
    icpBefore.must_have.includes("5+ years closing enterprise SaaS"));

  // ── 3. the actual deterministic mutation, called only after "confirmation" ──
  const updatedIcp = await orchestrator.applyHiringProfileEdit(ROLE_ID, "must_have", "remove", "5+ years closing enterprise SaaS");
  check("applyHiringProfileEdit removes the value", !updatedIcp.must_have.includes("5+ years closing enterprise SaaS"), updatedIcp.must_have);
  const icpAfter = await storage.requireSection(ROLE_ID, "icp");
  check("the removal persisted to Postgres", !icpAfter.must_have.includes("5+ years closing enterprise SaaS"), icpAfter.must_have);

  // ── 4. exercise the actual HTTP chat routes (not the orchestrator functions directly) ──
  const { buildServer } = await import("../src/server.js");
  const app = buildServer();
  await app.ready();

  const authService = await import("../src/auth/service.js");
  const user = await prisma.user.findUniqueOrThrow({ where: { email: "nodetest@example.com" } });
  const token = await authService.createSession(user.id);
  const cookieHeader = `gtm_session=${token}`;

  const chatResp = await app.inject({
    method: "POST", url: `/jobs/${ROLE_ID}/chat`, headers: { cookie: cookieHeader, "content-type": "application/json" },
    payload: { message: "List the candidates again please." },
  });
  check("POST /jobs/:roleId/chat returns 200 over real HTTP (Fastify inject)", chatResp.statusCode === 200, chatResp.body);
  const chatBody = JSON.parse(chatResp.body);
  check("HTTP chat route reply reflects the real tool result", chatBody.reply.includes("Taylor Kim"), chatBody.reply);

  const getChatResp = await app.inject({ method: "GET", url: `/jobs/${ROLE_ID}/chat`, headers: { cookie: cookieHeader } });
  const getChatBody = JSON.parse(getChatResp.body);
  check("GET /jobs/:roleId/chat returns the persisted, display-collapsed history",
    getChatBody.messages.length > 0 && getChatBody.messages.some((m: any) => m.role === "user"), getChatBody.messages);

  // Confirm route: propose again, then confirm via HTTP.
  await app.inject({
    method: "POST", url: `/jobs/${ROLE_ID}/chat`, headers: { cookie: cookieHeader, "content-type": "application/json" },
    payload: { message: "Please remove the must-have about 5+ years closing enterprise SaaS." },
  });
  // Nothing left to remove now (already removed above), so re-add it first to make the proposal meaningful for this test.
  await storage.mergeSection(ROLE_ID, "icp", { ...icpAfter, must_have: [...icpAfter.must_have, "5+ years closing enterprise SaaS"] });
  const proposeResp = await app.inject({
    method: "POST", url: `/jobs/${ROLE_ID}/chat`, headers: { cookie: cookieHeader, "content-type": "application/json" },
    payload: { message: "Please remove the must-have about 5+ years closing enterprise SaaS." },
  });
  const proposeBody = JSON.parse(proposeResp.body);
  check("HTTP chat route surfaces pending_proposal", proposeBody.pending_proposal?.field === "must_have", proposeBody);

  const confirmResp = await app.inject({
    method: "POST", url: `/jobs/${ROLE_ID}/chat/confirm`, headers: { cookie: cookieHeader, "content-type": "application/json" },
    payload: { approve: true },
  });
  check("POST /jobs/:roleId/chat/confirm applies the proposal over real HTTP", confirmResp.statusCode === 200, confirmResp.body);
  const confirmBody = JSON.parse(confirmResp.body);
  check("confirm route's response reflects the applied ICP", !confirmBody.icp.must_have.includes("5+ years closing enterprise SaaS"), confirmBody.icp);

  await app.close();
  server.close();
  await prisma.session.deleteMany({ where: { token } });
  await prisma.activityLog.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.candidateEvaluation.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.canonicalCandidate.deleteMany({ where: { firstSeenJobId: ROLE_ID } });
  await prisma.jobRecruiter.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.jobSection.deleteMany({ where: { roleId: ROLE_ID } });
  await prisma.job.deleteMany({ where: { roleId: ROLE_ID } });

  console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
  process.exit(failures === 0 ? 0 : 1);
}

main().finally(() => prisma.$disconnect());
