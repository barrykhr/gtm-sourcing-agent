"""Phase 3 chat routes via TestClient. Mocks orchestrator.run_chat_turn
directly (api.py's boundary), same reasoning as test_orchestrator.py: no
test here claims anything about tool-selection quality, only that the
persistence/confirmation plumbing around a turn is correct."""

import pytest
from fastapi.testclient import TestClient

from gtm_sourcing_agent import db, db_storage, orchestrator
from gtm_sourcing_agent.api import app

client = TestClient(app)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Isolated DB *and* an authenticated session — see test_api.py's
    identical fixture for why (Phase 7 auth)."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    client.cookies.clear()
    client.post("/auth/signup", json={"email": "recruiter@example.com", "password": "test-password-123"})
    return tmp_path


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


def test_chat_requires_job_to_exist(isolated_db):
    resp = client.post("/jobs/no-such-job/chat", json={"message": "hi"})
    assert resp.status_code == 404


def test_chat_round_trip_persists_history(isolated_db, fake_chat_turn):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    fake_chat_turn.queue.append({
        "reply": "Sure, what would you like to know?",
        "history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "Sure, what would you like to know?"}]},
        ],
        "pending_proposal": None,
    })

    resp = client.post("/jobs/ae-role/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.json() == {"reply": "Sure, what would you like to know?", "pending_proposal": None}

    chat = client.get("/jobs/ae-role/chat").json()
    assert chat["pending_proposal"] is None
    assert chat["messages"] == [
        {"role": "user", "text": "hi"},
        {"role": "assistant", "text": "Sure, what would you like to know?"},
    ]


def test_chat_history_is_passed_to_the_next_turn(isolated_db, fake_chat_turn):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    fake_chat_turn.queue.append({
        "reply": "ok",
        "history": [{"role": "user", "content": "first"}, {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}],
        "pending_proposal": None,
    })
    client.post("/jobs/ae-role/chat", json={"message": "first"})

    fake_chat_turn.queue.append({
        "reply": "ok again",
        "history": [
            {"role": "user", "content": "first"}, {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            {"role": "user", "content": "second"}, {"role": "assistant", "content": [{"type": "text", "text": "ok again"}]},
        ],
        "pending_proposal": None,
    })
    client.post("/jobs/ae-role/chat", json={"message": "second"})

    assert len(fake_chat_turn.calls[1]["history"]) == 2  # the first turn's full history was passed in
    assert fake_chat_turn.calls[1]["message"] == "second"


def test_chat_surfaces_pending_proposal_and_persists_it(isolated_db, fake_chat_turn):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    proposal = {
        "field": "must_have", "action": "remove", "value": "Fabric",
        "description": 'Remove "Fabric" from must have.', "impact": "No candidates evaluated yet.",
        "role_id": "ae-role",
    }
    fake_chat_turn.queue.append({"reply": "Here's the proposed change.", "history": [], "pending_proposal": proposal})

    resp = client.post("/jobs/ae-role/chat", json={"message": "remove Fabric"})
    assert resp.json()["pending_proposal"] == proposal

    chat = client.get("/jobs/ae-role/chat").json()
    assert chat["pending_proposal"] == proposal


def test_confirm_without_pending_proposal_is_400(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post("/jobs/ae-role/chat/confirm", json={"approve": True})
    assert resp.status_code == 400


def test_confirm_yes_actually_applies_the_change(isolated_db, fake_chat_turn):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS", "Fabric"]})

    proposal = {
        "field": "must_have", "action": "remove", "value": "Fabric",
        "description": 'Remove "Fabric" from must have.', "impact": "1 candidate evaluated.",
        "role_id": "ae-role",
    }
    fake_chat_turn.queue.append({"reply": "Proposal ready.", "history": [], "pending_proposal": proposal})
    client.post("/jobs/ae-role/chat", json={"message": "remove Fabric"})

    resp = client.post("/jobs/ae-role/chat/confirm", json={"approve": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True
    assert body["icp"]["must_have"] == ["SaaS"]

    # ICP is really changed, and the pending proposal is cleared
    assert db_storage.load_role("ae-role")["icp"]["must_have"] == ["SaaS"]
    assert client.get("/jobs/ae-role/chat").json()["pending_proposal"] is None


def test_confirm_no_does_not_change_anything(isolated_db, fake_chat_turn):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS", "Fabric"]})

    proposal = {
        "field": "must_have", "action": "remove", "value": "Fabric",
        "description": 'Remove "Fabric" from must have.', "impact": "1 candidate evaluated.",
        "role_id": "ae-role",
    }
    fake_chat_turn.queue.append({"reply": "Proposal ready.", "history": [], "pending_proposal": proposal})
    client.post("/jobs/ae-role/chat", json={"message": "remove Fabric"})

    resp = client.post("/jobs/ae-role/chat/confirm", json={"approve": False})
    assert resp.status_code == 200
    assert resp.json()["applied"] is False

    assert db_storage.load_role("ae-role")["icp"]["must_have"] == ["SaaS", "Fabric"]
    assert client.get("/jobs/ae-role/chat").json()["pending_proposal"] is None
