"""Feature 01 output: Create Role + Role Intelligence (TALYN_V2_ARCHITECTURE.md
§3/§5/§6). Evidence vocabulary here is deliberately 4-state — CONFIRMED /
INFERRED / NOT_STATED / CONFLICTING — a separate enum from
models/candidate.py's 3-state EvidenceLevel (VERIFIED/NOT_STATED/INFERRED).
Widening that one would touch candidate-scoring code outside this
feature's scope; see the architecture doc's decision #3 for why the fork
is deliberate, not an oversight.
"""

from typing import Literal

from pydantic import BaseModel, Field

RequirementEvidenceLevel = Literal["CONFIRMED", "INFERRED", "NOT_STATED", "CONFLICTING"]
RequirementCategory = Literal["skill", "experience", "location", "comp", "other"]
RequirementPriority = Literal["must_have", "nice_to_have"]


class EvidencedField(BaseModel):
    """One evidence-backed fact: a requirement's value, or one field of
    the ICP. `source_span` is the literal JD text it came from — required
    when evidence_level is CONFIRMED, empty otherwise, never fabricated."""

    value: str = ""
    evidence_level: RequirementEvidenceLevel = "NOT_STATED"
    source_span: str = Field(default="", description="literal JD text this came from; empty unless CONFIRMED")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ExtractedRequirement(BaseModel):
    category: RequirementCategory = "other"
    value: str
    priority: RequirementPriority = "nice_to_have"
    evidence_level: RequirementEvidenceLevel = "NOT_STATED"
    source_span: str = Field(default="", description="literal JD text this came from; empty unless CONFIRMED")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str = Field(default="", description="concise reasoning summary, never raw chain-of-thought")


class ExtractedAmbiguity(BaseModel):
    description: str
    candidate_resolutions: list[str] = Field(default_factory=list)


class GeneratedSearchStrategy(BaseModel):
    """`generate_search_strategy` tool output (Architecture §6) — built
    from a role's own requirements/ICP, not the talent-map pipeline's
    target-company tiering (stages/search_strategy.py, which needs a
    talent_map to exist first). Deliberately not persisted: this is a
    quick, requirements-grounded suggestion a recruiter can ask for at
    any point in Role Intelligence, before or instead of running the
    full talent-mapping pipeline — persisting search strategy is that
    pipeline's job, out of scope here (Architecture §3)."""

    boolean_strings: list[str] = Field(default_factory=list)
    xray_queries: list[str] = Field(default_factory=list)
    rationale: str = Field(default="", description="concise reasoning summary, never raw chain-of-thought")


class RoleExtraction(BaseModel):
    """Stage output: a JD turned into structured, evidence-labeled
    requirements/ICP fields/ambiguities — the Feature 01 replacement for
    letting an opaque hiring-profile summary be the only AI output a
    recruiter sees. Never includes a fabricated source_span: anything the
    model can't point at in the JD text is INFERRED or NOT_STATED, not
    CONFIRMED with an invented quote."""

    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    icp_fields: dict[str, EvidencedField] = Field(
        default_factory=dict,
        description="e.g. company_profile, candidate_persona, comp_band, geography — evidenced like a requirement",
    )
    ambiguities: list[ExtractedAmbiguity] = Field(default_factory=list)
