Summarize this recruiting interview transcript into a recruitment-specific
summary — not a generic meeting summary. Speaker labels are "RECRUITER"
and "CANDIDATE"; treat only the CANDIDATE's own turns as evidence about
the candidate.

Transcript:
---
{{ transcript_text }}
---

Write:
- `overview`: 2-4 sentences on what was actually discussed and demonstrated.
- `key_experience`: specific experience the candidate described, in their
  own terms — not inferred or assumed.
- `technical_skills`: specific tools/technologies/skills the candidate
  meaningfully discussed with real context, not just named in passing.
- `examples_provided`: concrete examples, projects, or stories the
  candidate actually gave.
- `areas_not_discussed`: topics that seem relevant to a hiring decision
  but never came up in this transcript — this is often the most useful
  field for the recruiter.
- `potential_followups`: a short list of what's worth asking about next
  time, based on gaps or vague answers in this conversation.

Never invent a claim the candidate didn't make. If something wasn't
discussed, say so in `areas_not_discussed` rather than guessing at it.

Output must validate against the InterviewSummaryResult schema.
