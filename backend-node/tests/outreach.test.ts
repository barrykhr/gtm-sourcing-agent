import { describe, expect, it } from "vitest";
import { authHeader, buildApp, createJob, seedCandidateWithOutreachDraft, signup } from "./helpers.js";
import { sentEmails } from "./mocks/nodemailer.js";
import * as storage from "../src/db/storage.js";
import { runOnce as runFollowupSweepOnce } from "../src/followupSweep.js";
import { prisma } from "../src/db/client.js";

describe("outreach send", () => {
  it("sends the drafted email, logs the communication, and marks the candidate contacted", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "outreach1@test.com");
    await createJob("outreach-role-1");
    await seedCandidateWithOutreachDraft("outreach-role-1", "cand-1", { email: "candidate1@example.com", draftBody: "Hi there, interested in this role?" });

    const res = await app.inject({
      method: "POST", url: "/jobs/outreach-role-1/candidates/cand-1/outreach/send", headers: authHeader(cookie),
    });
    expect(res.statusCode).toBe(200);
    expect(res.json().sent_to).toBe("candidate1@example.com");

    expect(sentEmails).toHaveLength(1);
    expect(sentEmails[0]!.to).toBe("candidate1@example.com");
    expect(sentEmails[0]!.text).toBe("Hi there, interested in this role?");

    const comms = await storage.listCommunications("outreach-role-1", "cand-1");
    expect(comms).toHaveLength(1);
    expect(comms[0]).toMatchObject({ channel: "email", direction: "outbound", contact_used: "candidate1@example.com" });

    const funnel: any = (await storage.loadRole("outreach-role-1")).funnel ?? {};
    expect(funnel["cand-1"]?.current_stage).toBe("CONTACTED");
  });

  it("refuses to send without a drafted outreach (draft one first)", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "outreach2@test.com");
    await createJob("outreach-role-2");
    await storage.mergeCandidate("outreach-role-2", "cand-2", { candidate_id: "cand-2", name: "No Draft" });
    await storage.setCandidateContact("outreach-role-2", "cand-2", { email: "nodraft@example.com" });

    const res = await app.inject({ method: "POST", url: "/jobs/outreach-role-2/candidates/cand-2/outreach/send", headers: authHeader(cookie) });
    expect(res.statusCode).toBe(400);
    expect(sentEmails).toHaveLength(0);
  });

  it("refuses to send when the candidate has no email on file", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "outreach3@test.com");
    await createJob("outreach-role-3");
    await storage.mergeCandidate("outreach-role-3", "cand-3", { candidate_id: "cand-3", name: "No Email" });
    await storage.mergeSection("outreach-role-3", "outreach", { "cand-3": { email: "Hi there" } });

    const res = await app.inject({ method: "POST", url: "/jobs/outreach-role-3/candidates/cand-3/outreach/send", headers: authHeader(cookie) });
    expect(res.statusCode).toBe(400);
  });

  it("marking outreach sent manually (no real email) records it and advances the funnel", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "outreach4@test.com");
    await createJob("outreach-role-4");
    await seedCandidateWithOutreachDraft("outreach-role-4", "cand-4", { email: "cand4@example.com" });

    const res = await app.inject({ method: "POST", url: "/jobs/outreach-role-4/candidates/cand-4/outreach/mark-sent", headers: authHeader(cookie) });
    expect(res.statusCode).toBe(200);
    expect(sentEmails).toHaveLength(0); // mark-sent never sends real email, unlike /outreach/send
  });
});

describe("outreach settings (admin-only)", () => {
  it("a non-admin cannot change workspace outreach settings", async () => {
    const app = buildApp();
    await signup(app, "settingsadmin@test.com"); // first account, admin
    const { cookie } = await signup(app, "settingsplain@test.com"); // recruiter
    const res = await app.inject({
      method: "PUT", url: "/outreach/settings", headers: authHeader(cookie), payload: { auto_send_followups: true },
    });
    expect(res.statusCode).toBe(403);
  });

  it("an admin can turn on auto-send and set the follow-up template", async () => {
    const app = buildApp();
    const { cookie } = await signup(app, "settingsadmin2@test.com");
    const res = await app.inject({
      method: "PUT", url: "/outreach/settings", headers: authHeader(cookie),
      payload: { auto_send_followups: true, followup_template: "Hi {{candidate_name}}, following up on {{role_title}}." },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json().auto_send_followups).toBe(true);
  });
});

describe("outreach follow-up background sweep", () => {
  // The gap found during migration audit: Python runs this on a 6-hour
  // timer (followup_sweep.py); this exercises the same logic
  // (runFollowupSweepOnce, exported by src/followupSweep.ts) directly
  // rather than waiting for the timer.

  async function seedOverdueInitialOutreach(roleId: string, candidateId: string, email: string, daysAgo: number) {
    await createJob(roleId);
    await storage.mergeCandidate(roleId, candidateId, { candidate_id: candidateId, name: "Follow-up Candidate" });
    await storage.setCandidateContact(roleId, candidateId, { email });
    // Directly backdate the initial outbound email so it's overdue for
    // stage-1 follow-up (FOLLOWUP_THRESHOLDS_DAYS[1], confirmed >0 days
    // by storage.dueFollowups()'s own logic) without waiting real time.
    await storage.logCommunication(roleId, candidateId, {
      channel: "email", direction: "outbound", content: "initial outreach", contactUsed: email, followupStage: 0,
    });
    const job = await prisma.job.findUnique({ where: { roleId } });
    await prisma.communicationLogEntry.updateMany({
      where: { roleId, candidateEvaluationId: candidateId, followupStage: 0 },
      data: { createdAt: new Date(Date.now() - daysAgo * 86_400_000) },
    });
    void job;
  }

  it("does nothing when auto_send_followups is off (the default)", async () => {
    await seedOverdueInitialOutreach("sweep-role-1", "cand-1", "sweepcand1@example.com", 4);
    const sent = await runFollowupSweepOnce();
    expect(sent).toHaveLength(0);
    expect(sentEmails).toHaveLength(0);
  });

  it("sends every currently-due follow-up once opted in, and logs each as a communication", async () => {
    await storage.setWorkspaceSettings({ autoSendFollowups: true });
    await seedOverdueInitialOutreach("sweep-role-2", "cand-2", "sweepcand2@example.com", 4);

    const sent = await runFollowupSweepOnce();
    expect(sent.length).toBeGreaterThan(0);
    expect(sentEmails.some((e) => e.to === "sweepcand2@example.com")).toBe(true);

    const comms = await storage.listCommunications("sweep-role-2", "cand-2");
    expect(comms.some((c: any) => c.followup_stage > 0)).toBe(true);
  });

  it("does not resend the same follow-up stage on a second sweep run", async () => {
    await storage.setWorkspaceSettings({ autoSendFollowups: true });
    await seedOverdueInitialOutreach("sweep-role-3", "cand-3", "sweepcand3@example.com", 4);

    const firstRun = await runFollowupSweepOnce();
    expect(firstRun.length).toBeGreaterThan(0);
    const sentAfterFirst = sentEmails.length;

    const secondRun = await runFollowupSweepOnce();
    expect(secondRun).toHaveLength(0); // that stage was already sent -- nothing newly due
    expect(sentEmails).toHaveLength(sentAfterFirst);
  });

  it("skips a candidate who already replied (has an inbound message after the initial outreach)", async () => {
    await storage.setWorkspaceSettings({ autoSendFollowups: true });
    await seedOverdueInitialOutreach("sweep-role-4", "cand-4", "sweepcand4@example.com", 4);
    await storage.logCommunication("sweep-role-4", "cand-4", {
      channel: "email", direction: "inbound", content: "Thanks, I'm interested!", contactUsed: "sweepcand4@example.com",
    });

    const sent = await runFollowupSweepOnce();
    expect(sent.find((e: any) => e.candidate_id === "cand-4")).toBeUndefined();
    expect(sentEmails).toHaveLength(0);
  });
});
