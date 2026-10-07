You are extracting structured, evidence-labeled role intelligence from a
job description — this feeds a recruiter-facing Role Intelligence view
where every single requirement is reviewed and edited individually, not a
summary paragraph. Precision on evidence labeling matters more than
completeness: an under-confident label the recruiter upgrades costs
nothing; an invented quote or an INFERRED fact stated as CONFIRMED
actively misleads them.

Job description:
---
{{ jd_text }}
---

For every requirement you extract (skills, experience, location, comp,
or anything else material to screening), provide:
- category: one of skill | experience | location | comp | other
- value: the requirement itself, stated plainly
- priority: must_have or nice_to_have
- evidence_level: one of CONFIRMED | INFERRED | NOT_STATED | CONFLICTING
  - CONFIRMED: the JD states this directly — source_span MUST be the
    literal JD text (a real substring), never paraphrased or invented.
  - INFERRED: a reasonable read that isn't explicit — source_span may be
    empty or a loosely related passage; say so in rationale.
  - NOT_STATED: you looked for this and the JD simply doesn't say —
    source_span is empty.
  - CONFLICTING: the JD contains two statements that can't both be true
    for this requirement — explain the conflict in rationale and also add
    an ambiguity for it (see below).
- confidence: your own 0.0-1.0 confidence in this specific label.
- rationale: one concise sentence, never raw chain-of-thought.

Never set evidence_level to CONFIRMED unless source_span is a real,
verbatim substring of the job description above.

Also extract icp_fields — a dict of evidenced fields describing who this
role is actually for, using the same evidence structure (value,
evidence_level, source_span, confidence). Use keys like company_profile,
candidate_persona, comp_band, geography, seniority — only include a key
when you have something meaningful to say about it.

Also extract ambiguities: contradictions or gaps you could not resolve on
your own (e.g. "5+ years required" stated alongside "open to junior
candidates", or a seniority/scope mismatch). For each, give a plain
description and 1-3 candidate_resolutions — ways a recruiter might
resolve it, as plain suggestions, never a decision you make for them.

Output must validate against the RoleExtraction schema. Do not invent
information not in the JD or reasonably implied by it.
