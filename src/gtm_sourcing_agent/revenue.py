"""Revenue calculation — one central place for the margin assumption
instead of it being scattered across routes/components (same "one
named constant" pattern SESSION_TTL follows in auth.py).

This is a recruitment-placement business, not a subscription product:
figures here are Expected/Pipeline/Realized Revenue, never "ARR" — see
db_storage.revenue_overview()'s docstring for the terminology rationale.

Expected revenue is computed from Job.role_value, a number the
recruiter enters by hand (never AI-inferred — see models_orm.py). A
role with no role_value set has no expected revenue; that's a real
"we don't know yet," not a reason to guess.

Realized revenue is NOT computed here — it's the existing, already-real
CandidatePrioritization.placement_fee a recruiter enters at the moment
of an actual placement (stages/prioritization.py::set_placement). This
module never invents a number where a real one already exists.
"""

# The one number every revenue figure in the product multiplies by.
# Change this in one place; nothing else should hardcode 8.33 (or its
# equivalent 0.0833) anywhere.
REVENUE_MARGIN_PERCENTAGE = 8.33


def expected_revenue(role_value: float | None) -> float | None:
    """Role value * margin — None (not 0) when role_value isn't set, so
    callers can distinguish "no value entered yet" from "worth zero"."""
    if role_value is None:
        return None
    return round(role_value * (REVENUE_MARGIN_PERCENTAGE / 100), 2)
