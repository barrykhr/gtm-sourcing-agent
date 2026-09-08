Build an Ideal Candidate Profile (ICP) from the structured JD and hiring
manager calibration sheet below.

Structured JD:
---
{{ job_description_json }}
---

Hiring manager calibration:
---
{{ calibration_json }}
---

Cover: target background, relevant companies, relevant industries,
relevant titles, adjacent titles, geography, seniority, typical career
progression, customer segment, product environment, relevant metrics,
relevant accomplishments, likely motivations, likely objections, and
transferable backgrounds.

Then separate every criterion into exactly one bucket:
MUST_HAVE, NICE_TO_HAVE, TRANSFERABLE, or DISQUALIFIER. A criterion should
appear in exactly one bucket — if you're tempted to put it in two, that's
a sign it needs to be split into two more precise criteria.

Output must validate against the IdealCandidateProfile schema.
