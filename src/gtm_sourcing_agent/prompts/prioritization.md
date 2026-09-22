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
- `competency_scores`: exactly five entries, one per dimension below.
  Each is scored and rationalized independently — do not just repeat
  `fit_score` five times or restate the label as the rationale. Every
  rationale must point at something specific in the candidate record or
  ICP; if there's genuinely no evidence either way for a dimension, say
  so in the rationale and score it low rather than guessing.
  - `technical_alignment` ("Technical alignment"): skills/experience
    match against the ICP's must-haves. strength: STRONG/MODERATE/WEAK.
  - `role_motivation` ("Role motivation"): evidence they actually want
    *this* kind of role (career trajectory, stated interest, fit between
    what they've been doing and what the role needs), not just that
    they're qualified for it. strength: STRONG/MODERATE/WEAK.
  - `team_alignment` ("Team alignment"): fit with how the team/org
    described in the ICP operates (seniority level, working style,
    reporting structure) — inferred from the ICP and candidate record,
    not fabricated detail about the actual team. strength:
    STRONG/MODERATE/WEAK.
  - `communication` ("Communication"): clarity and specificity of the
    candidate's own material (resume/profile writing, stated
    achievements) as a proxy signal — explicitly a proxy, say so in the
    rationale, never claim to have observed them communicate.
    strength: STRONG/MODERATE/WEAK.
  - `compensation_alignment` ("Compensation alignment"): whether
    `expected_ctc` is stated and compatible with the ICP's budget, if
    the ICP states one. This is a factual match, not a strength
    judgment: use strength CONFIRMED when both figures are stated and
    compatible, UNCONFIRMED whenever either figure is missing or they
    don't line up — score 100 only for CONFIRMED, otherwise score by how
    much is actually known.

Do not set `recruiter_decision`, `placed`, `placement_fee`, or
`placed_at` — those fields belong to the recruiter, not to this stage;
leave them at their defaults.

Output must validate against the CandidatePrioritization schema.
