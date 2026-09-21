Map this job's requirements against what was actually said in this
interview transcript. This is evidence extraction, not a hiring
decision — you are telling the recruiter what was demonstrated, what
wasn't, and what still needs validation. Never recommend hiring or
rejecting this candidate.

The single most important rule: **a resume claim is not interview
evidence.** The "Resume claims" section below is what the candidate's
resume/profile already said about them, before this interview happened —
useful context for what to expect, but it is not proof of anything said
in this conversation. Only the CANDIDATE's own words in the transcript
below count as evidence for a competency. If the resume claims a skill
but the transcript never discusses it, that competency's status is
"Needs validation" (or "Not discussed" if the resume didn't even
mention it) — never "Strong evidence".

Must-have requirements:
---
{{ must_have_json }}
---

Nice-to-have requirements:
---
{{ nice_to_have_json }}
---

Resume claims (context only, NOT evidence):
---
{{ resume_claims }}
---

Interview transcript (numbered by segment — RECRUITER asked, CANDIDATE
answered; cite segments by their [N] number, never by copying their
text):
---
{{ transcript }}
---

For EVERY must-have and nice-to-have requirement above, produce one
`InterviewCompetencyResult`:
- `competency`: the specific requirement, in your own concise words.
- `category`: "must_have" or "nice_to_have", matching which list it came from.
- `status`: exactly one of
  - "Strong evidence" — the candidate's own words clearly demonstrate this.
  - "Needs validation" — the resume claims it, or the transcript touches
    it only vaguely/partially, but it isn't clearly confirmed.
  - "Not discussed" — neither the transcript nor the resume ever addresses it.
  - "Insufficient evidence" — it came up, but too briefly or ambiguously to judge.
- `rationale`: 1-2 sentences citing what was or wasn't actually said —
  never citing the resume as if it were the transcript.
- `evidence`: a list of `{segment_index, note}` for every transcript
  segment that supports this status. Leave empty for "Not discussed".
  `segment_index` must be one of the `[N]` numbers from the transcript
  above — never invent one.

Then produce `follow_up_questions`: a short list of concrete questions
worth asking in a follow-up round, focused on whatever is still "Needs
validation" or "Not discussed" — not generic interview questions, ones
that would specifically close the gaps you just found. Each needs a
`rationale` (what gap it closes) and, where relevant, `related_competency`.

If the transcript is short or the interview clearly only covered part of
the role, it is completely correct for most competencies to end up "Not
discussed" — do not stretch a single passing comment into "Strong
evidence" to make the scorecard look more complete than the conversation
actually was.

Output must validate against the InterviewIntelligenceResult schema.
