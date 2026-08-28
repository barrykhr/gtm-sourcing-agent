"""Stage 12-13: Sourcing Funnel tracking (§12) and Forecasting (§13)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FunnelStage = Literal[
    "IDENTIFIED",
    "REVIEWED",
    "SHORTLISTED",
    "CONTACTED",
    "RESPONDED",
    "INTERESTED",
    "RECRUITER_SCREEN",
    "HM_INTERVIEW",
    "FINAL_INTERVIEW",
    "OFFER",
    "ACCEPTED",
    "JOINED",
]

FUNNEL_STAGE_ORDER: list[FunnelStage] = [
    "IDENTIFIED",
    "REVIEWED",
    "SHORTLISTED",
    "CONTACTED",
    "RESPONDED",
    "INTERESTED",
    "RECRUITER_SCREEN",
    "HM_INTERVIEW",
    "FINAL_INTERVIEW",
    "OFFER",
    "ACCEPTED",
    "JOINED",
]


class StageTransition(BaseModel):
    stage: FunnelStage
    at: datetime
    note: str = ""
    # Recruiter-entered, not inferred (Phase 8) — when an interview/screen
    # tied to this transition is scheduled for. Distinct from `at`, which
    # is when the stage move itself happened.
    scheduled_at: datetime | None = None


class FunnelRecord(BaseModel):
    candidate_id: str
    role_id: str
    current_stage: FunnelStage = "IDENTIFIED"
    stage_history: list[StageTransition] = Field(default_factory=list)


class FunnelMetrics(BaseModel):
    role_id: str
    counts_by_stage: dict[str, int] = Field(default_factory=dict)
    contact_rate: float | None = None
    response_rate: float | None = None
    positive_response_rate: float | None = None
    screen_conversion: float | None = None
    hm_conversion: float | None = None
    final_conversion: float | None = None
    offer_rate: float | None = None
    offer_acceptance_rate: float | None = None
    joining_rate: float | None = None
    biggest_leakage_stage: str = ""
    recommended_intervention: str = ""


class ForecastAssumptions(BaseModel):
    """Every rate here must be labeled by the caller as either
    'historical' (recruiter-supplied, from real funnel data) or
    'market_default' (an assumption used in the absence of data) —
    Architecture §1.5. Never present a market_default rate as if it were
    a measured historical rate.
    """

    source: Literal["historical", "market_default"]
    screen_to_hm_interview: float
    hm_interview_to_final: float
    final_to_offer: float
    offer_to_accept: float
    contacted_to_screen: float
    sourced_to_contacted: float


class ForecastResult(BaseModel):
    hires_needed: int
    timeline_weeks: int
    assumptions: ForecastAssumptions
    required_offers: int
    required_finalists: int
    required_hm_interviews: int
    required_recruiter_screens: int
    required_qualified_candidates: int
    required_sourced_candidates: int
