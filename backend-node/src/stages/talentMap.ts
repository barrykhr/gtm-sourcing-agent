// Port of stages/talent_map.py -- Stage 4-5: Talent Market Mapping +
// Title Intelligence. Populates target_companies/title_intelligence;
// search_strategies is added separately by searchStrategy.ts so the two
// regenerate independently.
import * as storage from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { TalentMap } from "../models.js";

const MIN_TARGET_COMPANIES = 15; // the prompt asks for >=5 per tier across 3 tiers

export async function run(roleId: string): Promise<TalentMap> {
  const icp = await storage.requireSection(roleId, "icp");
  const prompt = llmClient.renderPrompt("talent_map.md", { icp_json: JSON.stringify(icp) });
  let result = await llmClient.generate(prompt, TalentMap, { stage: "talent_map" });

  if (result.target_companies.length < MIN_TARGET_COMPANIES) {
    const total = result.target_companies.length;
    const retryPrompt = prompt +
      `\n\nYour previous attempt returned only ${total} target companies total — this role needs ` +
      `at least ${MIN_TARGET_COMPANIES} (5+ per tier). Cover more real companies across all three ` +
      `tiers and try again.`;
    const retried = await llmClient.generate(retryPrompt, TalentMap, { stage: "talent_map" });
    if (retried.target_companies.length > total) result = retried;
  }

  const existing = (await storage.loadRole(roleId)).talent_map ?? {};
  result.search_strategies = existing.search_strategies?.length ? existing.search_strategies : result.search_strategies;
  await storage.mergeSection(roleId, "talent_map", result);
  return result;
}
