"""Stage 2-3 output: Hiring Manager Calibration (§2) and Ideal Candidate
Profile (§3)."""

from pydantic import BaseModel, Field


class HiringManagerCalibration(BaseModel):
    must_have_criteria: list[str] = Field(default_factory=list)
    evaluation_criteria: list[str] = Field(default_factory=list)
    strong_candidate_definition: str = ""
    acceptable_candidate_definition: str = ""
    weak_candidate_definition: str = ""
    red_flags: list[str] = Field(default_factory=list)
    transferable_profiles_worth_considering: list[str] = Field(default_factory=list)
    looks_good_on_paper_but_reject: list[str] = Field(default_factory=list)
    interview_questions_to_validate_ambiguous_areas: list[str] = Field(default_factory=list)
    unrealistic_requirements_flag: str = Field(
        default="",
        description="non-empty only if requirements appear unrealistic for the market; explain why",
    )


class IdealCandidateProfile(BaseModel):
    target_background: str = ""
    relevant_companies: list[str] = Field(default_factory=list)
    relevant_industries: list[str] = Field(default_factory=list)
    relevant_titles: list[str] = Field(default_factory=list)
    adjacent_titles: list[str] = Field(default_factory=list)
    geography: str = ""
    seniority: str = ""
    typical_career_progression: str = ""
    customer_segment: str = ""
    product_environment: str = ""
    relevant_metrics: list[str] = Field(default_factory=list)
    relevant_accomplishments: list[str] = Field(default_factory=list)
    likely_motivations: list[str] = Field(default_factory=list)
    likely_objections: list[str] = Field(default_factory=list)
    transferable_backgrounds: list[str] = Field(default_factory=list)

    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    transferable: list[str] = Field(default_factory=list)
    disqualifier: list[str] = Field(default_factory=list)
