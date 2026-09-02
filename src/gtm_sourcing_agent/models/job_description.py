"""Stage 1 output: Role Intake & Deconstruction (operating brief §1)."""

from pydantic import BaseModel, Field


class RequirementClassification(BaseModel):
    """A single requirement pulled from the JD, classified per §1.

    `category` is one of: explicit, implied, unnecessary, ambiguous,
    overly_narrowing. A requirement can reasonably appear more than once
    across categories is not allowed — pick the single best-fit category
    and use `note` to flag a secondary concern.
    """

    requirement: str
    category: str = Field(
        description="one of: explicit | implied | unnecessary | ambiguous | overly_narrowing"
    )
    note: str = Field(default="", description="why it's classified this way")


class JobDescription(BaseModel):
    raw_jd_text: str

    company: str
    role_title: str
    function: str
    seniority: str
    geography: str
    reporting_structure: str = ""

    role_objective: str
    core_responsibilities: list[str] = Field(default_factory=list)
    compensation: str = Field(
        default="", description="salary/OTE/band as stated in the JD, free text — empty if the JD never mentions it, never estimated"
    )

    must_have_requirements: list[str] = Field(default_factory=list)
    nice_to_have_requirements: list[str] = Field(default_factory=list)
    transferable_experience: list[str] = Field(default_factory=list)
    disqualifiers: list[str] = Field(default_factory=list)

    industry_domain: str = ""
    customer_segment: str = ""
    product_exposure: str = ""
    technical_requirements: list[str] = Field(default_factory=list)
    commercial_requirements: list[str] = Field(default_factory=list)
    leadership_requirements: list[str] = Field(default_factory=list)
    relevant_years_experience: str = ""

    requirement_classifications: list[RequirementClassification] = Field(
        default_factory=list,
        description="explicit/implied/unnecessary/ambiguous/overly-narrowing breakdown, per §1",
    )
    contradictions: list[str] = Field(
        default_factory=list, description="contradictions found in the JD"
    )
    missing_critical_information: list[str] = Field(
        default_factory=list,
        description="information needed before sourcing can responsibly begin",
    )
