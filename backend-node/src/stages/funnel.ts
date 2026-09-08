// Port of stages/funnel.py -- deterministic arithmetic, no LLM call.
// update()/report() mirror the Python module exactly; forecast() is pure
// math with no storage dependency at all.
import * as storage from "../db/storage.js";
import { StorageError } from "../db/storage.js";

export const FUNNEL_STAGE_ORDER = [
  "IDENTIFIED", "REVIEWED", "SHORTLISTED", "CONTACTED", "RESPONDED", "INTERESTED",
  "RECRUITER_SCREEN", "HM_INTERVIEW", "FINAL_INTERVIEW", "OFFER", "ACCEPTED", "JOINED",
] as const;

export async function update(
  roleId: string, candidateId: string, stage: string,
  args: { note?: string; scheduledAt?: string | null } = {}
) {
  if (!(FUNNEL_STAGE_ORDER as readonly string[]).includes(stage)) {
    throw new StorageError(`unknown funnel stage: '${stage}'`);
  }
  const state = await storage.loadRole(roleId);
  const funnel = (state.funnel ??= {});
  const record = (funnel[candidateId] ??= {
    candidate_id: candidateId, role_id: roleId, current_stage: "IDENTIFIED", stage_history: [],
  });
  record.current_stage = stage;
  record.stage_history.push({
    stage, at: new Date().toISOString(), note: args.note ?? "", scheduled_at: args.scheduledAt ?? null,
  });
  await storage.saveRole(roleId, state);
  return record;
}

function rate(numerator: number, denominator: number): number | null {
  return denominator ? Math.round((numerator / denominator) * 10000) / 10000 : null;
}

export async function report(roleId: string) {
  const state = await storage.loadRole(roleId);
  const funnel: Record<string, any> = state.funnel ?? {};

  const counts: Record<string, number> = Object.fromEntries(FUNNEL_STAGE_ORDER.map((s) => [s, 0]));
  for (const record of Object.values(funnel)) {
    const reached = record.current_stage ?? "IDENTIFIED";
    const idx = FUNNEL_STAGE_ORDER.indexOf(reached as any);
    for (let i = 0; i <= idx; i++) counts[FUNNEL_STAGE_ORDER[i]!]!++;
  }

  const { IDENTIFIED: identified, CONTACTED: contacted, RESPONDED: responded, INTERESTED: interested,
    RECRUITER_SCREEN: screen, HM_INTERVIEW: hm, FINAL_INTERVIEW: final, OFFER: offer,
    ACCEPTED: accepted, JOINED: joined } = counts as any;

  let biggestLeakageStage = "";
  let worstDrop = -1.0;
  for (let i = 0; i < FUNNEL_STAGE_ORDER.length - 1; i++) {
    const prev = FUNNEL_STAGE_ORDER[i]!;
    const cur = FUNNEL_STAGE_ORDER[i + 1]!;
    if (counts[prev] === 0) continue;
    const drop = 1 - counts[cur]! / counts[prev]!;
    if (drop > worstDrop) {
      worstDrop = drop;
      biggestLeakageStage = `${prev} -> ${cur}`;
    }
  }

  const recommendedIntervention = biggestLeakageStage
    ? `Largest relative drop-off is ${biggestLeakageStage} ` +
      `(${Math.round(worstDrop * 100)}% loss). Investigate that transition first — ` +
      `e.g. message quality/targeting if it's CONTACTED->RESPONDED, ` +
      `or screen calibration if it's RECRUITER_SCREEN->HM_INTERVIEW.`
    : "Not enough funnel data yet to identify a leakage stage.";

  const metrics = {
    role_id: roleId,
    counts_by_stage: counts,
    contact_rate: rate(contacted, identified),
    response_rate: rate(responded, contacted),
    positive_response_rate: rate(interested, responded),
    screen_conversion: rate(hm, screen),
    hm_conversion: rate(final, hm),
    final_conversion: rate(offer, final),
    offer_rate: rate(offer, final),
    offer_acceptance_rate: rate(accepted, offer),
    joining_rate: rate(joined, accepted),
    biggest_leakage_stage: biggestLeakageStage,
    recommended_intervention: recommendedIntervention,
  };
  await storage.mergeSection(roleId, "funnel_metrics", metrics);
  return metrics;
}

export interface ForecastAssumptions {
  source: "historical" | "market_default";
  screen_to_hm_interview: number;
  hm_interview_to_final: number;
  final_to_offer: number;
  offer_to_accept: number;
  contacted_to_screen: number;
  sourced_to_contacted: number;
}

export function forecast(hiresNeeded: number, timelineWeeks: number, assumptions: ForecastAssumptions) {
  const up = (count: number, rate: number) => (rate > 0 ? Math.ceil(count / rate) : 0);

  const requiredOffers = up(hiresNeeded, assumptions.offer_to_accept);
  const requiredFinalists = up(requiredOffers, assumptions.final_to_offer);
  const requiredHmInterviews = up(requiredFinalists, assumptions.hm_interview_to_final);
  const requiredRecruiterScreens = up(requiredHmInterviews, assumptions.screen_to_hm_interview);
  const requiredQualifiedCandidates = up(requiredRecruiterScreens, assumptions.contacted_to_screen);
  const requiredSourcedCandidates = up(requiredQualifiedCandidates, assumptions.sourced_to_contacted);

  return {
    hires_needed: hiresNeeded,
    timeline_weeks: timelineWeeks,
    assumptions,
    required_offers: requiredOffers,
    required_finalists: requiredFinalists,
    required_hm_interviews: requiredHmInterviews,
    required_recruiter_screens: requiredRecruiterScreens,
    required_qualified_candidates: requiredQualifiedCandidates,
    required_sourced_candidates: requiredSourcedCandidates,
  };
}
