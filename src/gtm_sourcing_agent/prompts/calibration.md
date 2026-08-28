You are preparing a Hiring Manager Calibration Sheet from a structured
job description. This sheet is used to align with the hiring manager
*before* sourcing, and to keep evaluation consistent across candidates.

Structured JD:
---
{{ job_description_json }}
---

Produce: 5-10 must-have criteria, 5-10 evaluation criteria, a strong
candidate definition, an acceptable candidate definition, a weak candidate
definition, red flags, transferable profiles worth considering, profiles
that look good on paper but should be rejected (and why — this is the
category recruiters get wrong most often under volume pressure), and
interview questions required to validate the requirements flagged
`ambiguous` in the JD analysis.

If the requirements look unrealistic for the market (e.g. compensation
band vs. seniority mismatch, or a requirement combination that basically
no one meets), say so explicitly in `unrealistic_requirements_flag` with
your reasoning — do not blindly encode an unrealistic JD into the
calibration sheet as if it were achievable.

Output must validate against the HiringManagerCalibration schema.
