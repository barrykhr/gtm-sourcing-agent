// Per orchestrator.ts's own testing note: there's no way to check
// *tool-selection quality* without real inference, so every scenario
// here scripts exactly what the "model" says (see tests/mocks/anthropic.ts)
// -- what's actually under test is real tool execution, confirmation
// gating, and chat-history persistence, against the real database.
import { describe, expect, it } from "vitest";
import { authHeader, buildApp, createJob, seedIcp, signup } from "./helpers.js";
import { anthropicMock } from "./mocks/anthropic.js";
import * as storage from "../src/db/storage.js";

describe("Copilot chat", () => {
  it("answers a question by calling a real tool (list_candidates) against real data", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "copilot1@test.com");
    await createJob("copilot-role-1");
    await seedIcp("copilot-role-1");
    await storage.mergeCandidate("copilot-role-1", "cand-1", { candidate_id: "cand-1", name: "Priya Sharma", current_title: "Staff Engineer" });

    anthropicMock.chatScript = [
      { content: [{ type: "tool_use", id: "toolu_1", name: "list_candidates", input: {} }] },
      { content: [{ type: "text", text: "You have 1 candidate so far: Priya Sharma." }] },
    ];

    const res = await app.inject({
      method: "POST", url: "/jobs/copilot-role-1/chat", headers: authHeader(cookie), payload: { message: "who have we got so far?" },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json().reply).toBe("You have 1 candidate so far: Priya Sharma.");
    expect(res.json().pending_proposal).toBeNull();

    // Verify the transcript was actually persisted, not just returned.
    const history = await app.inject({ method: "GET", url: "/jobs/copilot-role-1/chat", headers: authHeader(cookie) });
    const messages = history.json().messages;
    expect(messages.at(-1)).toEqual({ role: "assistant", text: "You have 1 candidate so far: Priya Sharma." });
    expect(messages.some((m: any) => m.role === "user" && m.text === "who have we got so far?")).toBe(true);
  });

  it("a hiring-profile edit request produces a pending proposal without mutating the ICP", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "copilot2@test.com");
    await createJob("copilot-role-2");
    await seedIcp("copilot-role-2"); // must_have: ["5+ years experience"]

    anthropicMock.chatScript = [
      {
        content: [{
          type: "tool_use", id: "toolu_2", name: "propose_hiring_profile_edit",
          input: { field: "must_have", action: "add", value: "Kubernetes" },
        }],
      },
      { content: [{ type: "text", text: "I've prepared that change for your approval." }] },
    ];

    const res = await app.inject({
      method: "POST", url: "/jobs/copilot-role-2/chat", headers: authHeader(cookie),
      payload: { message: "add Kubernetes as a must-have" },
    });
    expect(res.statusCode).toBe(200);
    const proposal = res.json().pending_proposal;
    expect(proposal).toMatchObject({ field: "must_have", action: "add", value: "Kubernetes" });

    const icpAfterProposal: any = await storage.requireSection("copilot-role-2", "icp");
    expect(icpAfterProposal.must_have).not.toContain("Kubernetes"); // proposing never mutates
  });

  it("confirming a pending proposal (approve) actually applies it to the ICP", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "copilot3@test.com");
    await createJob("copilot-role-3");
    await seedIcp("copilot-role-3");

    anthropicMock.chatScript = [
      { content: [{ type: "tool_use", id: "toolu_3", name: "propose_hiring_profile_edit", input: { field: "must_have", action: "add", value: "Kubernetes" } }] },
      { content: [{ type: "text", text: "Ready for your approval." }] },
    ];
    await app.inject({ method: "POST", url: "/jobs/copilot-role-3/chat", headers: authHeader(cookie), payload: { message: "add Kubernetes" } });

    const confirm = await app.inject({
      method: "POST", url: "/jobs/copilot-role-3/chat/confirm", headers: authHeader(cookie), payload: { approve: true },
    });
    expect(confirm.statusCode).toBe(200);
    expect(confirm.json().applied).toBe(true);
    expect(confirm.json().icp.must_have).toContain("Kubernetes");

    const icpNow: any = await storage.requireSection("copilot-role-3", "icp");
    expect(icpNow.must_have).toContain("Kubernetes");
  });

  it("declining a pending proposal leaves the ICP unchanged and clears the proposal", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "copilot4@test.com");
    await createJob("copilot-role-4");
    await seedIcp("copilot-role-4");

    anthropicMock.chatScript = [
      { content: [{ type: "tool_use", id: "toolu_4", name: "propose_hiring_profile_edit", input: { field: "must_have", action: "add", value: "Kubernetes" } }] },
      { content: [{ type: "text", text: "Ready for your approval." }] },
    ];
    await app.inject({ method: "POST", url: "/jobs/copilot-role-4/chat", headers: authHeader(cookie), payload: { message: "add Kubernetes" } });

    const decline = await app.inject({
      method: "POST", url: "/jobs/copilot-role-4/chat/confirm", headers: authHeader(cookie), payload: { approve: false },
    });
    expect(decline.statusCode).toBe(200);
    expect(decline.json().applied).toBe(false);

    const icpNow: any = await storage.requireSection("copilot-role-4", "icp");
    expect(icpNow.must_have).not.toContain("Kubernetes");

    // no pending proposal left to confirm again
    const again = await app.inject({ method: "POST", url: "/jobs/copilot-role-4/chat/confirm", headers: authHeader(cookie), payload: { approve: true } });
    expect(again.statusCode).toBe(400);
  });

  it("404s for a job that doesn't exist", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "copilot5@test.com");
    const res = await app.inject({ method: "POST", url: "/jobs/no-such-job/chat", headers: authHeader(cookie), payload: { message: "hi" } });
    expect(res.statusCode).toBe(404);
  });
});
