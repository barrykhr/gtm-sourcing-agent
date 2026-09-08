Generate the standard interview question set for this role — asked of
every candidate who reaches a screen/interview, not tailored to one
specific candidate's record (a separate, per-candidate step already
exists for that). These must be grounded in *this* role's actual
requirements, not a generic template — a different JD should produce
different questions.

ICP (must-have / nice-to-have / disqualifier):
---
{{ icp_json }}
---

Calibration (hiring manager's red flags and what "looks good on paper
but reject" means for this role):
---
{{ calibration_json }}
---

Questions already asked in earlier generations for this same role — do
not repeat these, and do not lightly rephrase one of them into a
near-duplicate. Find genuinely different angles into the same ICP and
calibration material instead:
---
{{ prior_questions_text }}
---

Produce at least 10 questions in total across the three groups below —
thin coverage (one or two questions per group) is not acceptable; go
deep enough into the ICP's must-haves and the calibration's red flags
that a hiring manager could run a full interview loop from this set
alone.

For every question, state `why_it_matters` — which must-have, red flag,
or ambiguity from the material above it's meant to validate. A question
with no clear reason to ask is not useful here.

Group into:
- `core_questions`: ask every candidate for this role — grounded in the
  ICP's must-haves.
- `role_specific_questions`: specific to what makes *this* role
  different (domain, segment, deal size, tech stack — whatever the
  ICP/calibration actually calls out), not questions that would fit any
  role in this function.
- `red_flag_questions`: directly probe the calibration's red flags and
  "looks good on paper but reject" patterns.

Output must validate against the RoleInterviewQuestions schema.
