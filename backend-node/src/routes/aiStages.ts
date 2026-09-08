// Port of api.py's AI-triggering routes (lines 813-1039, 1185-1201): every
// LLM-touching stage call, enqueued through taskQueue.ts exactly like
// Python enqueues through task_queue.py rather than running inline.
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { parse as csvParse } from "csv-parse/sync";
import * as storage from "../db/storage.js";
import * as taskQueue from "../taskQueue.js";
import * as intakeStage from "../stages/intake.js";
import * as calibrationStage from "../stages/calibration.js";
import * as icpStage from "../stages/icp.js";
import * as talentMapStage from "../stages/talentMap.js";
import * as searchStrategyStage from "../stages/searchStrategy.js";
import * as interviewQuestionsStage from "../stages/interviewQuestions.js";
import * as candidateAnalysisStage from "../stages/candidateAnalysis.js";
import * as prioritizationStage from "../stages/prioritization.js";
import * as screeningStage from "../stages/screening.js";
import * as outreachStage from "../stages/outreach.js";
import * as conversationSummaryStage from "../stages/conversationSummary.js";
import * as resumeExtraction from "../resumeExtraction.js";
import * as fileStorage from "../fileStorage.js";
import { logAction, runStage } from "../lib/routeHelpers.js";

// ── task runners, registered once at module load (mirrors api.py's
// module-level `for _kind, _fn in [...]: task_queue.register_runner`) ──

taskQueue.registerRunner("intake", (roleId, args) => intakeStage.run(roleId, args.jd_text));
taskQueue.registerRunner("calibrate", (roleId) => calibrationStage.run(roleId));
taskQueue.registerRunner("icp", (roleId) => icpStage.run(roleId));
taskQueue.registerRunner("talent_map", (roleId) => talentMapStage.run(roleId));
taskQueue.registerRunner("search_strategy", (roleId) => searchStrategyStage.run(roleId));
taskQueue.registerRunner("interview_questions", (roleId) => interviewQuestionsStage.run(roleId));
taskQueue.registerRunner("add_candidate", (roleId, args) =>
  candidateAnalysisStage.run(roleId, args.source_text, args.role_family, {
    sourceUrl: args.source_url, resumeFileKey: args.resume_file_key, resumeFilename: args.resume_filename,
  })
);
taskQueue.registerRunner("prioritize", (roleId, args) => prioritizationStage.run(roleId, args.candidate_id));
taskQueue.registerRunner("screen", (roleId, args) => screeningStage.run(roleId, args.candidate_id));
taskQueue.registerRunner("outreach", (roleId, args) => outreachStage.run(roleId, args.candidate_id));
taskQueue.registerRunner("conversation_summary", (roleId, args) => conversationSummaryStage.run(roleId, args.candidate_id));
taskQueue.registerRunner("conversation_intelligence", (roleId, args) => conversationSummaryStage.runIntelligence(roleId, args.candidate_id));

const IntakeRequest = z.object({ jd_text: z.string() });
const CandidateAddRequest = z.object({ source_text: z.string(), role_family: z.string(), source_url: z.string().default("") });
const CommunicationLogRequest = z.object({
  channel: z.enum(["email", "whatsapp", "call", "note"]),
  direction: z.enum(["outbound", "inbound"]).default("outbound"),
  content: z.string().default(""),
  transcript: z.string().nullable().optional(),
  contact_used: z.string().default(""),
});

async function requireJobExists(roleId: string, reply: any): Promise<boolean> {
  if (!(await storage.jobExists(roleId))) {
    reply.code(404).send({ detail: `job '${roleId}' not found` });
    return false;
  }
  return true;
}

export async function registerAiStageRoutes(app: FastifyInstance) {
  app.post("/jobs/:roleId/intake", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    const body = IntakeRequest.parse(request.body);
    await logAction(request, roleId, "requested JD intake");
    const task = await taskQueue.enqueue(roleId, "intake", { jd_text: body.jd_text });
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/intake/upload", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    const body = request.body as any;
    const file = body.file;
    if (!file) {
      reply.code(400).send({ detail: "no file uploaded" });
      return;
    }
    const buffer = await file.toBuffer();
    let text: string;
    try {
      text = await resumeExtraction.extractText(file.filename ?? "", buffer);
    } catch (e: any) {
      reply.code(400).send({ detail: e.message });
      return;
    }
    if (!text.trim()) {
      reply.code(400).send({ detail: "couldn't extract any text from that file" });
      return;
    }
    await logAction(request, roleId, "uploaded JD file", { detail: file.filename ?? "" });
    reply.send({ text });
  });

  app.post("/jobs/:roleId/calibrate", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    await logAction(request, roleId, "requested calibration");
    const task = await taskQueue.enqueue(roleId, "calibrate", {});
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/icp", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    await logAction(request, roleId, "requested ICP build");
    const task = await taskQueue.enqueue(roleId, "icp", {});
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/talent-map", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    await logAction(request, roleId, "requested talent map");
    const task = await taskQueue.enqueue(roleId, "talent_map", {});
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/search-strategy", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    await logAction(request, roleId, "requested search strategy");
    const task = await taskQueue.enqueue(roleId, "search_strategy", {});
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/interview-questions", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    await logAction(request, roleId, "requested interview questions");
    const task = await taskQueue.enqueue(roleId, "interview_questions", {});
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/candidates", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    const body = CandidateAddRequest.parse(request.body);
    await logAction(request, roleId, "added candidate (pasted text)");
    const task = await taskQueue.enqueue(roleId, "add_candidate", {
      source_text: body.source_text, role_family: body.role_family, source_url: body.source_url,
    });
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/candidates/upload", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    const body = request.body as any;
    const file = body.file;
    const roleFamily = body.role_family?.value;
    const sourceUrl = body.source_url?.value ?? "";
    if (!file || !roleFamily) {
      reply.code(400).send({ detail: "file and role_family are required" });
      return;
    }
    const buffer = await file.toBuffer();
    let text: string;
    try {
      text = await resumeExtraction.extractText(file.filename ?? "", buffer);
    } catch (e: any) {
      reply.code(400).send({ detail: e.message });
      return;
    }
    if (!text.trim()) {
      reply.code(400).send({ detail: "couldn't extract any text from that file" });
      return;
    }
    // Best-effort: persist the original file alongside the extracted
    // text. Returns null (silently) when object storage isn't
    // configured in this environment -- the upload still succeeds
    // either way, since extraction never depended on this landing
    // anywhere.
    const resumeFileKey = await fileStorage.uploadResume(
      roleId, file.filename ?? "resume", buffer, file.mimetype ?? "application/octet-stream"
    );
    await logAction(request, roleId, "added candidate (resume upload)", { detail: file.filename ?? "" });
    const task = await taskQueue.enqueue(roleId, "add_candidate", {
      source_text: text, role_family: roleFamily, source_url: sourceUrl,
      resume_file_key: resumeFileKey, resume_filename: file.filename ?? null,
    });
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/candidates/bulk-import", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    const body = request.body as any;
    const file = body.file;
    const roleFamily = body.role_family?.value;
    if (!file || !roleFamily) {
      reply.code(400).send({ detail: "file and role_family are required" });
      return;
    }
    const buffer = await file.toBuffer();
    let text: string;
    try {
      text = buffer.toString("utf-8");
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1); // strip BOM, matches Python's utf-8-sig
    } catch {
      reply.code(400).send({ detail: "couldn't read that file as UTF-8 text — export the CSV as UTF-8 and try again" });
      return;
    }

    let rows: Record<string, string>[];
    try {
      rows = csvParse(text, { columns: true, skip_empty_lines: true });
    } catch {
      reply.code(400).send({ detail: "that CSV has no header row" });
      return;
    }
    if (!rows.length && !text.trim()) {
      reply.code(400).send({ detail: "that CSV has no header row" });
      return;
    }
    const fieldNames = rows.length ? Object.keys(rows[0]!) : [];
    const notesCol = fieldNames.find((c) => ["notes", "source_text", "resume", "text"].includes(c.trim().toLowerCase()));
    if (!notesCol) {
      reply.code(400).send({ detail: "CSV needs a 'notes' column with each candidate's resume/notes text" });
      return;
    }
    const urlCol = fieldNames.find((c) => ["source_url", "url", "link"].includes(c.trim().toLowerCase()));

    const taskIds: string[] = [];
    let skipped = 0;
    for (const row of rows) {
      const sourceText = (row[notesCol] ?? "").trim();
      if (!sourceText) { skipped++; continue; }
      const sourceUrl = urlCol ? (row[urlCol] ?? "").trim() : "";
      const task = await taskQueue.enqueue(roleId, "add_candidate", {
        source_text: sourceText, role_family: roleFamily, source_url: sourceUrl,
      });
      taskIds.push(task.task_id);
    }
    await logAction(request, roleId, "bulk-imported candidates (CSV)", { detail: `${taskIds.length} queued, ${skipped} skipped` });
    reply.code(202).send({ task_ids: taskIds, queued: taskIds.length, skipped_empty_rows: skipped });
  });

  app.post("/jobs/:roleId/candidates/:candidateId/prioritize", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    await logAction(request, roleId, "requested prioritization", { candidateId });
    const task = await taskQueue.enqueue(roleId, "prioritize", { candidate_id: candidateId });
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/candidates/:candidateId/screen", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    await logAction(request, roleId, "requested screening", { candidateId });
    const task = await taskQueue.enqueue(roleId, "screen", { candidate_id: candidateId });
    reply.code(202).send(task);
  });

  app.post("/jobs/:roleId/candidates/:candidateId/outreach", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    await logAction(request, roleId, "requested outreach draft", { candidateId });
    const task = await taskQueue.enqueue(roleId, "outreach", { candidate_id: candidateId });
    reply.code(202).send(task);
  });

  app.get("/jobs/:roleId/candidates/:candidateId/communications", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    if (!(await requireJobExists(roleId, reply))) return;
    const entries = await runStage(() => storage.listCommunications(roleId, candidateId));
    const summary = await runStage(() => storage.getConversationSummary(roleId, candidateId));
    const state = await storage.loadRole(roleId);
    const candidate = (state.candidates ?? {})[candidateId] ?? {};
    reply.send({ entries, intelligence: candidate.conversation_intelligence ?? null, ...summary });
  });

  app.post("/jobs/:roleId/candidates/:candidateId/communications", async (request, reply) => {
    const { roleId, candidateId } = request.params as { roleId: string; candidateId: string };
    const body = CommunicationLogRequest.parse(request.body);
    const loggedBy = (request as any).user.email;
    const entry = await runStage(() =>
      storage.logCommunication(roleId, candidateId, {
        channel: body.channel, direction: body.direction, content: body.content,
        transcript: body.transcript ?? null, contactUsed: body.contact_used, loggedBy,
      })
    );
    await logAction(request, roleId, `logged ${body.channel} communication`, { candidateId });
    const summaryTask = await taskQueue.enqueue(roleId, "conversation_summary", { candidate_id: candidateId });
    const intelligenceTask = await taskQueue.enqueue(roleId, "conversation_intelligence", { candidate_id: candidateId });
    reply.code(202).send({ entry, summary_task: summaryTask, intelligence_task: intelligenceTask });
  });
}
