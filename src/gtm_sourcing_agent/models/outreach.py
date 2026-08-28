"""Stage 11 output: Outreach drafting (§11). Draft only — see Architecture
§1.4 and §7; nothing in this repo sends outreach."""

from pydantic import BaseModel, Field


class OutreachSequence(BaseModel):
    candidate_id: str
    linkedin_connection_note: str = ""
    linkedin_inmail: str = ""
    email: str = ""
    follow_up_1: str = ""
    follow_up_2: str = ""
    personalization_basis: list[str] = Field(
        default_factory=list,
        description=(
            "verified facts (candidate_id's EvidencedFacts with evidence_level=VERIFIED) "
            "actually used for personalization; empty means this draft could not be "
            "personalized and is a generic fallback — the recruiter should know that"
        ),
    )
