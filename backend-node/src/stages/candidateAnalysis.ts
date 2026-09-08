// Port of stages/candidate_analysis.py -- Stage 7: Candidate
// Identification / evidence capture. Takes recruiter-supplied source
// text -- this backend never scrapes candidate profiles.
import * as storage from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { Candidate } from "../models.js";

function slugify(name: string, roleId: string): string {
  const normalized = name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${roleId}-${normalized}`;
}

export async function run(
  roleId: string, candidateSourceText: string, roleFamily: string,
  args: { sourceUrl?: string; resumeFileKey?: string | null; resumeFilename?: string | null } = {}
): Promise<Candidate> {
  const icp = await storage.requireSection(roleId, "icp");
  const prompt = llmClient.renderPrompt("candidate_analysis.md", {
    icp_json: JSON.stringify(icp), candidate_source_text: candidateSourceText, role_family: roleFamily,
  });
  const result = await llmClient.generate(prompt, Candidate, { stage: "candidate_analysis" });
  if (!result.candidate_id) result.candidate_id = slugify(result.name, roleId);
  if (args.sourceUrl && !result.source_url) result.source_url = args.sourceUrl;

  await storage.mergeCandidate(roleId, result.candidate_id, result);

  if (result.email || result.phone) {
    await storage.setCandidateContact(roleId, result.candidate_id, {
      phone: result.phone || null, email: result.email || null,
    });
  }
  if (args.resumeFileKey) {
    await storage.setCandidateResume(roleId, result.candidate_id, args.resumeFileKey, args.resumeFilename ?? "");
  }
  return result;
}
