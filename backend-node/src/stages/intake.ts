// Port of stages/intake.py -- Stage 1: Role Intake & Deconstruction.
import * as storage from "../db/storage.js";
import { StorageError } from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { JobDescription } from "../models.js";

export async function run(roleId: string, jdText: string): Promise<JobDescription> {
  const prompt = llmClient.renderPrompt("intake.md", { jd_text: jdText });
  const result = await llmClient.generate(prompt, JobDescription, { stage: "intake" });
  await storage.mergeSection(roleId, "job_description", result);
  return result;
}

export const EDITABLE_FIELDS = [
  "role_title", "seniority", "geography", "compensation",
  "must_have_requirements", "nice_to_have_requirements",
] as const;

export async function updateFields(roleId: string, fields: Record<string, unknown>) {
  const unknown = Object.keys(fields).filter((k) => !(EDITABLE_FIELDS as readonly string[]).includes(k));
  if (unknown.length) {
    throw new StorageError(`not an editable job-description field: ${unknown.sort().join(", ")}`);
  }
  const current = await storage.requireSection(roleId, "job_description");
  const updated = { ...current };
  for (const [key, value] of Object.entries(fields)) {
    if (value !== null && value !== undefined) updated[key] = value;
  }
  await storage.mergeSection(roleId, "job_description", updated);
  return updated;
}
