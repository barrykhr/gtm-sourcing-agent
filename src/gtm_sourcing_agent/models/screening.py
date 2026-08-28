"""Stage 10 output: Recruiter Screening questions (§10)."""

from pydantic import BaseModel, Field


class ScreeningQuestionSet(BaseModel):
    candidate_id: str
    must_ask: list[str] = Field(
        default_factory=list,
        description="validate facts/unknowns from this candidate's prioritization record",
    )
    nice_to_ask: list[str] = Field(default_factory=list)
    red_flag_followups: list[str] = Field(default_factory=list)
