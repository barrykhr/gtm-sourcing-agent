Analyse the sourcing funnel below and recommend an intervention.

Funnel counts by stage for this role:
---
{{ funnel_counts_json }}
---

Compute contact rate, response rate, positive response rate, screen
conversion, HM conversion, final conversion, offer rate, offer
acceptance rate, and joining rate, wherever the denominator is available
(if a rate can't be computed from the given counts, leave it null rather
than guessing).

Identify the single stage with the biggest leakage (largest relative
drop-off) and recommend one concrete intervention to address it. Ground
the recommendation in the specific numbers, not generic advice.

Output must validate against the FunnelMetrics schema.
