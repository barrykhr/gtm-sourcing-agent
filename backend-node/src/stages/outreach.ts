// Port of stages/outreach.py -- Stage 11: Outreach drafting. Draft only
// -- nothing here sends a message.
import * as storage from "../db/storage.js";
import { StorageError } from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { OutreachSequence } from "../models.js";
import * as funnelStage from "./funnel.js";
import { FUNNEL_STAGE_ORDER } from "./funnel.js";

export async function run(roleId: string, candidateId: string): Promise<OutreachSequence> {
  const jd = await storage.requireSection(roleId, "job_description");
  const candidates = await storage.requireSection(roleId, "candidates");
  if (!(candidateId in candidates)) {
    throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  }

  const prompt = llmClient.renderPrompt("outreach.md", {
    candidate_json: JSON.stringify(candidates[candidateId]), job_description_json: JSON.stringify(jd),
  });
  const result = await llmClient.generate(prompt, OutreachSequence, { stage: "outreach" });
  result.candidate_id = candidateId;

  const state = await storage.loadRole(roleId);
  (state.outreach ??= {})[candidateId] = result;
  await storage.saveRole(roleId, state);
  return result;
}

export async function markSent(roleId: string, candidateId: string) {
  const state = await storage.loadRole(roleId);
  const outreach = state.outreach ?? {};
  if (!(candidateId in outreach)) {
    throw new StorageError(`candidate '${candidateId}' has no outreach draft yet for role '${roleId}'`);
  }

  const sentAt = new Date().toISOString();
  (state.outreach_log ??= {})[candidateId] = { sent_at: sentAt };
  await storage.saveRole(roleId, state);

  const funnel = state.funnel ?? {};
  let currentStage = funnel[candidateId]?.current_stage ?? "IDENTIFIED";
  if (FUNNEL_STAGE_ORDER.indexOf(currentStage) < FUNNEL_STAGE_ORDER.indexOf("CONTACTED")) {
    const record = await funnelStage.update(roleId, candidateId, "CONTACTED", { note: "outreach marked sent" });
    currentStage = record.current_stage;
  }

  return { candidate_id: candidateId, sent_at: sentAt, funnel_stage: currentStage };
}
