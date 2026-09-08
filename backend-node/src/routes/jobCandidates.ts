// Port of api.py's deterministic per-job candidate routes (subset of
// lines 1094-1322: list, export, share, mark-sent, decision, placement,
// note, contact, attach-existing). AI-triggering candidate routes
// (add/upload/bulk-import/prioritize/screen/outreach draft) and the
// SMTP-send/resume-download/communications routes are deferred to
// Phase 5-7 -- see docs/migration.md.
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import * as storage from "../db/storage.js";
import * as outreachStage from "../stages/outreach.js";
import * as prioritizationStage from "../stages/prioritization.js";
import * as notifications from "../notifications.js";
import * as fileStorage from "../fileStorage.js";
import { logAction, maybeFireDecisionWebhook, runStage } from "../lib/routeHelpers.js";

const AttachExistingCandidateRequest = z.object({ canonical_candidate_id: z.string() });
const CandidateShareRequest = z.object({ visible: z.boolean() });
const RecruiterDecisionRequest = z.object({ decision: z.string() });
const PlacementRequest = z.object({ placed: z.boolean(), fee: z.number().default(0.0) });
const CandidateNoteRequest = z.object({ note: z.string().default("") });
const CandidateContactRequest = z.object({
  phone: z.string().nullable().optional(),
  email: z.string().nullable().optional(),
});

function csvField(value: string): string {
  if (/[",\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

export async function registerJobCandidateRoutes(app: FastifyInstance) {
  app.post("/jobs/:roleId/candidates/attach-existing", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = AttachExistingCandidateRequest.parse(request.body);
    const result = await runStage(() => storage.attachExistingCandidate(roleId, body.canonical_candidate_id));
    await logAction(request, roleId, "added candidate (from existing profile)", { detail: body.canonical_candidate_id });
    reply.send(result);
  });

  app.get("/jobs/:roleId/candidates", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const state = await storage.loadRole(roleId);
    const candidates = state.candidates ?? {};
    const prioritizations = state.prioritizations ?? {};
    reply.send(
      Object.entries(candidates).map(([cid, c]: [string, any]) => ({
        ...c, candidate_id: cid, prioritization: prioritizations[cid] ?? null,
      }))
    );
  });

  app.get("/jobs/:roleId/candidates/export.csv", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const state = await storage.loadRole(roleId);
    const candidates = state.candidates ?? {};
    const prioritizations = state.prioritizations ?? {};
    const funnel = state.funnel ?? {};
    const outreach = state.outreach ?? {};

    const rows = [
      ["Name", "Current title", "Current company", "Tier", "Recruiter decision", "Pipeline stage", "Outreach drafted", "Source URL"],
    ];
    for (const [cid, c] of Object.entries<any>(candidates)) {
      const p = prioritizations[cid] ?? {};
      rows.push([
        c.name ?? "", c.current_title ?? "", c.current_company ?? "",
        p.tier ?? "", p.recruiter_decision ?? "",
        funnel[cid]?.current_stage ?? "IDENTIFIED",
        cid in outreach ? "yes" : "no",
        c.source_url ?? "",
      ]);
    }
    const csv = rows.map((row) => row.map(csvField).join(",")).join("\r\n") + "\r\n";
    reply
      .header("content-type", "text/csv")
      .header("content-disposition", `attachment; filename="${roleId}-candidates.csv"`)
      .send(csv);
  });

  app.get("/jobs/:roleId/candidates/export.json", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const state = await storage.loadRole(roleId);
    const candidates = state.candidates ?? {};
    const prioritizations = state.prioritizations ?? {};
    const funnel = state.funnel ?? {};
    const outreach = state.outreach ?? {};
    reply.send({
      role_id: roleId,
      candidates: Object.entries(candidates).map(([cid, c]: [string, any]) => ({
        ...c, candidate_id: cid, prioritization: prioritizations[cid] ?? null,
        pipeline_stage: funnel[cid]?.current_stage ?? "IDENTIFIED",
        stage_history: funnel[cid]?.stage_history ?? [],
        outreach_drafted: cid in outreach,
      })),
    });
  });

  app.patch("/jobs/:roleId/candidates/:candidateId/share", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const body = CandidateShareRequest.parse(request.body);
    const result = await runStage(() => storage.setCandidateClientVisible(roleId, candidateId, body.visible));
    await logAction(request, roleId, body.visible ? "shared candidate with client" : "unshared candidate from client", { candidateId });
    reply.send(result);
  });

  app.post("/jobs/:roleId/candidates/:candidateId/outreach/mark-sent", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const result = await runStage(() => outreachStage.markSent(roleId, candidateId));
    await logAction(request, roleId, "marked outreach sent", { candidateId });
    reply.send(result);
  });

  app.post("/jobs/:roleId/candidates/:candidateId/decision", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const body = RecruiterDecisionRequest.parse(request.body);
    const result = await runStage(() => prioritizationStage.setRecruiterDecision(roleId, candidateId, body.decision));
    await logAction(request, roleId, `set decision: ${body.decision}`, { candidateId });
    await maybeFireDecisionWebhook(roleId, candidateId, body.decision);
    reply.send(result);
  });

  app.post("/jobs/:roleId/candidates/:candidateId/placement", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const body = PlacementRequest.parse(request.body);
    const result = await runStage(() => prioritizationStage.setPlacement(roleId, candidateId, body.placed, body.fee));
    await logAction(request, roleId, body.placed ? "marked candidate placed" : "cleared placement", {
      detail: body.placed ? `fee=${body.fee}` : "", candidateId,
    });
    reply.send(result);
  });

  app.patch("/jobs/:roleId/candidates/:candidateId/note", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const body = CandidateNoteRequest.parse(request.body);
    const result = await runStage(() => storage.setCandidateNote(roleId, candidateId, body.note));
    await logAction(request, roleId, "edited candidate note", { candidateId });
    reply.send(result);
  });

  app.patch("/jobs/:roleId/candidates/:candidateId/contact", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const body = CandidateContactRequest.parse(request.body);
    const result = await runStage(() =>
      storage.setCandidateContact(roleId, candidateId, { phone: body.phone ?? null, email: body.email ?? null })
    );
    await logAction(request, roleId, "updated candidate contact info", { candidateId });
    reply.send(result);
  });

  app.get("/jobs/:roleId/candidates/:candidateId/resume", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const state = await storage.loadRole(roleId);
    const candidate = (state.candidates ?? {})[candidateId];
    if (candidate === undefined) {
      reply.code(404).send({ detail: `candidate '${candidateId}' not found for role '${roleId}'` });
      return;
    }
    const fileKey = candidate.resume_file_key;
    if (!fileKey) {
      reply.code(404).send({ detail: "no resume file stored for this candidate" });
      return;
    }
    const url = await fileStorage.getResumeDownloadUrl(fileKey);
    if (url === null) {
      reply.code(503).send({ detail: "resume storage isn't available right now" });
      return;
    }
    reply.send({ url, filename: candidate.resume_filename });
  });

  app.post("/jobs/:roleId/candidates/:candidateId/outreach/send", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const state = await storage.loadRole(roleId);
    const candidate = (state.candidates ?? {})[candidateId];
    if (candidate === undefined) {
      reply.code(404).send({ detail: `candidate '${candidateId}' not found for role '${roleId}'` });
      return;
    }
    const email = candidate.email;
    if (!email) {
      reply.code(400).send({ detail: "no email on file for this candidate — add one first (PATCH .../contact)" });
      return;
    }
    const draft = (state.outreach ?? {})[candidateId];
    if (draft === undefined) {
      reply.code(400).send({ detail: "no outreach draft yet for this candidate — draft one first" });
      return;
    }
    const body: string = draft.email ?? "";
    if (!body.trim()) {
      reply.code(400).send({ detail: "the outreach draft has no email body to send" });
      return;
    }
    if (!notifications.isConfigured()) {
      reply.code(503).send({ detail: "outbound email isn't configured on this server (see SMTP_* env vars) — nothing was sent" });
      return;
    }
    const jobs = await storage.listJobs();
    const roleTitle = jobs.find((j) => j.role_id === roleId)?.title ?? roleId;
    const sent = await notifications.sendEmail([email], `Regarding the ${roleTitle} opportunity`, body);
    if (!sent) {
      reply.code(502).send({ detail: "sending the email failed — see server logs" });
      return;
    }
    const recruiterEmail = (request as any).user.email;
    await storage.logCommunication(roleId, candidateId, {
      channel: "email", direction: "outbound", content: body,
      contactUsed: email, loggedBy: recruiterEmail, followupStage: 0,
    });
    const result = await runStage(() => outreachStage.markSent(roleId, candidateId));
    await logAction(request, roleId, "sent outreach email", { candidateId });
    reply.send({ ...result, sent_to: email });
  });

  app.post("/jobs/:roleId/candidates/:candidateId/outreach/followup/send", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const due = await storage.dueFollowups();
    const entry = due.find((d: any) => d.role_id === roleId && d.candidate_id === candidateId);
    if (!entry) {
      reply.code(400).send({ detail: "no follow-up is due for this candidate right now" });
      return;
    }
    if (!notifications.isConfigured()) {
      reply.code(503).send({ detail: "outbound email isn't configured on this server (see SMTP_* env vars) — nothing was sent" });
      return;
    }
    const sent = await notifications.sendEmail([entry.email], `Following up: ${entry.role_title}`, entry.draft_message);
    if (!sent) {
      reply.code(502).send({ detail: "sending the follow-up failed — see server logs" });
      return;
    }
    await storage.logCommunication(roleId, candidateId, {
      channel: "email", direction: "outbound", content: entry.draft_message,
      contactUsed: entry.email, loggedBy: (request as any).user.email, followupStage: entry.followup_stage,
    });
    await logAction(request, roleId, `sent follow-up #${entry.followup_stage}`, { candidateId });
    reply.send({ sent_to: entry.email, followup_stage: entry.followup_stage });
  });
}
