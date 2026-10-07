"""Phase 3: chat orchestrator — a Claude tool-use loop over the existing
stage functions, job-scoped (docs/product-plan.md Phase 3; Blueprint §13-14/§J).

The orchestrator's only job is to turn natural language into calls to code
that already exists — the same stage functions the UI buttons call, plus
read-only lookups. It never mutates state directly for anything that
changes established criteria after candidates have been evaluated:
`propose_hiring_profile_edit` is read-only and returns a proposal; the
actual mutation (`apply_hiring_profile_edit`) is plain deterministic Python
that only runs when the recruiter explicitly clicks confirm in the UI
(api.py's /chat/confirm route) — the LLM is never the thing that writes
that particular change, only the thing that understands the request and
explains its impact. See Architecture §1.1/§1.2 (no automated rejection,
evidence discipline) — this is the same "recruiter is the checkpoint"
principle applied to hiring-profile edits specifically.

Testing note, more load-bearing here than in any earlier phase: there is
no way to check *tool-selection quality* — whether "remove Fabric as a
mandatory requirement" correctly triggers propose_hiring_profile_edit, or
"find me candidates like #17" correctly calls list_candidates first —
without real inference. `_run_tool_loop` is the one function that talks to
the Anthropic API; every test in this repo mocks it directly and instead
verifies that tool execution, confirmation-gating, and history persistence
are correct *given* a tool call the model made. TOOL_IMPLS (plain
functions, not the @beta_tool-wrapped closures) is what those tests call
directly, so they never depend on Anthropic SDK object internals.
"""

import json
from typing import Any

import anthropic

from . import db_storage, llm_client, role_intelligence
from .stages import calibration as calibration_stage
from .stages import candidate_analysis as candidate_analysis_stage
from .stages import funnel as funnel_stage
from .stages import icp as icp_stage
from .stages import intake as intake_stage
from .stages import outreach as outreach_stage
from .stages import prioritization as prioritization_stage
from .stages import screening as screening_stage
from .stages import search_strategy as search_strategy_stage
from .stages import talent_map as talent_map_stage

SYSTEM_PROMPT = (
    "You are the recruiter's assistant inside Talyn, scoped to "
    "one specific job — the recruiter never needs to restate which job or which "
    "candidate they mean if it was mentioned earlier in this conversation. Use "
    "the tools to answer questions and take the actions the recruiter asks for; "
    "don't describe what a tool would do instead of calling it. Never state a "
    "candidate fact as verified unless the underlying data labels it VERIFIED — "
    "pass through NOT_STATED/INFERRED labels honestly. When the recruiter asks "
    "to change a hiring-profile requirement (must-have, nice-to-have, "
    "disqualifier), always call propose_hiring_profile_edit rather than "
    "describing the change yourself — that tool does not apply anything, it "
    "only prepares a proposal the recruiter approves or declines through the "
    "product UI. Never treat a vague or ambiguous reply as approval. For the "
    "role's structured requirements/ICP/ambiguities (Role Intelligence), use "
    "get_role/get_requirements/get_icp/get_ambiguities/get_role_history to "
    "read, and always use the matching propose_* tool — never apply a change "
    "yourself — for add_requirement/update_requirement/remove_requirement/"
    "change_requirement_priority/update_icp/resolve_ambiguity. Every "
    "requirement and ICP field carries its own evidence_level — pass through "
    "CONFIRMED/INFERRED/NOT_STATED/CONFLICTING labels honestly, never state "
    "an INFERRED or NOT_STATED fact as CONFIRMED."
)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# ── tool implementations (plain functions — what tests call directly) ────


def _analyze_jd(role_id: str, storage_backend: Any, jd_text: str) -> str:
    return intake_stage.run(role_id, jd_text, storage_backend=storage_backend).model_dump_json()


def _build_hiring_profile(role_id: str, storage_backend: Any) -> str:
    calibration_stage.run(role_id, storage_backend=storage_backend)
    return icp_stage.run(role_id, storage_backend=storage_backend).model_dump_json()


def _build_talent_map(role_id: str, storage_backend: Any) -> str:
    return talent_map_stage.run(role_id, storage_backend=storage_backend).model_dump_json()


def _create_sourcing_strategy(role_id: str, storage_backend: Any) -> str:
    return search_strategy_stage.run(role_id, storage_backend=storage_backend).model_dump_json()


def _list_candidates(role_id: str, storage_backend: Any) -> str:
    state = storage_backend.load_role(role_id)
    candidates = state.get("candidates") or {}
    prioritizations = state.get("prioritizations") or {}
    rows = [
        {
            "candidate_id": cid,
            "name": c.get("name"),
            "current_title": c.get("current_title"),
            "current_company": c.get("current_company"),
            "tier": (prioritizations.get(cid) or {}).get("tier"),
        }
        for cid, c in candidates.items()
    ]
    return json.dumps(rows)


def _get_candidate(role_id: str, storage_backend: Any, candidate_id: str) -> str:
    state = storage_backend.load_role(role_id)
    candidate = (state.get("candidates") or {}).get(candidate_id)
    if candidate is None:
        return json.dumps({"error": f"candidate '{candidate_id}' not found"})
    prioritization = (state.get("prioritizations") or {}).get(candidate_id)
    return json.dumps({"candidate": candidate, "prioritization": prioritization})


def _prioritize_candidate(role_id: str, storage_backend: Any, candidate_id: str) -> str:
    return prioritization_stage.run(role_id, candidate_id, storage_backend=storage_backend).model_dump_json()


def _generate_screening_questions(role_id: str, storage_backend: Any, candidate_id: str) -> str:
    return screening_stage.run(role_id, candidate_id, storage_backend=storage_backend).model_dump_json()


def _generate_outreach(role_id: str, storage_backend: Any, candidate_id: str) -> str:
    return outreach_stage.run(role_id, candidate_id, storage_backend=storage_backend).model_dump_json()


def _get_funnel_report(role_id: str, storage_backend: Any) -> str:
    return funnel_stage.report(role_id, storage_backend=storage_backend).model_dump_json()


PROFILE_FIELDS = ("must_have", "nice_to_have", "disqualifier")


def _propose_hiring_profile_edit(
    role_id: str, storage_backend: Any, field: str, action: str, value: str
) -> str:
    """Read-only by design — see module docstring. Returns a proposal for
    the API layer to surface as a [YES/NO] confirmation, never applies it."""
    if field not in PROFILE_FIELDS:
        return json.dumps({"error": f"unknown field '{field}', must be one of {PROFILE_FIELDS}"})
    if action not in ("add", "remove"):
        return json.dumps({"error": f"unknown action '{action}', must be 'add' or 'remove'"})
    icp = storage_backend.require_section(role_id, "icp")
    current = icp.get(field, [])
    if action == "remove" and value not in current:
        return json.dumps({"error": f"'{value}' is not currently in {field}"})
    if action == "add" and value in current:
        return json.dumps({"error": f"'{value}' is already in {field}"})
    evaluated_count = len(storage_backend.load_role(role_id).get("prioritizations") or {})
    verb = "Remove" if action == "remove" else "Add"
    prep = "from" if action == "remove" else "to"
    proposal = {
        "kind": "hiring_profile_edit",
        "field": field,
        "action": action,
        "value": value,
        "description": f'{verb} "{value}" {prep} {field.replace("_", " ")}.',
        "impact": (
            f"{evaluated_count} candidate(s) already evaluated against the current "
            f"criteria may need re-evaluation."
            if evaluated_count
            else "No candidates evaluated yet for this job — safe to apply."
        ),
    }
    return json.dumps({"proposal": proposal})


def apply_hiring_profile_edit(
    role_id: str, field: str, action: str, value: str, *, storage_backend: Any = db_storage
) -> dict[str, Any]:
    """The actual mutation. Deterministic, no LLM involved — only called by
    api.py's /chat/confirm route after explicit recruiter approval, never
    by the orchestrator's tool loop directly."""
    icp = storage_backend.require_section(role_id, "icp")
    current = list(icp.get(field, []))
    if action == "add" and value not in current:
        current.append(value)
    elif action == "remove" and value in current:
        current.remove(value)
    icp[field] = current
    storage_backend.merge_section(role_id, "icp", icp)
    return icp


# ── Feature 01: role intelligence tool implementations ───────────────
# Same testing seam as everything above: plain functions TOOL_IMPLS
# exposes directly, @beta_tool wrappers only added in build_tools_for_job.
# Every mutating one is propose-only here (role_intelligence.propose_*) —
# the actual apply_* call only ever happens from api.py's /chat/confirm
# route after explicit recruiter approval, same discipline as
# apply_hiring_profile_edit above (see TALYN_V2_ARCHITECTURE.md §6).


def _get_role(role_id: str, storage_backend: Any) -> str:
    return json.dumps(role_intelligence.get_role(role_id))


def _get_requirements(role_id: str, storage_backend: Any) -> str:
    return json.dumps(role_intelligence.get_requirements(role_id))


def _propose_add_requirement(
    role_id: str, storage_backend: Any, category: str, value: str, priority: str,
    evidence_level: str = "NOT_STATED", source_span: str = "",
) -> str:
    try:
        proposal = role_intelligence.propose_add_requirement(
            role_id, category=category, value=value, priority=priority,
            evidence_level=evidence_level, source_span=source_span,
        )
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"proposal": proposal})


def _propose_update_requirement(role_id: str, storage_backend: Any, requirement_id: int, **fields: Any) -> str:
    fields = {k: v for k, v in fields.items() if v is not None}
    try:
        proposal = role_intelligence.propose_update_requirement(role_id, requirement_id, **fields)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"proposal": proposal})


def _propose_remove_requirement(role_id: str, storage_backend: Any, requirement_id: int) -> str:
    try:
        proposal = role_intelligence.propose_remove_requirement(role_id, requirement_id)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"proposal": proposal})


def _propose_change_requirement_priority(role_id: str, storage_backend: Any, requirement_id: int, priority: str) -> str:
    try:
        proposal = role_intelligence.propose_change_requirement_priority(role_id, requirement_id, priority)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"proposal": proposal})


def _get_icp(role_id: str, storage_backend: Any) -> str:
    return json.dumps(role_intelligence.get_icp(role_id))


def _propose_update_icp(role_id: str, storage_backend: Any, fields_json: str) -> str:
    try:
        fields = json.loads(fields_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "fields_json must be a JSON object"})
    try:
        proposal = role_intelligence.propose_update_icp(role_id, fields)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"proposal": proposal})


def _get_ambiguities(role_id: str, storage_backend: Any) -> str:
    return json.dumps(role_intelligence.get_ambiguities(role_id))


def _propose_resolve_ambiguity(
    role_id: str, storage_backend: Any, ambiguity_id: int, resolution_note: str,
) -> str:
    try:
        proposal = role_intelligence.propose_resolve_ambiguity(role_id, ambiguity_id, resolution_note=resolution_note)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"proposal": proposal})


def _generate_search_strategy(role_id: str, storage_backend: Any) -> str:
    return json.dumps(role_intelligence.generate_search_strategy(role_id))


def _get_role_history(role_id: str, storage_backend: Any) -> str:
    return json.dumps(role_intelligence.get_role_history(role_id))


TOOL_IMPLS = {
    "analyze_jd": _analyze_jd,
    "build_hiring_profile": _build_hiring_profile,
    "build_talent_map": _build_talent_map,
    "create_sourcing_strategy": _create_sourcing_strategy,
    "list_candidates": _list_candidates,
    "get_candidate": _get_candidate,
    "prioritize_candidate": _prioritize_candidate,
    "generate_screening_questions": _generate_screening_questions,
    "generate_outreach": _generate_outreach,
    "get_funnel_report": _get_funnel_report,
    "propose_hiring_profile_edit": _propose_hiring_profile_edit,
    "get_role": _get_role,
    "get_requirements": _get_requirements,
    "propose_add_requirement": _propose_add_requirement,
    "propose_update_requirement": _propose_update_requirement,
    "propose_remove_requirement": _propose_remove_requirement,
    "propose_change_requirement_priority": _propose_change_requirement_priority,
    "get_icp": _get_icp,
    "propose_update_icp": _propose_update_icp,
    "get_ambiguities": _get_ambiguities,
    "propose_resolve_ambiguity": _propose_resolve_ambiguity,
    "generate_search_strategy": _generate_search_strategy,
    "get_role_history": _get_role_history,
}

# Proposal "kind" strings (see role_intelligence.APPLY_BY_KIND) produced by
# the propose_* tools above — run_chat_turn checks a tool call's name
# against this set (not just the single hiring-profile-edit name) to
# decide whether its result is a pending_proposal.
_PROPOSAL_TOOL_NAMES = {
    "propose_hiring_profile_edit", "propose_add_requirement", "propose_update_requirement",
    "propose_remove_requirement", "propose_change_requirement_priority", "propose_update_icp",
    "propose_resolve_ambiguity",
}


# ── @beta_tool wrappers (what the real tool_runner sees) ─────────────────


def build_tools_for_job(role_id: str, storage_backend: Any = db_storage) -> list[Any]:
    """job_id is fixed context for the whole conversation (Blueprint §J) —
    bound here via closure, never a parameter the model fills in, so the
    model cannot address a different job than the one the recruiter is
    looking at."""
    from anthropic import beta_tool

    @beta_tool
    def analyze_jd(jd_text: str) -> str:
        """Run the JD intake stage: parse a job description into a structured
        record (company, role, must-haves, contradictions flagged, missing
        information). Use when the recruiter pastes a JD or asks you to
        analyse one.

        Args:
            jd_text: the full job description text to analyse.
        """
        return TOOL_IMPLS["analyze_jd"](role_id, storage_backend, jd_text)

    @beta_tool
    def build_hiring_profile() -> str:
        """Run hiring-manager calibration, then build the Ideal Candidate
        Profile (must-have / nice-to-have / transferable / disqualifier).
        Requires the JD to have been analysed first."""
        return TOOL_IMPLS["build_hiring_profile"](role_id, storage_backend)

    @beta_tool
    def build_talent_map() -> str:
        """Build the talent-market map: target companies by tier and title
        intelligence. Requires a hiring profile to exist first."""
        return TOOL_IMPLS["build_talent_map"](role_id, storage_backend)

    @beta_tool
    def create_sourcing_strategy() -> str:
        """Generate search strategies (boolean strings, X-ray queries) against
        the talent map. Requires a talent map to exist first."""
        return TOOL_IMPLS["create_sourcing_strategy"](role_id, storage_backend)

    @beta_tool
    def list_candidates() -> str:
        """List every candidate captured for this job: id, name, current
        role, and prioritization tier if one has been set. Call this before
        referring to a candidate by name or id if you haven't already seen
        the list this conversation."""
        return TOOL_IMPLS["list_candidates"](role_id, storage_backend)

    @beta_tool
    def get_candidate(candidate_id: str) -> str:
        """Get full detail for one candidate: achievements and evidence
        (each labeled VERIFIED, NOT_STATED, or INFERRED — never state one as
        fact if it isn't VERIFIED), and prioritization rationale if scored.

        Args:
            candidate_id: the candidate's id, from list_candidates.
        """
        return TOOL_IMPLS["get_candidate"](role_id, storage_backend, candidate_id)

    @beta_tool
    def prioritize_candidate(candidate_id: str) -> str:
        """Score/tier a candidate (A/B/C/D) against the hiring profile, with
        a rationale. This is a recommendation only — it never rejects a
        candidate; the recruiter decides.

        Args:
            candidate_id: the candidate's id, from list_candidates.
        """
        return TOOL_IMPLS["prioritize_candidate"](role_id, storage_backend, candidate_id)

    @beta_tool
    def generate_screening_questions(candidate_id: str) -> str:
        """Generate targeted screening questions for a candidate, based on
        what's unknown from their prioritization. Requires the candidate to
        be prioritized first.

        Args:
            candidate_id: the candidate's id, from list_candidates.
        """
        return TOOL_IMPLS["generate_screening_questions"](role_id, storage_backend, candidate_id)

    @beta_tool
    def generate_outreach(candidate_id: str) -> str:
        """Draft outreach (LinkedIn note, InMail, email, two follow-ups) for
        a candidate. Draft only — this never sends anything.

        Args:
            candidate_id: the candidate's id, from list_candidates.
        """
        return TOOL_IMPLS["generate_outreach"](role_id, storage_backend, candidate_id)

    @beta_tool
    def get_funnel_report() -> str:
        """Get sourcing funnel conversion metrics and the biggest leakage
        stage for this job."""
        return TOOL_IMPLS["get_funnel_report"](role_id, storage_backend)

    @beta_tool
    def propose_hiring_profile_edit(field: str, action: str, value: str) -> str:
        """Propose a change to the hiring profile's requirement lists. This
        does NOT apply the change — it only prepares a proposal for the
        recruiter to explicitly approve, because changing requirements after
        candidates have already been evaluated can invalidate their scores.
        Always call this instead of just describing the change, and let the
        recruiter approve or decline it through the product UI — never
        assume approval from an ambiguous reply.

        Args:
            field: one of "must_have", "nice_to_have", "disqualifier".
            action: "add" or "remove".
            value: the requirement text to add or remove, matching existing
                wording exactly for "remove".
        """
        return TOOL_IMPLS["propose_hiring_profile_edit"](role_id, storage_backend, field, action, value)

    # ── Feature 01: Role Intelligence tools ──────────────────────────

    @beta_tool
    def get_role() -> str:
        """Get this role's basic identity: title, role family, client, and
        lifecycle status."""
        return TOOL_IMPLS["get_role"](role_id, storage_backend)

    @beta_tool
    def get_requirements() -> str:
        """List this role's structured requirements — each with category,
        value, priority (must_have/nice_to_have), and evidence_level
        (CONFIRMED/INFERRED/NOT_STATED/CONFLICTING). This is the Role
        Intelligence view's source of truth, separate from the older
        hiring-profile must_have/nice_to_have free-text lists."""
        return TOOL_IMPLS["get_requirements"](role_id, storage_backend)

    @beta_tool
    def propose_add_requirement(
        category: str, value: str, priority: str, evidence_level: str = "NOT_STATED", source_span: str = "",
    ) -> str:
        """Propose adding a new requirement. Does NOT apply it — only
        prepares a proposal for the recruiter to approve or decline.

        Args:
            category: one of "skill", "experience", "location", "comp", "other".
            value: the requirement text.
            priority: "must_have" or "nice_to_have".
            evidence_level: one of "CONFIRMED", "INFERRED", "NOT_STATED",
                "CONFLICTING" — CONFIRMED only if source_span is a real
                quote from the JD; use NOT_STATED for a recruiter's own
                addition with no JD basis.
            source_span: literal JD text this came from, if any.
        """
        return TOOL_IMPLS["propose_add_requirement"](
            role_id, storage_backend, category, value, priority, evidence_level, source_span,
        )

    @beta_tool
    def propose_update_requirement(
        requirement_id: int, category: str | None = None, value: str | None = None,
        priority: str | None = None, evidence_level: str | None = None, source_span: str | None = None,
    ) -> str:
        """Propose editing an existing requirement's field(s). Does NOT
        apply it — only prepares a proposal for the recruiter to approve
        or decline. Only pass the fields that are actually changing.

        Args:
            requirement_id: the requirement's id, from get_requirements.
        """
        return TOOL_IMPLS["propose_update_requirement"](
            role_id, storage_backend, requirement_id, category=category, value=value,
            priority=priority, evidence_level=evidence_level, source_span=source_span,
        )

    @beta_tool
    def propose_remove_requirement(requirement_id: int) -> str:
        """Propose removing a requirement. Does NOT apply it — only
        prepares a proposal for the recruiter to approve or decline.

        Args:
            requirement_id: the requirement's id, from get_requirements.
        """
        return TOOL_IMPLS["propose_remove_requirement"](role_id, storage_backend, requirement_id)

    @beta_tool
    def propose_change_requirement_priority(requirement_id: int, priority: str) -> str:
        """Propose changing a requirement's priority between must_have and
        nice_to_have. Does NOT apply it — only prepares a proposal for the
        recruiter to approve or decline.

        Args:
            requirement_id: the requirement's id, from get_requirements.
            priority: "must_have" or "nice_to_have".
        """
        return TOOL_IMPLS["propose_change_requirement_priority"](role_id, storage_backend, requirement_id, priority)

    @beta_tool
    def get_icp() -> str:
        """Get this role's Ideal Candidate Profile fields (company_profile,
        candidate_persona, comp_band, geography, etc.), each with its own
        evidence_level."""
        return TOOL_IMPLS["get_icp"](role_id, storage_backend)

    @beta_tool
    def propose_update_icp(fields_json: str) -> str:
        """Propose updating one or more ICP fields. Does NOT apply it —
        only prepares a proposal for the recruiter to approve or decline.

        Args:
            fields_json: a JSON object mapping field name to
                {"value", "evidence_level", "source_span", "confidence"},
                e.g. '{"comp_band": {"value": "$120-150k OTE",
                "evidence_level": "CONFIRMED", "source_span": "...", "confidence": 0.9}}'.
        """
        return TOOL_IMPLS["propose_update_icp"](role_id, storage_backend, fields_json)

    @beta_tool
    def get_ambiguities() -> str:
        """List this role's open and resolved ambiguities — contradictions
        or gaps the extraction couldn't resolve on its own, each with
        candidate_resolutions the recruiter can choose from."""
        return TOOL_IMPLS["get_ambiguities"](role_id, storage_backend)

    @beta_tool
    def propose_resolve_ambiguity(ambiguity_id: int, resolution_note: str) -> str:
        """Propose resolving an ambiguity with a plain-text resolution note.
        Does NOT apply it — only prepares a proposal for the recruiter to
        approve or decline.

        Args:
            ambiguity_id: the ambiguity's id, from get_ambiguities.
            resolution_note: how it's being resolved, in plain language.
        """
        return TOOL_IMPLS["propose_resolve_ambiguity"](role_id, storage_backend, ambiguity_id, resolution_note)

    @beta_tool
    def generate_search_strategy() -> str:
        """Suggest boolean search strings and X-ray queries grounded in
        this role's current requirements and ICP. Read-only — does not
        persist anything; use create_sourcing_strategy for the full
        talent-mapping pipeline's own (separate) search strategy output."""
        return TOOL_IMPLS["generate_search_strategy"](role_id, storage_backend)

    @beta_tool
    def get_role_history() -> str:
        """Get this role's requirement/ICP/ambiguity change history —
        before/after/who/when/why for every edit."""
        return TOOL_IMPLS["get_role_history"](role_id, storage_backend)

    return [
        analyze_jd, build_hiring_profile, build_talent_map, create_sourcing_strategy,
        list_candidates, get_candidate, prioritize_candidate, generate_screening_questions,
        generate_outreach, get_funnel_report, propose_hiring_profile_edit,
        get_role, get_requirements, propose_add_requirement, propose_update_requirement,
        propose_remove_requirement, propose_change_requirement_priority, get_icp, propose_update_icp,
        get_ambiguities, propose_resolve_ambiguity, generate_search_strategy, get_role_history,
    ]


# ── the tool-use loop ──────────────────────────────────────────────────


def _run_tool_loop(
    model: str, system: str, tools: list[Any], messages: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """The only function in this module that talks to the real Anthropic
    API. Mutates and returns `messages` with the full transcript appended
    (plain dicts — content blocks are .model_dump()'d for JSON storage,
    since job_sections.data is a JSON column). Also returns the final
    assistant text and every tool call made this turn as
    [{"name", "input", "result"}, ...], so callers (and every test in this
    repo) never need to inspect Anthropic SDK response objects directly —
    see the module docstring for why that's the testing seam.
    """
    client = _get_client()
    runner = client.beta.messages.tool_runner(
        model=model, max_tokens=4096, system=system, tools=tools, messages=messages
    )

    tool_calls: list[dict[str, Any]] = []
    final_text = ""
    try:
        for message in runner:
            content = [block.model_dump() for block in message.content]
            messages.append({"role": "assistant", "content": content})
            for block in content:
                if block.get("type") == "text":
                    final_text = block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append({"name": block["name"], "input": block["input"], "id": block["id"]})

            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                messages.append(tool_response)
                for result_block in tool_response.get("content", []):
                    for tc in tool_calls:
                        if tc.get("id") == result_block.get("tool_use_id"):
                            tc["result"] = result_block.get("content")
    # Mirrors llm_client.generate()'s exception mapping — without this, the
    # copilot's own model call (as opposed to a stage call it delegates to)
    # crashed with a raw SDK exception that api.py's _run_stage doesn't
    # catch (it only catches ValueError/RuntimeError), surfacing as an
    # opaque 500 with no indication of what actually failed.
    except anthropic.AuthenticationError as e:
        raise RuntimeError("Anthropic API authentication failed — check ANTHROPIC_API_KEY.") from e
    except anthropic.PermissionDeniedError as e:
        raise RuntimeError("Anthropic API key lacks required permissions.") from e
    except anthropic.NotFoundError as e:
        raise RuntimeError(f"Anthropic model '{model}' not found.") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError("Anthropic API rate limit hit — retry later.") from e
    except anthropic.BadRequestError as e:
        raise RuntimeError(f"Anthropic API rejected the request: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Network error calling the Anthropic API.") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}") from e

    return messages, final_text, tool_calls


def run_chat_turn(
    role_id: str,
    user_message: str,
    history: list[dict[str, Any]],
    *,
    storage_backend: Any = db_storage,
    model: str = llm_client.DEFAULT_MODEL,
) -> dict[str, Any]:
    """Run one chat turn. Returns {"reply", "history", "pending_proposal"} —
    `history` is the full updated message list to persist verbatim (see
    api.py's chat routes); `pending_proposal` is non-null only when the most
    recent tool call this turn was propose_hiring_profile_edit and it
    produced a valid proposal (not an error)."""
    tools = build_tools_for_job(role_id, storage_backend)
    messages = [*history, {"role": "user", "content": user_message}]
    messages, final_text, tool_calls = _run_tool_loop(model, SYSTEM_PROMPT, tools, messages)

    pending_proposal = None
    for tc in reversed(tool_calls):
        if tc["name"] in _PROPOSAL_TOOL_NAMES:
            try:
                parsed = json.loads(tc.get("result") or "{}")
            except json.JSONDecodeError:
                parsed = {}
            if "proposal" in parsed:
                pending_proposal = {**parsed["proposal"], "role_id": role_id}
            break

    return {"reply": final_text, "history": messages, "pending_proposal": pending_proposal}
