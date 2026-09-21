A recruiter is asking a question about this specific interview. Answer
ONLY from the material below — the job's requirements, the candidate's
resume claims, and what was actually said in this transcript. Never
invent an answer, never speculate about what the candidate "probably"
meant, and never treat a resume claim as something the candidate said
in this interview.

If the answer genuinely isn't in this material, set `unable_to_answer`
to true and say so in `answer` — do not guess.

Must-have requirements:
---
{{ must_have_json }}
---

Nice-to-have requirements:
---
{{ nice_to_have_json }}
---

Resume claims (context only, not something said in this interview):
---
{{ resume_claims }}
---

What this interview's evidence scorecard already found (context; you
may reference it, but re-check the transcript itself for anything
specific):
---
{{ competencies_json }}
---

Interview transcript (numbered by segment — cite segments by their [N]
number, never by copying their text):
---
{{ transcript }}
---

Recruiter's question:
---
{{ question }}
---

Give a direct answer in `answer`. In `citations`, list every transcript
segment `{segment_index}` your answer actually relies on — every
`segment_index` must be a real `[N]` number from the transcript above.
If your answer draws only on the JD or resume claims (not the
transcript), citations can be empty — but say clearly in the answer that
it's not something the candidate discussed in this interview.

Output must validate against the AskInterviewAnswer schema.
