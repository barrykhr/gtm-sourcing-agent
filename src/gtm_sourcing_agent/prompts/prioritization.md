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

For A and B tiers specifically, be explicit about: why they fit, what is
unknown (gaps in the evidence, not just weaknesses), and what to validate
in screening. For C and D, still give a rationale — a low tier without a
reason is not useful to the recruiter and looks like an unexplained
auto-reject, which this system does not do.

Do not set `recruiter_decision` — that field belongs to the recruiter,
not to this stage; leave it null.

Output must validate against the CandidatePrioritization schema.
