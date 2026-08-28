Generate multiple distinct search strategies from the talent map below.
Never produce one giant boolean string unless there is a genuine reason to
— start broad, and produce strategies the recruiter can run, review
results from, and progressively narrow.

Talent map:
---
{{ talent_map_json }}
---

Generate strategies across: broad, targeted, competitor, adjacent
talent, transferable talent, geography-specific, and seniority-specific.
Skip a category only if it's genuinely not applicable to this role —
say why in that case rather than silently omitting it.

For each strategy, state its purpose (what it's intended to capture) and
produce, where applicable: a LinkedIn boolean string, a Google X-ray
query, a Naukri search string, a GitHub search (for technical roles), and
any other relevant channel (community, industry-specific database, etc).
Leave a field empty rather than forcing an irrelevant query into it.

Output must validate against the TalentMap schema's search_strategies
list (a list[SearchStrategy]).
