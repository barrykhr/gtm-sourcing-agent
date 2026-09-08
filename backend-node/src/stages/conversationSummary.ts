// Port of stages/conversation_summary.py -- rolling summary + structured
// extraction across a candidate's full communication log. Runs after
// every new log entry; never on its own schedule.
import * as storage from "../db/storage.js";
import { StorageError } from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { ConversationSummaryResult, ConversationIntelligence } from "../models.js";

export async function run(roleId: string, candidateId: string): Promise<ConversationSummaryResult> {
  const state = await storage.loadRole(roleId);
  const candidate = (state.candidates ?? {})[candidateId];
  if (candidate === undefined) {
    throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  }
  const entries = await storage.listCommunications(roleId, candidateId);
  if (!entries.length) {
    throw new StorageError(`candidate '${candidateId}' has no communications logged yet`);
  }

  const prompt = llmClient.renderPrompt("conversation_summary.md", {
    candidate_json: JSON.stringify(candidate), entries_json: JSON.stringify(entries),
  });
  const result = await llmClient.generate(prompt, ConversationSummaryResult, { stage: "conversation_summary" });
  await storage.setConversationSummary(roleId, candidateId, result.summary, entries.length);
  return result;
}

export async function runIntelligence(roleId: string, candidateId: string): Promise<ConversationIntelligence> {
  const state = await storage.loadRole(roleId);
  const candidate = (state.candidates ?? {})[candidateId];
  if (candidate === undefined) {
    throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  }
  const entries = await storage.listCommunications(roleId, candidateId);
  if (!entries.length) {
    throw new StorageError(`candidate '${candidateId}' has no communications logged yet`);
  }

  const prompt = llmClient.renderPrompt("conversation_intelligence.md", {
    candidate_json: JSON.stringify(candidate), entries_json: JSON.stringify(entries),
  });
  const result = await llmClient.generate(prompt, ConversationIntelligence, { stage: "conversation_intelligence" });
  await storage.setConversationIntelligence(roleId, candidateId, result);
  return result;
}
