A recruiter has {{ available_days_per_week }} working days available this
week, to split across the open roles below. For each role, recommend how
many days *this week specifically* they should spend on it, and why —
grounded in that role's actual urgency, how long it's been open
(tat_days), its client deadline if one was given (target_fill_date), and
where its candidates currently sit in the pipeline (funnel_stage_counts,
candidates_total). This is a recommendation the recruiter can override,
never an automated schedule — never phrase a rationale as an instruction
("spend exactly X hours"), phrase it as a judgment call with reasoning.

Roles (each already includes role_id, title, urgency, tat_days,
target_fill_date, role_value, candidates_total, funnel_stage_counts):
---
{{ roles_json }}
---

Rules:
- Give exactly one allocation per role_id listed above, using that exact
  role_id — do not invent a new one, and do not skip any role in the
  list.
- Recommended days across all roles should not exceed
  {{ available_days_per_week }} unless you explicitly explain in
  overall_notes why more capacity is genuinely needed this week (e.g.
  two roles are both overdue against a client deadline at once) — flag
  that as a real capacity problem, don't silently over-allocate.
- A role with no candidates yet and no deadline or urgency pressure can
  reasonably get 0 days this week — say so plainly in its rationale
  rather than padding time onto it just to avoid a zero.
- Weigh urgency (the client's stated priority) and target_fill_date (an
  actual deadline, if given) more heavily than tat_days alone — a role
  open 60 days with normal/low urgency and no deadline is not
  automatically more urgent than a role opened 5 days ago that's due in
  a week. An overdue target_fill_date (in the past) is the strongest
  signal of all.
- Ground every rationale in the specific numbers given for that role
  (urgency level, tat_days, days until/since target_fill_date,
  candidates_total, funnel_stage_counts) — never a generic "this role
  needs attention" with no numbers behind it.
- Use overall_notes for anything that applies across roles rather than
  to one of them: total capacity vs. total need, a role that looks
  stalled and might need the recruiter's judgment beyond just more time,
  etc.

Output must validate against the WeeklyEffortPlan schema.
