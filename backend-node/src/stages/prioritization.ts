// Port of stages/prioritization.py -- Stage 8: Candidate Prioritization
// (A/B/C/D). Never deletes or hides a candidate.
import { StorageError } from "../db/storage.js";
import * as storage from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { CandidatePrioritization } from "../models.js";

export async function run(roleId: string, candidateId: string): Promise<CandidatePrioritization> {
  const icp = await storage.requireSection(roleId, "icp");
  const candidates = await storage.requireSection(roleId, "candidates");
  if (!(candidateId in candidates)) {
    throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  }
  // Re-running this (a "re-rank") replaces the whole prioritization
  // record -- carry the recruiter-set fields forward rather than
  // silently wiping a decision or a placement/fee a re-rank has nothing
  // to do with. Only the recruiter's own actions ever change these.
  const existing = ((await storage.loadRole(roleId)).prioritizations ?? {})[candidateId] ?? {};

  const prompt = llmClient.renderPrompt("prioritization.md", {
    icp_json: JSON.stringify(icp), candidate_json: JSON.stringify(candidates[candidateId]),
  });
  const result = await llmClient.generate(prompt, CandidatePrioritization, { stage: "prioritization" });
  result.candidate_id = candidateId;
  result.recruiter_decision = existing.recruiter_decision ?? null;
  result.placed = existing.placed ?? false;
  result.placement_fee = existing.placement_fee ?? 0.0;
  result.placed_at = existing.placed_at ?? null;
  await storage.mergePrioritization(roleId, candidateId, result);
  return result;
}

export async function setRecruiterDecision(roleId: string, candidateId: string, decision: string) {
  const state = await storage.loadRole(roleId);
  const prioritizations = state.prioritizations ?? {};
  if (!(candidateId in prioritizations)) {
    throw new StorageError(`candidate '${candidateId}' has not been prioritized yet for role '${roleId}'`);
  }
  const record = { ...prioritizations[candidateId] };
  record.recruiter_decision = decision || null;
  await storage.mergePrioritization(roleId, candidateId, record);
  return { candidate_id: candidateId, recruiter_decision: record.recruiter_decision };
}

export async function setPlacement(roleId: string, candidateId: string, placed: boolean, fee = 0.0) {
  const state = await storage.loadRole(roleId);
  const prioritizations = state.prioritizations ?? {};
  if (!(candidateId in prioritizations)) {
    throw new StorageError(`candidate '${candidateId}' has not been prioritized yet for role '${roleId}'`);
  }
  const record = { ...prioritizations[candidateId] };
  record.placed = placed;
  record.placement_fee = placed ? fee : 0.0;
  record.placed_at = placed ? new Date().toISOString() : null;
  await storage.mergePrioritization(roleId, candidateId, record);
  return {
    candidate_id: candidateId, placed: record.placed,
    placement_fee: record.placement_fee, placed_at: record.placed_at,
  };
}
