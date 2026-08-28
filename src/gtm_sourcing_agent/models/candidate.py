"""Stage 7-8 output: Candidate Identification (§7) and Prioritization (§8).

Evidence discipline (Architecture §1.2) is enforced here, not just by
prompt instruction: every fact that could be wrong is an `EvidencedFact`,
never a bare string, so a stage cannot produce an achievement or metric
without labeling its evidence level.
"""

from typing import Literal

from pydantic import BaseModel, Field

EvidenceLevel = Literal["VERIFIED", "NOT_STATED", "INFERRED"]
PriorityTier = Literal["A", "B", "C", "D"]


class EvidencedFact(BaseModel):
    fact: str
    evidence_level: EvidenceLevel
    source: str = Field(
        default="", description="where this came from, e.g. 'LinkedIn About section'"
    )


class Candidate(BaseModel):
    candidate_id: str = Field(description="stable id, e.g. slugified name + role_id")
    name: str
    current_company: str = ""
    current_title: str = ""
    location: str = ""
    previous_relevant_companies: list[str] = Field(default_factory=list)
    relevant_experience_summary: str = ""
    industry: str = ""
    customer_segment: str = ""
    seniority: str = ""

    achievements: list[EvidencedFact] = Field(default_factory=list)
    metrics: list[EvidencedFact] = Field(default_factory=list)
    education: str = Field(default="", description="only populate when relevant to fit")

    source_url: str = ""
    evidence_of_fit: list[EvidencedFact] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    recommended_next_action: str = ""


class CandidatePrioritization(BaseModel):
    """Never a rejection mechanism (Architecture §1.1): `tier` is a
    recommendation with rationale. `recruiter_decision` is the only field
    that can move a candidate out of the active pool, and it is only ever
    set by the recruiter, never by a stage."""

    candidate_id: str
    tier: PriorityTier
    why_they_fit: list[str] = Field(default_factory=list)
    what_is_unknown: list[str] = Field(default_factory=list)
    what_to_validate: list[str] = Field(default_factory=list)
    recruiter_decision: str | None = Field(
        default=None,
        description="set only by the recruiter, e.g. 'pursue', 'pass for now', 'revisit in Q3'",
    )
