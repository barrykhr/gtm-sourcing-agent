Draft an outreach sequence for the candidate below, using only verified
information. Never fabricate personalization. Avoid excessive praise. Do
not copy the job description into the message.

Candidate record (use only facts labeled VERIFIED for personalization;
INFERRED or NOT_STATED facts must not be presented as known about the
candidate):
---
{{ candidate_json }}
---

Role summary (for context on the opportunity — do not paste this into
the message):
---
{{ job_description_json }}
---

Focus each message on: why them (specific, verified), why this role, why
now. Keep messages concise, human, specific, and non-generic.

Produce: a LinkedIn connection note, a LinkedIn InMail, an email, and two
follow-ups.

List in `personalization_basis` exactly which VERIFIED facts you actually
used. If the candidate record has no VERIFIED facts strong enough to
personalize against, say so by leaving `personalization_basis` empty and
writing an honest, still-non-generic-but-less-personalized draft — do not
invent a fact to fill the gap.

Output must validate against the OutreachSequence schema.
