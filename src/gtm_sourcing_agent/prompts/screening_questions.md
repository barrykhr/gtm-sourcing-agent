Generate recruiter screening questions for the candidate below. Questions
must validate specific facts and unknowns from this candidate's
prioritization record — not ask them to repeat their resume.

Bad: "Tell me about your sales experience."
Good: "You've mentioned owning enterprise accounts. What was your annual
quota, what did you achieve against it, and what was the typical ACV?"

Candidate record:
---
{{ candidate_json }}
---

Prioritization record (use `what_is_unknown` and `what_to_validate`
directly — these are the specific gaps this screen needs to close):
---
{{ prioritization_json }}
---

Hiring manager calibration (for red-flag context):
---
{{ calibration_json }}
---

Produce: must-ask questions (targeting the specific unknowns above),
nice-to-ask questions, and red-flag follow-ups (questions that would
surface the red flags from the calibration sheet if they apply to this
candidate).

Output must validate against the ScreeningQuestionSet schema.
