"""Weekly effort/time-allocation planning (TAT/prioritization batch): a
recommendation for how many days a recruiter should spend on each of
their open roles this week, given each role's urgency/TAT/deadline and
the recruiter's own available capacity. Never an automated schedule
(Architecture §1.1's "recommendation, not automated decision" precedent,
same category as CandidatePrioritization.tier) — the recruiter decides
what to actually do with it.
"""

from pydantic import BaseModel, Field


class RoleEffortAllocation(BaseModel):
    role_id: str
    title: str
    recommended_days_this_week: float = Field(ge=0)
    rationale: str = Field(
        default="",
        description="grounded in the role's actual urgency/tat_days/target_fill_date/pipeline stage counts, never generic advice",
    )


class WeeklyEffortPlan(BaseModel):
    available_days_per_week: float = Field(ge=0)
    allocations: list[RoleEffortAllocation] = Field(default_factory=list)
    overall_notes: str = Field(
        default="",
        description="e.g. flagging that recommended days exceed available capacity, or that a role needs deprioritizing",
    )
