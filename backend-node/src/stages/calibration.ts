// Port of stages/calibration.py -- Stage 2: Hiring Manager Calibration.
import * as storage from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { HiringManagerCalibration } from "../models.js";

export async function run(roleId: string): Promise<HiringManagerCalibration> {
  const jd = await storage.requireSection(roleId, "job_description");
  const prompt = llmClient.renderPrompt("calibration.md", { job_description_json: JSON.stringify(jd) });
  const result = await llmClient.generate(prompt, HiringManagerCalibration, { stage: "calibration" });
  await storage.mergeSection(roleId, "calibration", result);
  return result;
}
