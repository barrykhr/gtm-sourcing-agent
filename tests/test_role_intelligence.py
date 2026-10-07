"""Unit tests for role_intelligence.py — Feature 01's application-service
layer (TALYN_V2_ARCHITECTURE.md §6/§7). DB-only, same fixture style as
test_workload_planning.py: no file-backend equivalent exists for these
tables, so tests go straight through db_storage/role_intelligence rather
than the isolated_workspace fixture test_stages.py's other stage tests
share."""

import pytest

from gtm_sourcing_agent import db, db_storage, role_intelligence


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    return tmp_path


# ── requirements: create/read ────────────────────────────────────────


def test_save_extraction_creates_requirements_icp_and_ambiguities(isolated_db):
    out = role_intelligence.save_extraction(
        "acme-ae-2026",
        requirements=[
            {"category": "skill", "value": "Salesforce", "priority": "must_have",
             "evidence_level": "CONFIRMED", "source_span": "experience with Salesforce", "confidence": 0.9},
        ],
        icp_fields={"company_profile": {"value": "B2B SaaS", "evidence_level": "INFERRED", "source_span": "", "confidence": 0.6}},
        ambiguities=[{"description": "5+ years vs junior", "candidate_resolutions": ["ask hiring manager"]}],
    )
    assert len(out["requirement_ids"]) == 1
    assert len(out["ambiguity_ids"]) == 1

    reqs = role_intelligence.get_requirements("acme-ae-2026")
    assert len(reqs) == 1
    assert reqs[0]["value"] == "Salesforce"
    assert reqs[0]["evidence_level"] == "CONFIRMED"
    assert reqs[0]["created_by"] == "ai"

    icp = role_intelligence.get_icp("acme-ae-2026")
    assert icp["fields"]["company_profile"]["value"] == "B2B SaaS"

    ambs = role_intelligence.get_ambiguities("acme-ae-2026")
    assert len(ambs) == 1
    assert ambs[0]["status"] == "open"


def test_save_extraction_writes_a_role_version_per_created_entity(isolated_db):
    role_intelligence.save_extraction(
        "acme-ae-2026",
        requirements=[{"category": "skill", "value": "Salesforce", "priority": "must_have", "evidence_level": "CONFIRMED", "source_span": "x"}],
        icp_fields={}, ambiguities=[],
    )
    history = role_intelligence.get_role_history("acme-ae-2026")
    kinds = {(h["entity_type"], h["action"]) for h in history}
    assert ("requirement", "add") in kinds
    assert ("icp", "add") in kinds
    assert all(h["changed_by"] == "ai" for h in history)


def test_get_requirements_excludes_soft_deleted_by_default(isolated_db):
    role_intelligence.apply_add_requirement(
        "acme-ae-2026", category="skill", value="Salesforce", priority="must_have", changed_by="r1@example.com",
    )
    req = role_intelligence.get_requirements("acme-ae-2026")[0]
    role_intelligence.apply_remove_requirement("acme-ae-2026", req["id"], changed_by="r1@example.com")

    assert role_intelligence.get_requirements("acme-ae-2026") == []
    assert len(role_intelligence.get_requirements("acme-ae-2026", include_deleted=True)) == 1


def test_get_requirements_raises_for_unknown_role(isolated_db):
    with pytest.raises(ValueError, match="not found"):
        role_intelligence.get_requirements("no-such-role")


# ── requirements: validation ──────────────────────────────────────────


def test_apply_add_requirement_rejects_unknown_category(isolated_db):
    with pytest.raises(ValueError, match="category"):
        role_intelligence.apply_add_requirement(
            "acme-ae-2026", category="nonsense", value="x", priority="must_have", changed_by="r1@example.com",
        )


def test_apply_add_requirement_rejects_unknown_evidence_level(isolated_db):
    with pytest.raises(ValueError, match="evidence_level"):
        role_intelligence.apply_add_requirement(
            "acme-ae-2026", category="skill", value="x", priority="must_have",
            evidence_level="MAYBE", changed_by="r1@example.com",
        )


def test_propose_update_requirement_rejects_unknown_field(isolated_db):
    req = role_intelligence.apply_add_requirement(
        "acme-ae-2026", category="skill", value="Salesforce", priority="must_have", changed_by="r1@example.com",
    )
    with pytest.raises(ValueError, match="not an editable requirement field"):
        role_intelligence.propose_update_requirement("acme-ae-2026", req["id"], created_by="hijack")


# ── propose/apply split: propose never writes ─────────────────────────


def test_propose_add_requirement_does_not_persist_anything(isolated_db):
    role_intelligence.propose_add_requirement(
        "acme-ae-2026", category="skill", value="Salesforce", priority="must_have",
    )
    assert role_intelligence.get_requirements("acme-ae-2026") == []
    assert role_intelligence.get_role_history("acme-ae-2026") == []


def test_apply_update_requirement_writes_before_after_version(isolated_db):
    req = role_intelligence.apply_add_requirement(
        "acme-ae-2026", category="skill", value="Salesforce", priority="must_have", changed_by="ai",
    )
    updated = role_intelligence.apply_update_requirement(
        "acme-ae-2026", req["id"], priority="nice_to_have", changed_by="r1@example.com", reason="recruiter edit",
    )
    assert updated["priority"] == "nice_to_have"

    history = role_intelligence.get_role_history("acme-ae-2026")
    update_entry = next(h for h in history if h["action"] == "update")
    assert update_entry["before"]["priority"] == "must_have"
    assert update_entry["after"]["priority"] == "nice_to_have"
    assert update_entry["changed_by"] == "r1@example.com"
    assert update_entry["reason"] == "recruiter edit"


def test_apply_remove_requirement_soft_deletes(isolated_db):
    req = role_intelligence.apply_add_requirement(
        "acme-ae-2026", category="skill", value="Salesforce", priority="must_have", changed_by="ai",
    )
    removed = role_intelligence.apply_remove_requirement("acme-ae-2026", req["id"], changed_by="r1@example.com")
    assert removed["is_deleted"] is True
    # the row still exists for role_version's before/after reconstruction
    assert len(role_intelligence.get_requirements("acme-ae-2026", include_deleted=True)) == 1


def test_apply_change_requirement_priority(isolated_db):
    req = role_intelligence.apply_add_requirement(
        "acme-ae-2026", category="skill", value="Salesforce", priority="must_have", changed_by="ai",
    )
    updated = role_intelligence.apply_change_requirement_priority(
        "acme-ae-2026", req["id"], "nice_to_have", changed_by="r1@example.com",
    )
    assert updated["priority"] == "nice_to_have"


def test_requirement_not_found_raises(isolated_db):
    with pytest.raises(ValueError, match="not found"):
        role_intelligence.apply_update_requirement("acme-ae-2026", 9999, value="x", changed_by="r1@example.com")


# ── ICP ───────────────────────────────────────────────────────────────


def test_apply_update_icp_merges_fields_and_creates_on_first_call(isolated_db):
    first = role_intelligence.apply_update_icp(
        "acme-ae-2026", {"company_profile": {"value": "B2B SaaS", "evidence_level": "INFERRED", "source_span": "", "confidence": 0.5}},
        changed_by="r1@example.com",
    )
    assert first["fields"]["company_profile"]["value"] == "B2B SaaS"

    second = role_intelligence.apply_update_icp(
        "acme-ae-2026", {"geography": {"value": "Remote US", "evidence_level": "CONFIRMED", "source_span": "remote", "confidence": 0.9}},
        changed_by="r1@example.com",
    )
    # merge, not replace — company_profile from the first call survives
    assert second["fields"]["company_profile"]["value"] == "B2B SaaS"
    assert second["fields"]["geography"]["value"] == "Remote US"

    history = role_intelligence.get_role_history("acme-ae-2026")
    actions = [h["action"] for h in history if h["entity_type"] == "icp"]
    assert actions == ["update", "add"]  # most-recent-first (changed_at desc)


# ── ambiguities ───────────────────────────────────────────────────────


def test_apply_resolve_ambiguity_with_no_new_requirement(isolated_db):
    role_intelligence.save_extraction(
        "acme-ae-2026", requirements=[], icp_fields={},
        ambiguities=[{"description": "5+ years vs junior", "candidate_resolutions": ["ask"]}],
    )
    amb = role_intelligence.get_ambiguities("acme-ae-2026")[0]
    resolved = role_intelligence.apply_resolve_ambiguity(
        "acme-ae-2026", amb["id"], resolution_note="confirmed senior-only", changed_by="r1@example.com",
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolved_requirement_id"] is None
    assert role_intelligence.get_requirements("acme-ae-2026") == []


def test_apply_resolve_ambiguity_with_a_new_requirement(isolated_db):
    role_intelligence.save_extraction(
        "acme-ae-2026", requirements=[], icp_fields={},
        ambiguities=[{"description": "5+ years vs junior", "candidate_resolutions": ["ask"]}],
    )
    amb = role_intelligence.get_ambiguities("acme-ae-2026")[0]
    resolved = role_intelligence.apply_resolve_ambiguity(
        "acme-ae-2026", amb["id"], resolution_note="confirmed senior-only",
        new_requirement={"category": "experience", "value": "5+ years required", "priority": "must_have"},
        changed_by="r1@example.com",
    )
    assert resolved["resolved_requirement_id"] is not None
    reqs = role_intelligence.get_requirements("acme-ae-2026")
    assert len(reqs) == 1
    assert reqs[0]["value"] == "5+ years required"


def test_apply_resolve_ambiguity_twice_raises(isolated_db):
    role_intelligence.save_extraction(
        "acme-ae-2026", requirements=[], icp_fields={},
        ambiguities=[{"description": "x", "candidate_resolutions": []}],
    )
    amb = role_intelligence.get_ambiguities("acme-ae-2026")[0]
    role_intelligence.apply_resolve_ambiguity("acme-ae-2026", amb["id"], resolution_note="ok", changed_by="r1@example.com")
    with pytest.raises(ValueError, match="already resolved"):
        role_intelligence.apply_resolve_ambiguity("acme-ae-2026", amb["id"], resolution_note="again", changed_by="r1@example.com")


# ── APPLY_BY_KIND dispatch table (api.py's confirm route uses this) ────


def test_apply_by_kind_dispatches_requirement_add():
    assert "requirement_add" in role_intelligence.APPLY_BY_KIND
    assert "requirement_update" in role_intelligence.APPLY_BY_KIND
    assert "requirement_remove" in role_intelligence.APPLY_BY_KIND
    assert "requirement_priority" in role_intelligence.APPLY_BY_KIND
    assert "icp_update" in role_intelligence.APPLY_BY_KIND
    assert "ambiguity_resolve" in role_intelligence.APPLY_BY_KIND


def test_apply_by_kind_requirement_add_end_to_end(isolated_db):
    proposal = role_intelligence.propose_add_requirement(
        "acme-ae-2026", category="skill", value="Salesforce", priority="must_have",
    )
    apply_fn = role_intelligence.APPLY_BY_KIND[proposal["kind"]]
    result = apply_fn("acme-ae-2026", proposal, "r1@example.com")
    assert result["value"] == "Salesforce"
    assert role_intelligence.get_requirements("acme-ae-2026")[0]["created_by"] == "r1@example.com"
