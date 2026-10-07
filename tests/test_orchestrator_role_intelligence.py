"""Tool-level tests for Feature 01's 12 role-intelligence tools added to
orchestrator.py. Same seam as test_orchestrator.py: calls TOOL_IMPLS (the
plain functions), never the @beta_tool-wrapped closures or a real model —
see orchestrator.py's module docstring for why tool-selection quality
itself is untestable without live inference."""

import json

import pytest

from gtm_sourcing_agent import db, db_storage, orchestrator, role_intelligence


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db_storage.create_job("job-a", title="AE Role", owner_email="r1@example.com")
    return tmp_path


def test_get_role(isolated_db):
    result = json.loads(orchestrator.TOOL_IMPLS["get_role"]("job-a", db_storage))
    assert result["role_id"] == "job-a"
    assert result["title"] == "AE Role"


def test_get_requirements_empty(isolated_db):
    result = json.loads(orchestrator.TOOL_IMPLS["get_requirements"]("job-a", db_storage))
    assert result == []


def test_propose_add_requirement_returns_a_proposal_without_persisting(isolated_db):
    result = json.loads(orchestrator.TOOL_IMPLS["propose_add_requirement"](
        "job-a", db_storage, "skill", "Salesforce", "must_have",
    ))
    assert result["proposal"]["kind"] == "requirement_add"
    assert result["proposal"]["fields"]["value"] == "Salesforce"
    assert role_intelligence.get_requirements("job-a") == []


def test_propose_add_requirement_rejects_bad_category(isolated_db):
    result = json.loads(orchestrator.TOOL_IMPLS["propose_add_requirement"](
        "job-a", db_storage, "nonsense", "x", "must_have",
    ))
    assert "error" in result


def test_propose_update_requirement(isolated_db):
    req = role_intelligence.apply_add_requirement(
        "job-a", category="skill", value="Salesforce", priority="must_have", changed_by="ai",
    )
    result = json.loads(orchestrator.TOOL_IMPLS["propose_update_requirement"](
        "job-a", db_storage, req["id"], priority="nice_to_have",
    ))
    assert result["proposal"]["kind"] == "requirement_update"
    # still unapplied
    assert role_intelligence.get_requirements("job-a")[0]["priority"] == "must_have"


def test_propose_update_requirement_unknown_id(isolated_db):
    result = json.loads(orchestrator.TOOL_IMPLS["propose_update_requirement"](
        "job-a", db_storage, 9999, priority="must_have",
    ))
    assert "error" in result


def test_propose_remove_requirement(isolated_db):
    req = role_intelligence.apply_add_requirement(
        "job-a", category="skill", value="Salesforce", priority="must_have", changed_by="ai",
    )
    result = json.loads(orchestrator.TOOL_IMPLS["propose_remove_requirement"]("job-a", db_storage, req["id"]))
    assert result["proposal"]["kind"] == "requirement_remove"
    assert len(role_intelligence.get_requirements("job-a")) == 1  # still there


def test_propose_change_requirement_priority(isolated_db):
    req = role_intelligence.apply_add_requirement(
        "job-a", category="skill", value="Salesforce", priority="must_have", changed_by="ai",
    )
    result = json.loads(orchestrator.TOOL_IMPLS["propose_change_requirement_priority"](
        "job-a", db_storage, req["id"], "nice_to_have",
    ))
    assert result["proposal"]["kind"] == "requirement_priority"


def test_get_icp_none(isolated_db):
    assert json.loads(orchestrator.TOOL_IMPLS["get_icp"]("job-a", db_storage)) is None


def test_propose_update_icp(isolated_db):
    fields_json = json.dumps({"geography": {"value": "Remote US", "evidence_level": "CONFIRMED", "source_span": "x", "confidence": 0.9}})
    result = json.loads(orchestrator.TOOL_IMPLS["propose_update_icp"]("job-a", db_storage, fields_json))
    assert result["proposal"]["kind"] == "icp_update"
    assert role_intelligence.get_icp("job-a") is None  # unapplied


def test_propose_update_icp_bad_json(isolated_db):
    result = json.loads(orchestrator.TOOL_IMPLS["propose_update_icp"]("job-a", db_storage, "not json"))
    assert "error" in result


def test_get_ambiguities_empty(isolated_db):
    assert json.loads(orchestrator.TOOL_IMPLS["get_ambiguities"]("job-a", db_storage)) == []


def test_propose_resolve_ambiguity(isolated_db):
    role_intelligence.save_extraction(
        "job-a", requirements=[], icp_fields={},
        ambiguities=[{"description": "x", "candidate_resolutions": []}],
    )
    amb = role_intelligence.get_ambiguities("job-a")[0]
    result = json.loads(orchestrator.TOOL_IMPLS["propose_resolve_ambiguity"]("job-a", db_storage, amb["id"], "resolved it"))
    assert result["proposal"]["kind"] == "ambiguity_resolve"
    assert role_intelligence.get_ambiguities("job-a")[0]["status"] == "open"  # unapplied


def test_get_role_history_empty(isolated_db):
    assert json.loads(orchestrator.TOOL_IMPLS["get_role_history"]("job-a", db_storage)) == []


def test_get_role_history_after_a_change(isolated_db):
    role_intelligence.apply_add_requirement(
        "job-a", category="skill", value="Salesforce", priority="must_have", changed_by="ai",
    )
    history = json.loads(orchestrator.TOOL_IMPLS["get_role_history"]("job-a", db_storage))
    assert len(history) == 1
    assert history[0]["action"] == "add"


# ── run_chat_turn: the new tool names surface a pending_proposal too ────


def test_run_chat_turn_surfaces_a_requirement_add_proposal(isolated_db, monkeypatch):
    def fake_loop(model, system, tools, messages):
        tool = next(t for t in tools if t.name == "propose_add_requirement")
        result_str = tool(category="skill", value="Salesforce", priority="must_have")
        return messages, "Here's that proposal.", [
            {"name": "propose_add_requirement", "input": {}, "id": "tu_1", "result": result_str}
        ]

    monkeypatch.setattr(orchestrator, "_run_tool_loop", fake_loop)

    result = orchestrator.run_chat_turn("job-a", "add Salesforce as a must-have", [])
    assert result["pending_proposal"]["kind"] == "requirement_add"
    assert result["pending_proposal"]["role_id"] == "job-a"
    assert role_intelligence.get_requirements("job-a") == []  # still unapplied
