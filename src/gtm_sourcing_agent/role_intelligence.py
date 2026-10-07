"""Feature 01 application services: Role Intelligence (create-role +
role-requirement/ICP/ambiguity CRUD + role versioning). See
docs/TALYN_V2_ARCHITECTURE.md §6/§7 for the design this implements.

Plain, directly-testable functions over the new DB-only tables
(models_orm.py's RoleRequirement/RoleICP/RoleAmbiguity/RoleVersion) — same
shape as db_storage.py, kept in its own module rather than added to that
1600+-line file since this is a distinct bounded context (role
intelligence, not general job/candidate storage). DB-only, same category
as workload_planning.py/conversation_summary.py: there is no file-backend
equivalent and no `storage_backend=` kwarg.

Every mutating operation (`apply_*`) is deterministic, LLM-free Python and
writes a RoleVersion row recording before/after/who/when/why — the data
model's "the LLM must never directly modify SQL" guarantee and its role-
versioning requirement are both enforced here, not by convention upstream.
Each has a matching `propose_*` that returns a diff with no DB write, for
orchestrator.py's typed tools to call before a recruiter confirms — the
same propose/confirm split orchestrator.py already uses for hiring-profile
edits (see its module docstring), applied here to a second family of
mutations.
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from . import agent_observability, db, db_storage, llm_client
from .models.role_intelligence import GeneratedSearchStrategy
from .models_orm import DEFAULT_ORGANIZATION_ID, Job, RoleAmbiguity, RoleICP, RoleRequirement, RoleVersion

REQUIREMENT_CATEGORIES = ("skill", "experience", "location", "comp", "other")
REQUIREMENT_PRIORITIES = ("must_have", "nice_to_have")
EVIDENCE_LEVELS = ("CONFIRMED", "INFERRED", "NOT_STATED", "CONFLICTING")


def _require_job(role_id: str) -> None:
    if not db_storage.job_exists(role_id):
        raise ValueError(f"role '{role_id}' not found")


def _requirement_dict(row: RoleRequirement) -> dict[str, Any]:
    return {
        "id": row.id,
        "role_id": row.role_id,
        "category": row.category,
        "value": row.value,
        "priority": row.priority,
        "evidence_level": row.evidence_level,
        "source_span": row.source_span,
        "confidence": row.confidence,
        "created_by": row.created_by,
        "is_deleted": row.is_deleted,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _icp_dict(row: RoleICP) -> dict[str, Any]:
    return {
        "role_id": row.role_id,
        "fields": row.fields,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _ambiguity_dict(row: RoleAmbiguity) -> dict[str, Any]:
    return {
        "id": row.id,
        "role_id": row.role_id,
        "description": row.description,
        "candidate_resolutions": row.candidate_resolutions,
        "status": row.status,
        "resolution_note": row.resolution_note,
        "resolved_requirement_id": row.resolved_requirement_id,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _version_dict(row: RoleVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "role_id": row.role_id,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "action": row.action,
        "before": row.before,
        "after": row.after,
        "changed_by": row.changed_by,
        "reason": row.reason,
        "changed_at": row.changed_at.isoformat(),
    }


def _write_version(
    session,
    role_id: str,
    *,
    entity_type: str,
    entity_id: int | None,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    changed_by: str,
    reason: str,
) -> None:
    session.add(RoleVersion(
        role_id=role_id, organization_id=DEFAULT_ORGANIZATION_ID, entity_type=entity_type,
        entity_id=entity_id, action=action, before=before, after=after,
        changed_by=changed_by, reason=reason,
    ))


# ── requirements ──────────────────────────────────────────────────────


def get_role(role_id: str) -> dict[str, Any]:
    _require_job(role_id)
    with db.get_session() as session:
        job = session.get(Job, role_id)
        return {
            "role_id": job.role_id, "title": job.title, "role_family": job.role_family,
            "client_name": job.client_name, "lifecycle_status": job.lifecycle_status,
            "owner_email": job.owner_email,
        }


def get_requirements(role_id: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    _require_job(role_id)
    with db.get_session() as session:
        stmt = select(RoleRequirement).where(RoleRequirement.role_id == role_id)
        if not include_deleted:
            stmt = stmt.where(RoleRequirement.is_deleted.is_(False))
        rows = session.scalars(stmt.order_by(RoleRequirement.id)).all()
        return [_requirement_dict(r) for r in rows]


def _validate_requirement_fields(category: str, priority: str, evidence_level: str) -> None:
    if category not in REQUIREMENT_CATEGORIES:
        raise ValueError(f"unknown category '{category}', must be one of {REQUIREMENT_CATEGORIES}")
    if priority not in REQUIREMENT_PRIORITIES:
        raise ValueError(f"unknown priority '{priority}', must be one of {REQUIREMENT_PRIORITIES}")
    if evidence_level not in EVIDENCE_LEVELS:
        raise ValueError(f"unknown evidence_level '{evidence_level}', must be one of {EVIDENCE_LEVELS}")


def save_extraction(
    role_id: str,
    *,
    requirements: list[dict[str, Any]],
    icp_fields: dict[str, Any],
    ambiguities: list[dict[str, Any]],
    created_by: str = "ai",
) -> dict[str, Any]:
    """Persist a fresh RoleExtraction (stages/role_intelligence_extraction.py's
    output) for a role that has no requirements yet — the Feature 01
    "Create Role" write. Unlike every mutation below, this does not go
    through propose/confirm: nothing has been evaluated against these
    requirements yet (they don't exist until this call), so there's
    nothing a confirmation step would be protecting. Each created row
    still gets its own RoleVersion("add") entry — versioning covers
    every write, not just edits."""
    _require_job(role_id)
    created_requirements = []
    with db.get_session() as session:
        for r in requirements:
            _validate_requirement_fields(r["category"], r["priority"], r["evidence_level"])
            row = RoleRequirement(
                role_id=role_id, organization_id=DEFAULT_ORGANIZATION_ID,
                category=r["category"], value=r["value"], priority=r["priority"],
                evidence_level=r["evidence_level"], source_span=r.get("source_span", ""),
                confidence=r.get("confidence"), created_by=created_by,
            )
            session.add(row)
            session.flush()
            _write_version(
                session, role_id, entity_type="requirement", entity_id=row.id, action="add",
                before=None, after=_requirement_dict(row), changed_by=created_by,
                reason="initial extraction",
            )
            created_requirements.append(row.id)

        icp_row = session.scalars(select(RoleICP).where(RoleICP.role_id == role_id)).first()
        if icp_row is None:
            icp_row = RoleICP(role_id=role_id, organization_id=DEFAULT_ORGANIZATION_ID, fields=icp_fields)
            session.add(icp_row)
            icp_before = None
        else:
            icp_before = dict(icp_row.fields)
            icp_row.fields = icp_fields
            icp_row.updated_at = datetime.now(UTC)
        session.flush()
        _write_version(
            session, role_id, entity_type="icp", entity_id=icp_row.id,
            action="add" if icp_before is None else "update",
            before=icp_before, after=dict(icp_row.fields), changed_by=created_by,
            reason="initial extraction",
        )

        created_ambiguities = []
        for a in ambiguities:
            row = RoleAmbiguity(
                role_id=role_id, organization_id=DEFAULT_ORGANIZATION_ID,
                description=a["description"], candidate_resolutions=a.get("candidate_resolutions", []),
            )
            session.add(row)
            session.flush()
            _write_version(
                session, role_id, entity_type="ambiguity", entity_id=row.id, action="add",
                before=None, after=_ambiguity_dict(row), changed_by=created_by,
                reason="initial extraction",
            )
            created_ambiguities.append(row.id)

        session.commit()

    return {
        "requirement_ids": created_requirements,
        "ambiguity_ids": created_ambiguities,
    }


def propose_add_requirement(
    role_id: str, *, category: str, value: str, priority: str, evidence_level: str = "NOT_STATED",
    source_span: str = "", confidence: float | None = None,
) -> dict[str, Any]:
    _require_job(role_id)
    _validate_requirement_fields(category, priority, evidence_level)
    return {
        "kind": "requirement_add",
        "description": f'Add {priority.replace("_", " ")} requirement: "{value}".',
        "impact": "Creates a new requirement; does not change any existing one.",
        "fields": {
            "category": category, "value": value, "priority": priority,
            "evidence_level": evidence_level, "source_span": source_span, "confidence": confidence,
        },
    }


def apply_add_requirement(
    role_id: str, *, category: str, value: str, priority: str, evidence_level: str = "NOT_STATED",
    source_span: str = "", confidence: float | None = None, changed_by: str, reason: str = "",
) -> dict[str, Any]:
    _require_job(role_id)
    _validate_requirement_fields(category, priority, evidence_level)
    with db.get_session() as session:
        row = RoleRequirement(
            role_id=role_id, organization_id=DEFAULT_ORGANIZATION_ID, category=category, value=value,
            priority=priority, evidence_level=evidence_level, source_span=source_span,
            confidence=confidence, created_by=changed_by,
        )
        session.add(row)
        session.flush()
        _write_version(
            session, role_id, entity_type="requirement", entity_id=row.id, action="add",
            before=None, after=_requirement_dict(row), changed_by=changed_by, reason=reason,
        )
        session.commit()
        return _requirement_dict(row)


def _get_requirement_row(session, role_id: str, requirement_id: int) -> RoleRequirement:
    row = session.get(RoleRequirement, requirement_id)
    if row is None or row.role_id != role_id:
        raise ValueError(f"requirement {requirement_id} not found for role '{role_id}'")
    return row


def propose_update_requirement(role_id: str, requirement_id: int, **fields: Any) -> dict[str, Any]:
    _require_job(role_id)
    with db.get_session() as session:
        row = _get_requirement_row(session, role_id, requirement_id)
        current = _requirement_dict(row)
    unknown = set(fields) - {"category", "value", "priority", "evidence_level", "source_span", "confidence"}
    if unknown:
        raise ValueError(f"not an editable requirement field: {', '.join(sorted(unknown))}")
    return {
        "kind": "requirement_update",
        "description": f"Update requirement \"{current['value']}\": {fields}.",
        "impact": "Already-scored candidates were evaluated against the current wording and may need re-review.",
        "requirement_id": requirement_id,
        "fields": fields,
    }


def apply_update_requirement(
    role_id: str, requirement_id: int, *, changed_by: str, reason: str = "", **fields: Any
) -> dict[str, Any]:
    _require_job(role_id)
    unknown = set(fields) - {"category", "value", "priority", "evidence_level", "source_span", "confidence"}
    if unknown:
        raise ValueError(f"not an editable requirement field: {', '.join(sorted(unknown))}")
    with db.get_session() as session:
        row = _get_requirement_row(session, role_id, requirement_id)
        before = _requirement_dict(row)
        for key, value in fields.items():
            setattr(row, key, value)
        _validate_requirement_fields(row.category, row.priority, row.evidence_level)
        row.updated_at = datetime.now(UTC)
        session.flush()
        after = _requirement_dict(row)
        _write_version(
            session, role_id, entity_type="requirement", entity_id=row.id, action="update",
            before=before, after=after, changed_by=changed_by, reason=reason,
        )
        session.commit()
        return after


def propose_remove_requirement(role_id: str, requirement_id: int) -> dict[str, Any]:
    _require_job(role_id)
    with db.get_session() as session:
        row = _get_requirement_row(session, role_id, requirement_id)
        current = _requirement_dict(row)
    return {
        "kind": "requirement_remove",
        "description": f"Remove requirement: \"{current['value']}\".",
        "impact": "Already-scored candidates were evaluated including this requirement and may need re-review.",
        "requirement_id": requirement_id,
    }


def apply_remove_requirement(role_id: str, requirement_id: int, *, changed_by: str, reason: str = "") -> dict[str, Any]:
    _require_job(role_id)
    with db.get_session() as session:
        row = _get_requirement_row(session, role_id, requirement_id)
        before = _requirement_dict(row)
        row.is_deleted = True
        row.updated_at = datetime.now(UTC)
        session.flush()
        after = _requirement_dict(row)
        _write_version(
            session, role_id, entity_type="requirement", entity_id=row.id, action="remove",
            before=before, after=after, changed_by=changed_by, reason=reason,
        )
        session.commit()
        return after


def propose_change_requirement_priority(role_id: str, requirement_id: int, priority: str) -> dict[str, Any]:
    _require_job(role_id)
    if priority not in REQUIREMENT_PRIORITIES:
        raise ValueError(f"unknown priority '{priority}', must be one of {REQUIREMENT_PRIORITIES}")
    with db.get_session() as session:
        row = _get_requirement_row(session, role_id, requirement_id)
        current = _requirement_dict(row)
    return {
        "kind": "requirement_priority",
        "description": f"Change \"{current['value']}\" priority: {current['priority']} -> {priority}.",
        "impact": "Already-scored candidates were evaluated under the old priority and may need re-review.",
        "requirement_id": requirement_id,
        "fields": {"priority": priority},
    }


def apply_change_requirement_priority(
    role_id: str, requirement_id: int, priority: str, *, changed_by: str, reason: str = ""
) -> dict[str, Any]:
    if priority not in REQUIREMENT_PRIORITIES:
        raise ValueError(f"unknown priority '{priority}', must be one of {REQUIREMENT_PRIORITIES}")
    return apply_update_requirement(role_id, requirement_id, priority=priority, changed_by=changed_by, reason=reason)


# ── ICP ───────────────────────────────────────────────────────────────


def get_icp(role_id: str) -> dict[str, Any] | None:
    _require_job(role_id)
    with db.get_session() as session:
        row = session.scalars(select(RoleICP).where(RoleICP.role_id == role_id)).first()
        return _icp_dict(row) if row else None


def propose_update_icp(role_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    _require_job(role_id)
    return {
        "kind": "icp_update",
        "description": f"Update ICP field(s): {', '.join(sorted(fields))}.",
        "impact": "Already-scored candidates were evaluated against the current ICP and may need re-review.",
        "fields": fields,
    }


def apply_update_icp(role_id: str, fields: dict[str, Any], *, changed_by: str, reason: str = "") -> dict[str, Any]:
    _require_job(role_id)
    with db.get_session() as session:
        row = session.scalars(select(RoleICP).where(RoleICP.role_id == role_id)).first()
        if row is None:
            row = RoleICP(role_id=role_id, organization_id=DEFAULT_ORGANIZATION_ID, fields={})
            session.add(row)
            session.flush()
            before = None
        else:
            before = dict(row.fields)
        merged = {**row.fields, **fields}
        row.fields = merged
        row.updated_at = datetime.now(UTC)
        session.flush()
        after = dict(row.fields)
        _write_version(
            session, role_id, entity_type="icp", entity_id=row.id,
            action="add" if before is None else "update",
            before=before, after=after, changed_by=changed_by, reason=reason,
        )
        session.commit()
        return _icp_dict(row)


# ── ambiguities ───────────────────────────────────────────────────────


def get_ambiguities(role_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    _require_job(role_id)
    with db.get_session() as session:
        stmt = select(RoleAmbiguity).where(RoleAmbiguity.role_id == role_id)
        if status is not None:
            stmt = stmt.where(RoleAmbiguity.status == status)
        rows = session.scalars(stmt.order_by(RoleAmbiguity.id)).all()
        return [_ambiguity_dict(r) for r in rows]


def _get_ambiguity_row(session, role_id: str, ambiguity_id: int) -> RoleAmbiguity:
    row = session.get(RoleAmbiguity, ambiguity_id)
    if row is None or row.role_id != role_id:
        raise ValueError(f"ambiguity {ambiguity_id} not found for role '{role_id}'")
    return row


def propose_resolve_ambiguity(
    role_id: str, ambiguity_id: int, *, resolution_note: str,
    new_requirement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_job(role_id)
    with db.get_session() as session:
        row = _get_ambiguity_row(session, role_id, ambiguity_id)
        description = row.description
        if row.status == "resolved":
            raise ValueError(f"ambiguity {ambiguity_id} is already resolved")
    if new_requirement is not None:
        _validate_requirement_fields(
            new_requirement.get("category", "other"), new_requirement.get("priority", "nice_to_have"),
            new_requirement.get("evidence_level", "NOT_STATED"),
        )
    return {
        "kind": "ambiguity_resolve",
        "description": f"Resolve ambiguity \"{description}\": {resolution_note}",
        "impact": (
            "Adds a new requirement reflecting this resolution."
            if new_requirement else "Marks this ambiguity resolved with no new requirement."
        ),
        "ambiguity_id": ambiguity_id,
        "resolution_note": resolution_note,
        "new_requirement": new_requirement,
    }


def apply_resolve_ambiguity(
    role_id: str, ambiguity_id: int, *, resolution_note: str, new_requirement: dict[str, Any] | None = None,
    changed_by: str, reason: str = "",
) -> dict[str, Any]:
    _require_job(role_id)
    with db.get_session() as session:
        row = _get_ambiguity_row(session, role_id, ambiguity_id)
        if row.status == "resolved":
            raise ValueError(f"ambiguity {ambiguity_id} is already resolved")
        before = _ambiguity_dict(row)

        resolved_requirement_id = None
        if new_requirement is not None:
            _validate_requirement_fields(
                new_requirement.get("category", "other"), new_requirement.get("priority", "nice_to_have"),
                new_requirement.get("evidence_level", "NOT_STATED"),
            )
            req_row = RoleRequirement(
                role_id=role_id, organization_id=DEFAULT_ORGANIZATION_ID,
                category=new_requirement.get("category", "other"), value=new_requirement["value"],
                priority=new_requirement.get("priority", "nice_to_have"),
                evidence_level=new_requirement.get("evidence_level", "NOT_STATED"),
                source_span=new_requirement.get("source_span", ""),
                confidence=new_requirement.get("confidence"), created_by=changed_by,
            )
            session.add(req_row)
            session.flush()
            _write_version(
                session, role_id, entity_type="requirement", entity_id=req_row.id, action="add",
                before=None, after=_requirement_dict(req_row), changed_by=changed_by,
                reason=f"resolving ambiguity {ambiguity_id}",
            )
            resolved_requirement_id = req_row.id

        row.status = "resolved"
        row.resolution_note = resolution_note
        row.resolved_requirement_id = resolved_requirement_id
        row.updated_at = datetime.now(UTC)
        session.flush()
        after = _ambiguity_dict(row)
        _write_version(
            session, role_id, entity_type="ambiguity", entity_id=row.id, action="resolve",
            before=before, after=after, changed_by=changed_by, reason=reason,
        )
        session.commit()
        return after


# ── search strategy (read-only, not persisted — see Architecture §6) ────


def generate_search_strategy(role_id: str, *, user_email: str = "") -> dict[str, Any]:
    _require_job(role_id)
    requirements = get_requirements(role_id)
    icp = get_icp(role_id)
    must_haves = [r["value"] for r in requirements if r["priority"] == "must_have"]
    nice_to_haves = [r["value"] for r in requirements if r["priority"] == "nice_to_have"]
    icp_fields = icp["fields"] if icp else {}

    prompt = llm_client.render_prompt(
        "role_intelligence_search_strategy.md",
        must_haves="\n".join(f"- {v}" for v in must_haves) or "(none yet)",
        nice_to_haves="\n".join(f"- {v}" for v in nice_to_haves) or "(none yet)",
        icp_fields_json=json.dumps(icp_fields),
    )

    with agent_observability.timed_tool_call(
        role_id=role_id, user_email=user_email, tool_name="generate_search_strategy",
        input_summary=f"{len(must_haves)} must-haves, {len(nice_to_haves)} nice-to-haves",
    ) as obs:
        def _capture_usage(usage):
            obs["model"] = llm_client.DEFAULT_MODEL
            obs["input_tokens"] = usage.input_tokens
            obs["output_tokens"] = usage.output_tokens

        result = llm_client.generate(
            prompt, GeneratedSearchStrategy, stage="role_intelligence_search_strategy", on_usage=_capture_usage,
        )
        obs["output_summary"] = f"{len(result.boolean_strings)} boolean strings, {len(result.xray_queries)} x-ray queries"

    return result.model_dump()


# ── history ───────────────────────────────────────────────────────────


def get_role_history(role_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    _require_job(role_id)
    with db.get_session() as session:
        rows = session.scalars(
            select(RoleVersion).where(RoleVersion.role_id == role_id)
            .order_by(RoleVersion.changed_at.desc()).limit(limit)
        ).all()
        return [_version_dict(r) for r in rows]


# Every propose_*/apply_* pair above, keyed by the proposal "kind" string
# they produce/consume — api.py's confirm route dispatches through this
# instead of hardcoding one mutation shape (today's hiring-profile-only
# confirm route is the thing this generalizes; see api.py's
# confirm_chat_proposal).
APPLY_BY_KIND = {
    "requirement_add": lambda role_id, pending, changed_by: apply_add_requirement(
        role_id, changed_by=changed_by, **pending["fields"]
    ),
    "requirement_update": lambda role_id, pending, changed_by: apply_update_requirement(
        role_id, pending["requirement_id"], changed_by=changed_by, **pending["fields"]
    ),
    "requirement_remove": lambda role_id, pending, changed_by: apply_remove_requirement(
        role_id, pending["requirement_id"], changed_by=changed_by
    ),
    "requirement_priority": lambda role_id, pending, changed_by: apply_change_requirement_priority(
        role_id, pending["requirement_id"], pending["fields"]["priority"], changed_by=changed_by
    ),
    "icp_update": lambda role_id, pending, changed_by: apply_update_icp(
        role_id, pending["fields"], changed_by=changed_by
    ),
    "ambiguity_resolve": lambda role_id, pending, changed_by: apply_resolve_ambiguity(
        role_id, pending["ambiguity_id"], resolution_note=pending["resolution_note"],
        new_requirement=pending.get("new_requirement"), changed_by=changed_by,
    ),
}
