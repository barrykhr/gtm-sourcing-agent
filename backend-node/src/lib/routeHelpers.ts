// Shared helpers used across route modules -- ports of api.py's
// module-level helpers (_slugify, _job_summary, _log,
// _maybe_fire_decision_webhook) so every route file doesn't reinvent
// them.
import type { FastifyRequest } from "fastify";
import * as storage from "../db/storage.js";
import * as pipeline from "../pipeline.js";
import { sendWebhook } from "../webhooks.js";

export function slugify(text: string): string {
  const normalized = text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "job";
}

export async function jobSummary(roleId: string) {
  return {
    role_id: roleId,
    status: await pipeline.status(roleId),
    next_stage: await pipeline.nextStage(roleId),
  };
}

export function currentUserEmail(request: FastifyRequest): string {
  return (request as any).user?.email ?? "";
}

export async function logAction(
  request: FastifyRequest, roleId: string, action: string,
  args: { detail?: string; candidateId?: string | null } = {}
) {
  try {
    await storage.logActivity(roleId, currentUserEmail(request), action, args);
  } catch {
    request.log.error({ roleId, action }, "activity logging failed");
  }
}

// Maps a StorageError the same way api.py's _run_stage maps a ValueError
// (400) -- callers await the storage/stage call directly and let Fastify's
// error handler (server.ts) do this translation via the thrown error's
// `statusCode`, which storage.StorageError does not set by default. This
// helper sets it so the generic handler routes it to 400 instead of 500.
export async function runStage<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e: any) {
    if (e?.constructor?.name === "StorageError" && e.statusCode === undefined) {
      e.statusCode = 400;
    }
    throw e;
  }
}

export async function maybeFireDecisionWebhook(roleId: string, candidateId: string, decision: string) {
  if (decision !== "pursue") return;
  try {
    const state = await storage.loadRole(roleId);
    const webhookUrl = (state.integrations ?? {}).webhook_url;
    if (!webhookUrl) return;
    const candidate = (state.candidates ?? {})[candidateId] ?? {};
    const result = await sendWebhook(webhookUrl, "candidate.decision.pursue", {
      role_id: roleId, candidate_id: candidateId, candidate_name: candidate.name ?? "",
    });
    await storage.logActivity(
      roleId, "system", result.ok ? "webhook delivery" : "webhook delivery failed",
      { detail: result.detail, candidateId }
    );
  } catch {
    // best-effort, matches Python's bare except
  }
}
