"""Stage 12-13: Funnel tracking and forecasting.

Unlike the other stages, funnel math is deterministic arithmetic, not
something an LLM should be asked to compute (rates and leakage have exact
answers; forecasting is exact given assumptions). `update` and `report`
run with no LLM call and no API key required. `prompts/funnel_analysis.md`
is reserved for an optional future narrative layer (e.g. "why is this
stage leaking") on top of these numbers, not for the arithmetic itself.
"""

import math
from datetime import UTC, datetime

from .. import storage
from ..models.funnel import FUNNEL_STAGE_ORDER, ForecastAssumptions, ForecastResult, FunnelMetrics


def update(
    role_id: str, candidate_id: str, stage: str, *,
    note: str = "", scheduled_at: str | None = None, storage_backend=storage,
) -> dict:
    if stage not in FUNNEL_STAGE_ORDER:
        raise ValueError(f"unknown funnel stage: {stage!r}")

    state = storage_backend.load_role(role_id)
    funnel = state.setdefault("funnel", {})
    record = funnel.setdefault(
        candidate_id,
        {"candidate_id": candidate_id, "role_id": role_id, "current_stage": "IDENTIFIED", "stage_history": []},
    )
    record["current_stage"] = stage
    record["stage_history"].append({
        "stage": stage, "at": datetime.now(UTC).isoformat(), "note": note, "scheduled_at": scheduled_at,
    })
    storage_backend.save_role(role_id, state)
    return record


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def report(role_id: str, *, storage_backend=storage) -> FunnelMetrics:
    state = storage_backend.load_role(role_id)
    funnel = state.get("funnel", {})

    counts = {stage: 0 for stage in FUNNEL_STAGE_ORDER}
    for record in funnel.values():
        # a candidate at stage N has passed through every stage before it
        reached = record.get("current_stage", "IDENTIFIED")
        idx = FUNNEL_STAGE_ORDER.index(reached)
        for stage in FUNNEL_STAGE_ORDER[: idx + 1]:
            counts[stage] += 1

    identified, contacted, responded, interested = (
        counts["IDENTIFIED"], counts["CONTACTED"], counts["RESPONDED"], counts["INTERESTED"],
    )
    screen, hm, final, offer, accepted, joined = (
        counts["RECRUITER_SCREEN"], counts["HM_INTERVIEW"], counts["FINAL_INTERVIEW"],
        counts["OFFER"], counts["ACCEPTED"], counts["JOINED"],
    )

    biggest_leakage_stage = ""
    worst_drop = -1.0
    for prev, cur in zip(FUNNEL_STAGE_ORDER, FUNNEL_STAGE_ORDER[1:]):
        if counts[prev] == 0:
            continue
        drop = 1 - (counts[cur] / counts[prev])
        if drop > worst_drop:
            worst_drop, biggest_leakage_stage = drop, f"{prev} -> {cur}"

    recommended_intervention = (
        f"Largest relative drop-off is {biggest_leakage_stage} "
        f"({worst_drop:.0%} loss). Investigate that transition first — "
        f"e.g. message quality/targeting if it's CONTACTED->RESPONDED, "
        f"or screen calibration if it's RECRUITER_SCREEN->HM_INTERVIEW."
        if biggest_leakage_stage
        else "Not enough funnel data yet to identify a leakage stage."
    )

    metrics = FunnelMetrics(
        role_id=role_id,
        counts_by_stage=counts,
        contact_rate=_rate(contacted, identified),
        response_rate=_rate(responded, contacted),
        positive_response_rate=_rate(interested, responded),
        screen_conversion=_rate(hm, screen),
        hm_conversion=_rate(final, hm),
        final_conversion=_rate(offer, final),
        offer_rate=_rate(offer, final),
        offer_acceptance_rate=_rate(accepted, offer),
        joining_rate=_rate(joined, accepted),
        biggest_leakage_stage=biggest_leakage_stage,
        recommended_intervention=recommended_intervention,
    )
    storage_backend.merge_section(role_id, "funnel_metrics", metrics.model_dump())
    return metrics


def forecast(hires_needed: int, timeline_weeks: int, assumptions: ForecastAssumptions) -> ForecastResult:
    """Back-calculate required volume at each stage per §13. Labels in
    `assumptions.source` must say whether rates are 'historical' or
    'market_default' — never presented as measured fact when they're an
    assumption (Architecture §1.5)."""

    def up(count: float, rate: float) -> int:
        return math.ceil(count / rate) if rate > 0 else 0

    required_offers = up(hires_needed, assumptions.offer_to_accept)
    required_finalists = up(required_offers, assumptions.final_to_offer)
    required_hm_interviews = up(required_finalists, assumptions.hm_interview_to_final)
    required_recruiter_screens = up(required_hm_interviews, assumptions.screen_to_hm_interview)
    required_qualified_candidates = up(required_recruiter_screens, assumptions.contacted_to_screen)
    required_sourced_candidates = up(required_qualified_candidates, assumptions.sourced_to_contacted)

    return ForecastResult(
        hires_needed=hires_needed,
        timeline_weeks=timeline_weeks,
        assumptions=assumptions,
        required_offers=required_offers,
        required_finalists=required_finalists,
        required_hm_interviews=required_hm_interviews,
        required_recruiter_screens=required_recruiter_screens,
        required_qualified_candidates=required_qualified_candidates,
        required_sourced_candidates=required_sourced_candidates,
    )
