// Port of api.py's AI chat / Copilot routes (lines 1507-1531, 1534-1586).
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import * as storage from "../db/storage.js";
import * as orchestrator from "../orchestrator.js";
import { logAction, runStage } from "../lib/routeHelpers.js";

const ChatRequest = z.object({ message: z.string() });
const ChatConfirmRequest = z.object({ approve: z.boolean() });

// Collapse the raw tool-use transcript into something renderable:
// user/assistant text turns, with tool calls noted inline rather than
// shown as raw JSON. Tool-result turns (role="user" carrying tool_result
// blocks) are internal plumbing and are skipped.
function displayMessages(history: any[]): { role: string; text: string }[] {
  const display: { role: string; text: string }[] = [];
  for (const msg of history) {
    const content = msg.content;
    if (typeof content === "string") {
      display.push({ role: msg.role, text: content });
      continue;
    }
    if (!Array.isArray(content)) continue;
    if (content.some((block: any) => block?.type === "tool_result")) continue;
    const textParts = content.filter((b: any) => b?.type === "text").map((b: any) => b.text ?? "");
    const toolNotes = content.filter((b: any) => b?.type === "tool_use").map((b: any) => `[used ${b.name}]`);
    let text = textParts.filter(Boolean).join(" ");
    if (toolNotes.length && !text) text = toolNotes.join(" ");
    if (text) display.push({ role: msg.role, text });
  }
  return display;
}

export async function registerChatRoutes(app: FastifyInstance) {
  app.get("/jobs/:roleId/chat", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const state = await storage.loadRole(roleId);
    reply.send({
      messages: displayMessages(state.chat_history ?? []),
      pending_proposal: state.chat_pending ?? null,
    });
  });

  app.post("/jobs/:roleId/chat", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const body = ChatRequest.parse(request.body);
    const state = await storage.loadRole(roleId);
    const history = state.chat_history ?? [];

    const result = await runStage(() => orchestrator.runChatTurn(roleId, body.message, history));

    await storage.mergeSection(roleId, "chat_history", result.history);
    await storage.mergeSection(roleId, "chat_pending", result.pending_proposal);
    reply.send({ reply: result.reply, pending_proposal: result.pending_proposal });
  });

  app.post("/jobs/:roleId/chat/confirm", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const body = ChatConfirmRequest.parse(request.body);
    const state = await storage.loadRole(roleId);
    const pending = state.chat_pending;
    if (!pending) {
      reply.code(400).send({ detail: "no pending proposal for this job" });
      return;
    }

    let icp: any;
    let note: string;
    if (body.approve) {
      icp = await runStage(() =>
        orchestrator.applyHiringProfileEdit(roleId, pending.field, pending.action, pending.value)
      );
      note = `Applied: ${pending.description}`;
    } else {
      icp = state.icp ?? null;
      note = `Declined: ${pending.description}`;
    }

    await storage.mergeSection(roleId, "chat_pending", null);
    const history = state.chat_history ?? [];
    history.push({ role: "assistant", content: [{ type: "text", text: note }] });
    await storage.mergeSection(roleId, "chat_history", history);
    await logAction(request, roleId, `AI chat proposal ${body.approve ? "applied" : "declined"}`, {
      detail: pending.description,
    });

    reply.send({ applied: body.approve, message: note, icp });
  });
}
