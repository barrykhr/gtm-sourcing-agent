// Port of pipeline.py -- role-level stage completion + "what's next".
import * as storage from "./db/storage.js";

const ROLE_LEVEL_STAGES: Record<string, (s: Record<string, any>) => boolean> = {
  intake: (s) => Boolean(s.job_description),
  calibration: (s) => Boolean(s.calibration),
  icp: (s) => Boolean(s.icp),
  talent_map: (s) => Boolean(s.talent_map?.target_companies),
  search_strategy: (s) => Boolean(s.talent_map?.search_strategies),
};

export async function status(roleId: string): Promise<Record<string, boolean>> {
  const state = await storage.loadRole(roleId);
  const result: Record<string, boolean> = {};
  for (const [name, isDone] of Object.entries(ROLE_LEVEL_STAGES)) {
    result[name] = isDone(state);
  }
  return result;
}

export async function nextStage(roleId: string): Promise<string | null> {
  const state = await storage.loadRole(roleId);
  for (const [name, isDone] of Object.entries(ROLE_LEVEL_STAGES)) {
    if (!isDone(state)) return name;
  }
  return null;
}
