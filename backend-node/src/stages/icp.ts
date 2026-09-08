// Port of stages/icp.py -- Stage 3: Ideal Candidate Profile.
import * as storage from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { IdealCandidateProfile } from "../models.js";

export async function run(roleId: string): Promise<IdealCandidateProfile> {
  const jd = await storage.requireSection(roleId, "job_description");
  const calibration = await storage.requireSection(roleId, "calibration");
  const prompt = llmClient.renderPrompt("icp.md", {
    job_description_json: JSON.stringify(jd), calibration_json: JSON.stringify(calibration),
  });
  const result = await llmClient.generate(prompt, IdealCandidateProfile, { stage: "icp" });
  await storage.mergeSection(roleId, "icp", result);
  return result;
}

export async function updateCriteria(
  roleId: string, args: { mustHave?: string[] | null; niceToHave?: string[] | null }
) {
  const current = await storage.requireSection(roleId, "icp");
  const updated = { ...current };
  if (args.mustHave != null) updated.must_have = args.mustHave;
  if (args.niceToHave != null) updated.nice_to_have = args.niceToHave;
  await storage.mergeSection(roleId, "icp", updated);
  return updated;
}
