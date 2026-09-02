Structure the candidate source material below into a candidate record.
This stage never invents information and never infers a specific
achievement, metric, or fact that isn't supported by the source text.

ICP (for fit context only — do not let it bias what you report as fact):
---
{{ icp_json }}
---

Candidate source material (resume text, LinkedIn profile text, recruiter
notes — whatever was provided):
---
{{ candidate_source_text }}
---

Role family for evaluation-criteria context (sales / SDR-BDR / customer
success / KAM / product / engineering / other): {{ role_family }}
Apply the role-appropriate evaluation lens (e.g. for sales: new business
vs. expansion, segment, quota/attainment, ACV/TCV, deal size, sales
cycle, win rate; for CS: ARR under management, GRR/NRR, churn, portfolio
size; for engineering: languages, architecture, scale, ownership level —
adapt to what the role family actually is, this list is illustrative not
exhaustive).

For every achievement, metric, and piece of evidence-of-fit, label it:
- VERIFIED — explicitly stated in the source material
- NOT_STATED — you looked for it and it is not in the source material
  (use this instead of omitting the field so gaps are visible)
- INFERRED — a reasonable read that is not explicitly stated (e.g.
  seniority implied by title, but "led" isn't the same as "owned")
Never mark something VERIFIED unless it is explicitly in the source text.

Also report: missing information (what you'd need to properly assess
fit), concerns, and a recommended next action (e.g. "screen", "needs
more research", "pass for now with reason").

If the source material states current CTC, expected CTC, or notice
period, capture them verbatim in `current_ctc`, `expected_ctc`, and
`notice_period` (free text — currency, period, and format vary by
source, don't normalize or guess a currency). Leave a field empty if the
source material never mentions it — do not estimate or invent a number.

This is very often a resume, where contact information matters as much
as evidence of fit. Extract into `email` and `phone` exactly as written
in the source (don't reformat a phone number or guess a country code).
For `total_experience`, use what the source states directly, or what is
unambiguously computable from the source's own stated employment dates
(e.g. two roles with start/end years given) — never estimate from title
or seniority alone. Leave `email`, `phone`, and `total_experience` empty
if the source doesn't support them — the product shows "Not available"
for an empty field, which is correct and expected; never fill one in to
avoid an empty result.

Output must validate against the Candidate schema.
