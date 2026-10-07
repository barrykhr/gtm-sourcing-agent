"""API tests for Feature 01's Role Intelligence routes (api.py) — same
mocking/polling pattern as test_api.py (mock llm_client.generate, poll
the real background task to completion) plus test_chat_api.py's pattern
for the generalized chat/confirm dispatch (role_intelligence.APPLY_BY_KIND)."""

import time

import pytest
from fastapi.testclient import TestClient

from gtm_sourcing_agent import db, db_storage, llm_client, orchestrator
from gtm_sourcing_agent.api import app
from gtm_sourcing_agent.models.role_intelligence import RoleExtraction

client = TestClient(app)


def _wait_for_task(role_id: str, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    task = None
    while time.time() < deadline:
        task = client.get(f"/jobs/{role_id}/tasks/{task_id}").json()
        if task["status"] in ("succeeded", "failed"):
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not finish within {timeout}s: last seen {task}")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    client.cookies.clear()
    client.post("/auth/signup", json={"email": "recruiter@example.com", "password": "test-password-123"})
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    return tmp_path


@pytest.fixture
def fake_generate(monkeypatch):
    calls = []
    queue = []

    def _fake(prompt, output_model, *, model=llm_client.DEFAULT_MODEL, max_tokens=0, stage="", on_usage=None):
        calls.append({"prompt": prompt, "output_model": output_model, "stage": stage})
        if on_usage is not None:
            class _Usage:
                input_tokens = 10
                output_tokens = 5
            on_usage(_Usage())
        return queue.pop(0)

    monkeypatch.setattr(llm_client, "generate", _fake)
    _fake.calls = calls
    _fake.queue = queue
    return _fake


@pytest.fixture
def fake_chat_turn(monkeypatch):
    calls = []
    queue = []

    def _fake(role_id, message, history, *, storage_backend=db_storage, model=None):
        calls.append({"role_id": role_id, "message": message, "history": history})
        return queue.pop(0)

    monkeypatch.setattr(orchestrator, "run_chat_turn", _fake)
    _fake.calls = calls
    _fake.queue = queue
    return _fake


# ── extraction (async task) ───────────────────────────────────────────


def test_extract_requires_job_to_exist(isolated_db):
    resp = client.post("/jobs/no-such-job/role-intelligence/extract", json={"jd_text": "x"})
    assert resp.status_code == 404


def test_extract_end_to_end_persists_requirements(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(requirements=[], icp_fields={}, ambiguities=[]))
    resp = client.post("/jobs/ae-role/role-intelligence/extract", json={"jd_text": "Enterprise AE role, 5+ years."})
    assert resp.status_code == 202, resp.text

    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "succeeded", task

    reqs = client.get("/jobs/ae-role/role-intelligence/requirements").json()
    assert reqs == []


# ── requirements CRUD (direct apply — recruiter's own explicit edit) ──


def test_requirements_crud_round_trip(isolated_db):
    create = client.post("/jobs/ae-role/role-intelligence/requirements", json={
        "category": "skill", "value": "Salesforce", "priority": "must_have",
    })
    assert create.status_code == 200, create.text
    req = create.json()
    assert req["value"] == "Salesforce"
    assert req["created_by"] == "recruiter@example.com"

    listed = client.get("/jobs/ae-role/role-intelligence/requirements").json()
    assert len(listed) == 1

    patched = client.patch(
        f"/jobs/ae-role/role-intelligence/requirements/{req['id']}", json={"priority": "nice_to_have"}
    )
    assert patched.status_code == 200
    assert patched.json()["priority"] == "nice_to_have"

    deleted = client.delete(f"/jobs/ae-role/role-intelligence/requirements/{req['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["is_deleted"] is True
    assert client.get("/jobs/ae-role/role-intelligence/requirements").json() == []


def test_update_unknown_requirement_is_400(isolated_db):
    resp = client.patch("/jobs/ae-role/role-intelligence/requirements/9999", json={"priority": "must_have"})
    assert resp.status_code == 400


# ── ICP ─────────────────────────────────────────────────────────────


def test_icp_get_and_patch(isolated_db):
    assert client.get("/jobs/ae-role/role-intelligence/icp").json() is None

    patched = client.patch("/jobs/ae-role/role-intelligence/icp", json={
        "fields": {"geography": {"value": "Remote US", "evidence_level": "CONFIRMED", "source_span": "remote", "confidence": 0.9}},
    })
    assert patched.status_code == 200
    assert patched.json()["fields"]["geography"]["value"] == "Remote US"

    assert client.get("/jobs/ae-role/role-intelligence/icp").json()["fields"]["geography"]["value"] == "Remote US"


# ── ambiguities ───────────────────────────────────────────────────────


def test_ambiguity_resolve_via_api(isolated_db):
    # seed one via the extraction path's own persistence layer directly
    from gtm_sourcing_agent import role_intelligence
    role_intelligence.save_extraction(
        "ae-role", requirements=[], icp_fields={},
        ambiguities=[{"description": "seniority unclear", "candidate_resolutions": ["ask"]}],
    )
    amb = client.get("/jobs/ae-role/role-intelligence/ambiguities").json()[0]

    resolved = client.post(
        f"/jobs/ae-role/role-intelligence/ambiguities/{amb['id']}/resolve",
        json={"resolution_note": "confirmed senior"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


# ── history + agent runs ───────────────────────────────────────────────


def test_history_and_agent_runs_endpoints(isolated_db):
    client.post("/jobs/ae-role/role-intelligence/requirements", json={
        "category": "skill", "value": "Salesforce", "priority": "must_have",
    })
    history = client.get("/jobs/ae-role/role-intelligence/history").json()
    assert len(history) == 1
    assert history[0]["entity_type"] == "requirement"
    assert history[0]["changed_by"] == "recruiter@example.com"

    runs = client.get("/jobs/ae-role/role-intelligence/agent-runs").json()
    assert runs == []  # direct REST CRUD isn't an agent action — only chat/extraction tool calls are


# ── chat/confirm dispatch generalization (role_intelligence.APPLY_BY_KIND) ─


def test_confirm_applies_a_requirement_add_proposal(isolated_db, fake_chat_turn):
    proposal = {
        "kind": "requirement_add",
        "description": 'Add must have requirement: "Salesforce".',
        "impact": "Creates a new requirement.",
        "fields": {"category": "skill", "value": "Salesforce", "priority": "must_have", "evidence_level": "NOT_STATED", "source_span": "", "confidence": None},
        "role_id": "ae-role",
    }
    fake_chat_turn.queue.append({"reply": "Here's the proposal.", "history": [], "pending_proposal": proposal})
    client.post("/jobs/ae-role/chat", json={"message": "add Salesforce as a must-have"})

    resp = client.post("/jobs/ae-role/chat/confirm", json={"approve": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["result"]["value"] == "Salesforce"

    reqs = client.get("/jobs/ae-role/role-intelligence/requirements").json()
    assert len(reqs) == 1
    assert reqs[0]["created_by"] == "recruiter@example.com"  # confirming user, not "ai"


def test_confirm_decline_does_not_apply_a_requirement_proposal(isolated_db, fake_chat_turn):
    proposal = {
        "kind": "requirement_add",
        "description": 'Add must have requirement: "Salesforce".',
        "impact": "Creates a new requirement.",
        "fields": {"category": "skill", "value": "Salesforce", "priority": "must_have", "evidence_level": "NOT_STATED", "source_span": "", "confidence": None},
        "role_id": "ae-role",
    }
    fake_chat_turn.queue.append({"reply": "Here's the proposal.", "history": [], "pending_proposal": proposal})
    client.post("/jobs/ae-role/chat", json={"message": "add Salesforce as a must-have"})

    resp = client.post("/jobs/ae-role/chat/confirm", json={"approve": False})
    assert resp.status_code == 200
    assert resp.json()["applied"] is False
    assert client.get("/jobs/ae-role/role-intelligence/requirements").json() == []


def test_confirm_unknown_proposal_kind_is_400(isolated_db, fake_chat_turn):
    proposal = {"kind": "something_unsupported", "description": "x", "role_id": "ae-role"}
    fake_chat_turn.queue.append({"reply": "ok", "history": [], "pending_proposal": proposal})
    client.post("/jobs/ae-role/chat", json={"message": "do something weird"})

    resp = client.post("/jobs/ae-role/chat/confirm", json={"approve": True})
    assert resp.status_code == 400
