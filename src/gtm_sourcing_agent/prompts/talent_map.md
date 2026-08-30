Build a talent-market map and title intelligence from the ICP below. Do
this before any candidate search — the map is the plan, not a byproduct
of searching.

ICP:
---
{{ icp_json }}
---

Target companies: judge every one against the same four dimensions —
product (what they actually build/sell), business segment (SMB / mid-market
/ enterprise, B2B / B2C, etc.), customer base (who buys it — industry,
size, buyer persona), and industry. This is the one yardstick for every
tier; a company's tier is a direct consequence of how many of these four
it shares with the role, not a separate judgment call:

- TIER 1 (direct talent): shares most or all four dimensions — someone
  doing essentially this same job, selling/building essentially the same
  thing, to essentially the same buyer. The closest, least-adaptation-needed
  hires.
- TIER 2 (adjacent talent): shares some of the four (commonly 2-3) — e.g.
  same industry and customer base but a different product line, or the
  same product category sold into a different segment. Real transferable
  skill, some ramp-up expected.
- TIER 3 (transferable talent): shares few of the four (commonly 1-2) but
  is still a legitimate source — comparable scale, complexity, or operating
  environment from further afield. The "wouldn't have thought of that, but
  it makes sense" companies, not a random scattering.

For every target company, set `match_dimensions` to exactly which of the
four (product / business_segment / customer_base / industry) it actually
shares — this is what determines the tier, so it must be consistent with
the tier assigned. Do not assume direct competitors are automatically the
best source — prioritize the four dimensions above over brand-name
competitor overlap; a household-name "competitor" that's misaligned on
segment or customer base is a worse source than a smaller company that
matches all four.

Give real breadth, not a token few: at least 5 companies in each tier
(15+ total), covering different angles within each tier rather than
minor variations on the same company. Thin coverage here means a
recruiter runs out of sourcing targets after a day.

For every target company also give: why it's relevant (in prose, tying
back to the match_dimensions), which roles to target there, what type of
talent likely exists there, which seniority levels to target, and the
potential limitations of that pool.

Title intelligence: generate exact target titles, alternative titles,
previous titles (what this person was likely called one step back),
adjacent titles, common market terminology, competitor-specific titles,
and geography-specific title variants. Do not rely on the JD's title
alone — think about how the market actually labels this job.

Output must validate against the TalentMap schema.
