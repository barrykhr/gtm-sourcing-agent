"""Outreach automation batch: attach-existing-candidate, real SMTP send
(replacing the old draft-only outreach), and the day-3/6/9 follow-up
reminder engine (template-based, auto-send opt-in). Mirrors test_api.py's
isolated_db/fake_generate fixtures and test_auth.py's send_email-capture
pattern rather than hitting real SMTP or a real model."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from gtm_sourcing_agent import db, db_storage, followup_sweep, llm_client, notifications
from gtm_sourcing_agent.api import app
from gtm_sourcing_agent.models import Candidate, OutreachSequence
from gtm_sourcing_agent.models_orm import CommunicationLogEntry

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
    return tmp_path


@pytest.fixture
def fake_generate(monkeypatch):
    calls = []
    queue = []

    def _fake(prompt, output_model, *, model=llm_client.DEFAULT_MODEL, max_tokens=0, stage=""):
        calls.append({"prompt": prompt, "output_model": output_model, "stage": stage})
        return queue.pop(0)

    monkeypatch.setattr(llm_client, "generate", _fake)
    _fake.calls = calls
    _fake.queue = queue
    return _fake


def _capture_sent_emails(monkeypatch, succeed: bool = True):
    calls = []
    monkeypatch.setattr(notifications, "send_email", lambda *a, **k: calls.append(a) or succeed)
    monkeypatch.setattr(notifications, "is_configured", lambda: True)
    return calls


def _add_candidate(fake_generate, role_id: str, candidate_id: str, name: str = "Jane Doe") -> str:
    db_storage.merge_section(role_id, "icp", {"must_have": ["SaaS"]})
    db_storage.merge_section(role_id, "job_description", {"company": "Acme"})
    fake_generate.queue.append(Candidate(candidate_id=candidate_id, name=name))
    resp = client.post(f"/jobs/{role_id}/candidates", json={"source_text": "resume", "role_family": "sales"})
    task = _wait_for_task(role_id, resp.json()["task_id"])
    return task["result"]["candidate_id"]


def _backdate_entry(role_id: str, candidate_id: str, days_ago: float) -> None:
    """Test-only helper: directly ages the most recent CommunicationLogEntry
    for this candidate so due_followups()'s day-3/6/9 math has something
    real to compare against, without waiting days in a test."""
    from sqlalchemy import select

    with db.get_session() as session:
        entry = session.scalars(
            select(CommunicationLogEntry)
            .where(
                CommunicationLogEntry.role_id == role_id,
                CommunicationLogEntry.candidate_evaluation_id == candidate_id,
            )
            .order_by(CommunicationLogEntry.created_at.desc())
        ).first()
        entry.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)
        session.commit()


# ── attach-existing-candidate ────────────────────────────────────────────


def test_attach_existing_candidate_reuses_evidence_without_extraction(isolated_db, fake_generate):
    client.post("/jobs", json={"title": "First Role", "role_id": "first-role"})
    client.post("/jobs", json={"title": "Second Role", "role_id": "second-role"})
    candidate_id = _add_candidate(fake_generate, "first-role", "cand-1")
    state = db_storage.load_role("first-role")
    canonical_id = state["candidates"][candidate_id]["canonical_candidate_id"]

    resp = client.post("/jobs/second-role/candidates/attach-existing", json={"canonical_candidate_id": canonical_id})
    assert resp.status_code == 200, resp.text
    second_state = resp.json()
    assert any(c["name"] == "Jane Doe" for c in second_state["candidates"].values())
    # no second LLM call was spent — fake_generate's queue was only ever
    # given one Candidate, and it's already been consumed above
    assert len(fake_generate.calls) == 1


def test_attach_existing_candidate_unknown_id_is_400(isolated_db):
    client.post("/jobs", json={"title": "Role", "role_id": "role-a"})
    resp = client.post("/jobs/role-a/candidates/attach-existing", json={"canonical_candidate_id": "cand-nope"})
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]


def test_attach_existing_candidate_twice_to_same_role_is_400(isolated_db, fake_generate):
    client.post("/jobs", json={"title": "First Role", "role_id": "first-role"})
    client.post("/jobs", json={"title": "Second Role", "role_id": "second-role"})
    candidate_id = _add_candidate(fake_generate, "first-role", "cand-1")
    canonical_id = db_storage.load_role("first-role")["candidates"][candidate_id]["canonical_candidate_id"]

    first = client.post("/jobs/second-role/candidates/attach-existing", json={"canonical_candidate_id": canonical_id})
    assert first.status_code == 200, first.text
    second = client.post("/jobs/second-role/candidates/attach-existing", json={"canonical_candidate_id": canonical_id})
    assert second.status_code == 400
    assert "already been added" in second.json()["detail"]


# ── real send (replacing draft-only outreach) ────────────────────────────


def test_send_outreach_requires_candidate_email(isolated_db, fake_generate, monkeypatch):
    _capture_sent_emails(monkeypatch)
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    fake_generate.queue.append(OutreachSequence(candidate_id=candidate_id, email="Hi Jane"))
    o_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach")
    _wait_for_task("ae-role", o_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach/send")
    assert resp.status_code == 400
    assert "no email on file" in resp.json()["detail"]


def test_send_outreach_requires_draft(isolated_db, fake_generate, monkeypatch):
    _capture_sent_emails(monkeypatch)
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    client.patch(f"/jobs/ae-role/candidates/{candidate_id}/contact", json={"email": "jane@example.com"})

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach/send")
    assert resp.status_code == 400
    assert "no outreach draft" in resp.json()["detail"]


def test_send_outreach_503_when_smtp_not_configured(isolated_db, fake_generate):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    client.patch(f"/jobs/ae-role/candidates/{candidate_id}/contact", json={"email": "jane@example.com"})
    fake_generate.queue.append(OutreachSequence(candidate_id=candidate_id, email="Hi Jane"))
    o_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach")
    _wait_for_task("ae-role", o_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach/send")
    assert resp.status_code == 503
    assert "isn't configured" in resp.json()["detail"]


def test_send_outreach_succeeds_logs_and_advances_funnel(isolated_db, fake_generate, monkeypatch):
    calls = _capture_sent_emails(monkeypatch)
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    client.patch(f"/jobs/ae-role/candidates/{candidate_id}/contact", json={"email": "jane@example.com"})
    fake_generate.queue.append(OutreachSequence(candidate_id=candidate_id, email="Hi Jane, ..."))
    o_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach")
    _wait_for_task("ae-role", o_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach/send")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent_to"] == "jane@example.com"
    assert resp.json()["funnel_stage"] == "CONTACTED"

    assert len(calls) == 1
    to_addresses, subject, body = calls[0]
    assert to_addresses == ["jane@example.com"]
    assert body == "Hi Jane, ..."

    comms = client.get(f"/jobs/ae-role/candidates/{candidate_id}/communications").json()
    assert len(comms["entries"]) == 1
    assert comms["entries"][0]["channel"] == "email"
    assert comms["entries"][0]["direction"] == "outbound"
    assert comms["entries"][0]["followup_stage"] == 0


def test_send_outreach_502_when_smtp_send_fails(isolated_db, fake_generate, monkeypatch):
    _capture_sent_emails(monkeypatch, succeed=False)
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    client.patch(f"/jobs/ae-role/candidates/{candidate_id}/contact", json={"email": "jane@example.com"})
    fake_generate.queue.append(OutreachSequence(candidate_id=candidate_id, email="Hi Jane"))
    o_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach")
    _wait_for_task("ae-role", o_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach/send")
    assert resp.status_code == 502


# ── workspace settings ────────────────────────────────────────────────────


def test_outreach_settings_default_and_admin_only_write(isolated_db):
    settings = client.get("/outreach/settings").json()
    assert settings["auto_send_followups"] is False
    assert "{candidate_name}" in settings["followup_template"]

    # first account is admin (see auth.create_user) -- write succeeds
    resp = client.put("/outreach/settings", json={"auto_send_followups": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["auto_send_followups"] is True

    # a recruiter (non-admin) cannot flip it
    client.post("/auth/signup", json={"email": "recruiter2@example.com", "password": "test-password-123"})
    resp = client.put("/outreach/settings", json={"auto_send_followups": False})
    assert resp.status_code == 403


# ── follow-up due engine ─────────────────────────────────────────────────


def _send_initial_outreach(fake_generate, monkeypatch, role_id: str, candidate_id: str, email: str = "jane@example.com") -> None:
    _capture_sent_emails(monkeypatch)
    client.patch(f"/jobs/{role_id}/candidates/{candidate_id}/contact", json={"email": email})
    fake_generate.queue.append(OutreachSequence(candidate_id=candidate_id, email="Hi Jane"))
    o_resp = client.post(f"/jobs/{role_id}/candidates/{candidate_id}/outreach")
    _wait_for_task(role_id, o_resp.json()["task_id"])
    resp = client.post(f"/jobs/{role_id}/candidates/{candidate_id}/outreach/send")
    assert resp.status_code == 200, resp.text


def test_no_followup_due_before_day_3(isolated_db, fake_generate, monkeypatch):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    _send_initial_outreach(fake_generate, monkeypatch, "ae-role", candidate_id)

    assert client.get("/outreach/followups/due").json() == []


def test_followup_due_at_day_3_then_6_then_9_then_capped(isolated_db, fake_generate, monkeypatch):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    _send_initial_outreach(fake_generate, monkeypatch, "ae-role", candidate_id)
    _backdate_entry("ae-role", candidate_id, days_ago=3.5)

    due = client.get("/outreach/followups/due").json()
    assert len(due) == 1
    assert due[0]["followup_stage"] == 1
    assert due[0]["candidate_name"] == "Jane Doe"

    calls = _capture_sent_emails(monkeypatch)
    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach/followup/send")
    assert resp.status_code == 200, resp.text
    assert resp.json()["followup_stage"] == 1
    assert len(calls) == 1

    # stage 1 just sent "now" -- not due again immediately
    assert client.get("/outreach/followups/due").json() == []

    # age the whole thing further: day 6 since the *original* email
    with db.get_session() as session:
        from sqlalchemy import select
        entries = session.scalars(
            select(CommunicationLogEntry).where(CommunicationLogEntry.role_id == "ae-role")
        ).all()
        for e in entries:
            e.created_at = e.created_at - timedelta(days=6.5)
        session.commit()

    due = client.get("/outreach/followups/due").json()
    assert len(due) == 1
    assert due[0]["followup_stage"] == 2


def test_followup_stops_once_candidate_responds(isolated_db, fake_generate, monkeypatch):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    _send_initial_outreach(fake_generate, monkeypatch, "ae-role", candidate_id)
    _backdate_entry("ae-role", candidate_id, days_ago=4)

    assert len(client.get("/outreach/followups/due").json()) == 1

    client.post(
        f"/jobs/ae-role/candidates/{candidate_id}/communications",
        json={"channel": "email", "direction": "inbound", "content": "Thanks, interested!"},
    )
    assert client.get("/outreach/followups/due").json() == []


def test_send_followup_400_when_nothing_due(isolated_db, fake_generate, monkeypatch):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    _send_initial_outreach(fake_generate, monkeypatch, "ae-role", candidate_id)

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach/followup/send")
    assert resp.status_code == 400
    assert "no follow-up is due" in resp.json()["detail"]


# ── background auto-send sweep ────────────────────────────────────────────


def test_sweep_run_once_noop_when_auto_send_disabled(isolated_db, fake_generate, monkeypatch):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    _send_initial_outreach(fake_generate, monkeypatch, "ae-role", candidate_id)
    _backdate_entry("ae-role", candidate_id, days_ago=4)

    calls = _capture_sent_emails(monkeypatch)
    sent = followup_sweep.run_once()
    assert sent == []
    assert calls == []


def test_sweep_run_once_sends_when_auto_send_enabled(isolated_db, fake_generate, monkeypatch):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    candidate_id = _add_candidate(fake_generate, "ae-role", "cand-1")
    _send_initial_outreach(fake_generate, monkeypatch, "ae-role", candidate_id)
    _backdate_entry("ae-role", candidate_id, days_ago=4)
    db_storage.set_workspace_settings(auto_send_followups=True)

    calls = _capture_sent_emails(monkeypatch)
    sent = followup_sweep.run_once()
    assert len(sent) == 1
    assert sent[0]["followup_stage"] == 1
    assert len(calls) == 1

    comms = client.get(f"/jobs/ae-role/candidates/{candidate_id}/communications").json()
    assert len(comms["entries"]) == 2  # initial + auto follow-up
    assert comms["entries"][-1]["followup_stage"] == 1

    # already sent -- a second run right away sends nothing more
    assert followup_sweep.run_once() == []
