"""Weekly effort/time-allocation planning (TAT/prioritization batch):
given a recruiter's own available capacity and their open roles' urgency/
TAT/deadline/pipeline state, recommend how many days this week to spend
on each. Never an automated schedule (Architecture §1.1) — a
recommendation the recruiter can override, same category as
CandidatePrioritization.tier.

Not job-scoped like every other stage in this package — it spans a
recruiter's whole roster, which is why it takes `recruiter_email`
instead of `role_id` and why Task.role_id is nullable for this kind
(see models_orm.py's Task docstring). Also DB-only, same category as
conversation_summary.py: multi-recruiter assignment (JobRecruiter) and
job-shell metadata (urgency, target_fill_date) are db_storage-only
concepts with no file-backend equivalent, so storage_backend defaults to
db_storage, not storage, and this stage has no CLI pipeline entry."""

import json

from .. import db_storage, llm_client
from ..models.workload import RoleEffortAllocation, WeeklyEffortPlan


def run(
    recruiter_email: str, available_days_per_week: float, *, storage_backend=db_storage
) -> WeeklyEffortPlan:
    roles = storage_backend.list_jobs_for_recruiter(recruiter_email)

    prompt = llm_client.render_prompt(
        "workload_planning.md",
        available_days_per_week=available_days_per_week,
        roles_json=json.dumps(roles, default=str),
    )
    result = llm_client.generate(prompt, WeeklyEffortPlan, stage="workload_planning")
    result.available_days_per_week = available_days_per_week

    # Safety net, not a correctness check on the model's judgment: a role
    # the model's response omitted (skipped it, or invented an unrelated
    # role_id for it) still needs to show up, since a role silently
    # vanishing from the recruiter's weekly plan is worse than an honest
    # "not explicitly addressed" placeholder. Never trust an allocation's
    # role_id/title beyond matching it back to a role actually in the
    # roster passed above.
    by_role_id = {a.role_id: a for a in result.allocations}
    matched = [by_role_id[r["role_id"]] for r in roles if r["role_id"] in by_role_id]
    missing = [r for r in roles if r["role_id"] not in by_role_id]

    if missing:
        allocated_so_far = sum(a.recommended_days_this_week for a in matched)
        remaining = max(available_days_per_week - allocated_so_far, 0.0)
        share = round(remaining / len(missing), 1)
        for r in missing:
            matched.append(RoleEffortAllocation(
                role_id=r["role_id"], title=r["title"], recommended_days_this_week=share,
                rationale="Split evenly across remaining capacity — not explicitly addressed in this week's plan.",
            ))

    result.allocations = matched
    return result
