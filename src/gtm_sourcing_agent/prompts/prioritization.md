Prioritize the candidate below against the ICP. This is a recommendation
for the recruiter, never an automated decision — you are not rejecting
this candidate, you are giving the recruiter a starting point and telling
them what to check.

ICP:
---
{{ icp_json }}
---

Candidate record:
---
{{ candidate_json }}
---

Assign exactly one tier:
- A — HIGH PRIORITY: strong evidence of fit against the must-haves.
- B — MEDIUM PRIORITY: potentially strong, but requires validation on
  specific points.
- C — LOW PRIORITY: limited evidence of fit.
- D — DO NOT PRIORITIZE (for now): clear mismatch with core requirements.

For A and B tiers specifically, be explicit about: why they fit
(`why_they_fit`), concrete weaknesses against the must-haves
(`weaknesses` — an actual gap, e.g. "no enterprise closing experience",
not a missing fact), what is unknown (`what_is_unknown` — gaps in the
*evidence*, not weaknesses; something you can't tell either way from what
you have), and what to validate in screening. For C and D, still give a
rationale — a low tier without a reason is not useful to the recruiter
and looks like an unexplained auto-reject, which this system does not do.

Also set:
- `fit_score`: 0-100, your best-effort numeric read of fit against the
  ICP's must-haves. This is a fast visual number for the recruiter, not
  a replacement for the tier or the rationale above — a low score still
  needs the same reasoning a low tier does.
- `fit_rating`: RED (clear mismatch), YELLOW (partial fit / needs
  validation), or GREEN (strong fit). Roughly: tier A/strong B -> GREEN,
  weak B/strong C -> YELLOW, weak C/D -> RED — but use judgment, this is
  a distinct at-a-glance signal, not a mechanical remap of the tier.

Do not set `recruiter_decision`, `placed`, `placement_fee`, or
`placed_at` — those fields belong to the recruiter, not to this stage;
leave them at their defaults.

Output must validate against the CandidatePrioritization schema.
