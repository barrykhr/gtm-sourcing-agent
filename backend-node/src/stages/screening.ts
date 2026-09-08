// Port of stages/screening.py -- Stage 10: Recruiter Screening questions.
import * as storage from "../db/storage.js";
import { StorageError } from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { ScreeningQuestionSet } from "../models.js";

export async function run(roleId: string, candidateId: string): Promise<ScreeningQuestionSet> {
  const calibration = await storage.requireSection(roleId, "calibration");
  const candidates = await storage.requireSection(roleId, "candidates");
  const prioritizations = await storage.requireSection(roleId, "prioritizations");
  if (!(candidateId in candidates)) {
    throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  }
  if (!(candidateId in prioritizations)) {
    throw new StorageError(`candidate '${candidateId}' has not been prioritized yet — run prioritize first`);
  }

  const prompt = llmClient.renderPrompt("screening_questions.md", {
    candidate_json: JSON.stringify(candidates[candidateId]),
    prioritization_json: JSON.stringify(prioritizations[candidateId]),
    calibration_json: JSON.stringify(calibration),
  });
  const result = await llmClient.generate(prompt, ScreeningQuestionSet, { stage: "screening" });
  result.candidate_id = candidateId;

  const state = await storage.loadRole(roleId);
  (state.screening ??= {})[candidateId] = result;
  await storage.saveRole(roleId, state);
  return result;
}
