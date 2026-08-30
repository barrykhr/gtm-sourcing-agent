"""Stage 4-6 output: Talent Market Mapping (§4), Title Intelligence (§5),
Search Strategy (§6)."""

from typing import Literal

from pydantic import BaseModel, Field

Tier = Literal[1, 2, 3]
SearchType = Literal[
    "broad", "targeted", "competitor", "adjacent", "transferable", "geography", "seniority"
]

# The one consistent yardstick every company is tiered against — same
# four dimensions for Tier 1 and Tier 3 alike, so "why is this Tier 2
# and not Tier 1" always has a concrete answer instead of a vibe.
MatchDimension = Literal["product", "business_segment", "customer_base", "industry"]


class TargetCompany(BaseModel):
    name: str
    tier: Tier
    match_dimensions: list[MatchDimension] = Field(
        default_factory=list,
        description="which of product / business_segment / customer_base / industry this company actually "
        "shares with the target role — the basis for its tier, not a separate opinion from it",
    )
    why_relevant: str
    roles_to_target: list[str] = Field(default_factory=list)
    likely_talent_type: str = ""
    seniority_levels_to_target: list[str] = Field(default_factory=list)
    limitations: str = Field(
        default="", description="potential limitations of this talent pool"
    )


class TitleIntelligence(BaseModel):
    exact_target_titles: list[str] = Field(default_factory=list)
    alternative_titles: list[str] = Field(default_factory=list)
    previous_titles: list[str] = Field(default_factory=list)
    adjacent_titles: list[str] = Field(default_factory=list)
    market_terminology: list[str] = Field(default_factory=list)
    competitor_titles: list[str] = Field(default_factory=list)
    geography_specific_titles: list[str] = Field(default_factory=list)


class SearchStrategy(BaseModel):
    name: str
    search_type: SearchType
    purpose: str = Field(description="what this specific search is intended to capture")
    linkedin_boolean: str = ""
    google_xray: str = ""
    naukri_search: str = ""
    github_search: str = ""
    other_channels: list[str] = Field(default_factory=list)


class TalentMap(BaseModel):
    target_companies: list[TargetCompany] = Field(default_factory=list)
    title_intelligence: TitleIntelligence = Field(default_factory=TitleIntelligence)
    search_strategies: list[SearchStrategy] = Field(default_factory=list)
