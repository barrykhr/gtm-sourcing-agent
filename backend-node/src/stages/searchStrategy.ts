// Port of stages/search_strategy.py -- Stage 6: Search Strategy
// generation. Regenerable independently of target companies / title
// intelligence.
import * as storage from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import { TalentMap } from "../models.js";

export async function run(roleId: string): Promise<TalentMap> {
  const talentMap = await storage.requireSection(roleId, "talent_map");
  const prompt = llmClient.renderPrompt("search_strategy.md", { talent_map_json: JSON.stringify(talentMap) });
  const result = await llmClient.generate(prompt, TalentMap, { stage: "search_strategy" });

  const existing = (await storage.loadRole(roleId)).talent_map;
  const merged: TalentMap = {
    target_companies: existing?.target_companies ?? [],
    title_intelligence: existing?.title_intelligence ?? {
      exact_target_titles: [], alternative_titles: [], previous_titles: [], adjacent_titles: [],
      market_terminology: [], competitor_titles: [], geography_specific_titles: [],
    },
    search_strategies: result.search_strategies,
  };
  await storage.mergeSection(roleId, "talent_map", merged);
  return merged;
}
