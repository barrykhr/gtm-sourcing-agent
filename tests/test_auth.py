"""Phase 7 auth, extended to multiple accounts in Phase 8
(docs/product-plan.md). Exercises the real HTTP layer via TestClient,
same pattern as test_api.py, but deliberately does NOT use test_api.py's
isolated_db fixture (which auto-signs-up a user) — auth's own tests need
to control signup/login/logout precisely."""

import pytest
from fastapi.testclient import TestClient

from gtm_sourcing_agent import auth, db
from gtm_sourcing_agent.api import app

client = TestClient(app)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    client.cookies.clear()
    return tmp_path


def test_unauthenticated_request_is_rejected(isolated_db):
    assert client.get("/jobs").status_code == 401


def test_health_and_auth_status_are_public(isolated_db):
    assert client.get("/health").status_code == 200
    assert client.get("/auth/status").json() == {"signup_requires_code": False}


def test_signup_then_authenticated_request_succeeds(isolated_db):
    resp = client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "r@example.com"
    assert client.get("/jobs").status_code == 200


def test_signup_allows_multiple_distinct_accounts(isolated_db):
    r1 = client.post("/auth/signup", json={"email": "r1@example.com", "password": "hunter22"})
    assert r1.status_code == 200, r1.text
    client.post("/auth/logout")
    r2 = client.post("/auth/signup", json={"email": "r2@example.com", "password": "hunter22"})
    assert r2.status_code == 200, r2.text
    assert client.get("/auth/me").json()["email"] == "r2@example.com"


def test_signup_refuses_duplicate_email(isolated_db):
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    resp = client.post("/auth/signup", json={"email": "r@example.com", "password": "different-pw"})
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


def test_signup_rejects_short_password(isolated_db):
    resp = client.post("/auth/signup", json={"email": "r@example.com", "password": "short"})
    assert resp.status_code == 400
    assert "8 characters" in resp.json()["detail"]


def test_signup_code_gate(isolated_db, monkeypatch):
    monkeypatch.setattr(auth, "SIGNUP_CODE", "let-me-in")
    assert client.get("/auth/status").json() == {"signup_requires_code": True}

    wrong = client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    assert wrong.status_code == 400
    assert "invalid signup code" in wrong.json()["detail"]

    right = client.post(
        "/auth/signup", json={"email": "r@example.com", "password": "hunter22", "signup_code": "let-me-in"}
    )
    assert right.status_code == 200, right.text


def test_login_wrong_password_is_401(isolated_db):
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.cookies.clear()
    resp = client.post("/auth/login", json={"email": "r@example.com", "password": "wrong"})
    assert resp.status_code == 401
    assert client.get("/jobs").status_code == 401


def test_login_unknown_email_is_401(isolated_db):
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": "hunter22"})
    assert resp.status_code == 401


def test_logout_ends_the_session(isolated_db):
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    assert client.get("/jobs").status_code == 200
    client.post("/auth/logout")
    assert client.get("/jobs").status_code == 401


def test_me_returns_the_logged_in_user(isolated_db):
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    assert client.get("/auth/me").json()["email"] == "r@example.com"


def test_session_survives_login_after_signup(isolated_db):
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.cookies.clear()
    resp = client.post("/auth/login", json={"email": "r@example.com", "password": "hunter22"})
    assert resp.status_code == 200
    assert client.get("/jobs").status_code == 200


def test_two_accounts_share_the_same_workspace(isolated_db):
    client.post("/auth/signup", json={"email": "r1@example.com", "password": "hunter22"})
    client.post("/jobs", json={"title": "Shared Job", "role_id": "shared-job"})
    client.post("/auth/logout")

    client.post("/auth/signup", json={"email": "r2@example.com", "password": "hunter22"})
    jobs = client.get("/jobs").json()
    assert any(j["role_id"] == "shared-job" for j in jobs)
