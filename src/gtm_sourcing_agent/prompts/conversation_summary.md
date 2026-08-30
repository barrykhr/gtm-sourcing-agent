Summarize this candidate's communication history so far — every logged
email, WhatsApp message, and phone call in one place, in chronological
order. This is a recap for a recruiter picking the relationship back up,
not a transcript restatement: focus on where things actually stand.

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

Write `summary` as 2-4 sentences: tone of the relationship, what's been
discussed, where it currently stands. Base it only on what the log
entries actually say — if a call's transcript is missing, don't guess
what was discussed on it beyond its logged notes.

List in `open_items` any concrete unresolved things a recruiter would
need to follow up on (e.g. "said they'd share updated CTC by Friday",
"waiting on their manager's decision") — only ones the log actually
supports, not assumed next steps. Leave it empty if nothing is open.

Output must validate against the ConversationSummaryResult schema.
