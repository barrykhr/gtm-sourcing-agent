"""Feature 01's "Create Role" extraction stage: a JD -> structured,
evidence-labeled requirements/ICP fields/ambiguities (see
docs/TALYN_V2_ARCHITECTURE.md §3/§8 step 3). DB-only, same category as
workload_planning.py/conversation_summary.py — RoleRequirement/RoleICP/
RoleAmbiguity are db_storage-only concepts with no file-backend
equivalent, so this has no `storage_backend=` kwarg and no CLI pipeline
entry.

Distinct from stages/intake.py (which still produces the existing
JobDescription JobSection blob, untouched by this feature): this is the
new, granular replacement the Role Intelligence view reads from. The two
coexist until a later feature migrates downstream stages onto this model
(see architecture doc §11, risk #1)."""

from .. import agent_observability, llm_client, role_intelligence
from ..models.role_intelligence import RoleExtraction


def run(role_id: str, jd_text: str, *, created_by: str = "ai", user_email: str = "") -> dict:
    prompt = llm_client.render_prompt("role_intelligence_extraction.md", jd_text=jd_text)

    with agent_observability.timed_tool_call(
        role_id=role_id, user_email=user_email, tool_name="extract_role_intelligence",
        input_summary=f"jd_text ({len(jd_text)} chars)",
    ) as obs:
        def _capture_usage(usage):
            obs["model"] = llm_client.DEFAULT_MODEL
            obs["input_tokens"] = usage.input_tokens
            obs["output_tokens"] = usage.output_tokens

        result = llm_client.generate(
            prompt, RoleExtraction, stage="role_intelligence_extraction", on_usage=_capture_usage,
        )
        obs["output_summary"] = (
            f"{len(result.requirements)} requirements, {len(result.icp_fields)} icp fields, "
            f"{len(result.ambiguities)} ambiguities"
        )

    # Anti-hallucination guardrail (Architecture §5): a requirement cannot
    # claim CONFIRMED evidence with a source_span that isn't actually in
    # the JD — downgrade rather than trust an invented quote.
    requirements = []
    for r in result.requirements:
        d = r.model_dump()
        if d["evidence_level"] == "CONFIRMED" and (not d["source_span"] or d["source_span"] not in jd_text):
            d["evidence_level"] = "INFERRED"
            d["rationale"] = (d["rationale"] + " [downgraded: source_span not found verbatim in JD]").strip()
        requirements.append(d)

    icp_fields = {}
    for key, field in result.icp_fields.items():
        d = field.model_dump()
        if d["evidence_level"] == "CONFIRMED" and (not d["source_span"] or d["source_span"] not in jd_text):
            d["evidence_level"] = "INFERRED"
        icp_fields[key] = d

    ambiguities = [a.model_dump() for a in result.ambiguities]

    return role_intelligence.save_extraction(
        role_id, requirements=requirements, icp_fields=icp_fields, ambiguities=ambiguities,
        created_by=created_by,
    )
