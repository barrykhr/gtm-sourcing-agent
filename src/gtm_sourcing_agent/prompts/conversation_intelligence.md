Extract structured conversation intelligence from this candidate's
communication log — the same log a rolling prose summary is written
from elsewhere, but here every field is its own structured claim.

Candidate:
---
{{ candidate_json }}
---

Communication log, oldest first (each entry has a channel, direction,
the recruiter's own content/notes, and — for calls — a transcript if one
was entered):
---
{{ entries_json }}
---

For every field below, use only what the log actually states. Leave a
free-text field empty if it was never discussed — do not infer a number
or a fact from title, seniority, or anything outside the log itself:

- current_compensation, expected_compensation, notice_period, location,
  relocation_willingness: verbatim or a faithful paraphrase of what the
  candidate said, exactly as in the log.
- relevant_experience: relevant experience the candidate raised in
  conversation (distinct from resume-derived evidence you have not seen
  here).
- leadership: anything the candidate said about managing/leading people
  or projects; empty if not discussed.
- motivation: why they're engaging with this move, in their own stated
  terms — not your inference about what a "typical" candidate wants.

interest_level: one of "High", "Medium", "Low", or "Insufficient
evidence" — only pick High/Medium/Low if the log actually supports it
(explicit enthusiasm/hesitation, not just polite replies); default to
"Insufficient evidence" rather than guessing from tone alone.

concerns: hesitations or worries the candidate raised themselves.
risks: your own risk read for the recruiter (e.g. a pattern across
multiple messages, a mismatch between stated interest and behavior) —
distinct from concerns, which are the candidate's own words.
unanswered_questions: questions raised by either side that the log shows
were never answered.

recommendation: a concrete next step (e.g. "Move to interview", "Wait
for compensation expectations before proceeding") grounded in the above
— or literally "Insufficient evidence" if the log is too thin to
recommend anything yet. Never pad this with a generic recommendation to
avoid saying the evidence is thin.

Output must validate against the ConversationIntelligence schema.
