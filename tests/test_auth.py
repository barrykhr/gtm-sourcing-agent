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
    assert client.get("/auth/status").json() == {"signup_requires_code": False, "google_client_id": None}


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
    assert client.get("/auth/status").json() == {"signup_requires_code": True, "google_client_id": None}

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


# ── Google Sign-In ──────────────────────────────────────────────────────
# _verify_google_id_token is the one function that talks to Google's
# network endpoint — monkeypatched everywhere below, same "swap what's
# below" pattern mock_llm_server.py uses for llm_client.generate.


def test_google_login_is_400_when_not_configured(isolated_db):
    assert auth.GOOGLE_CLIENT_ID is None  # unset by default in this test env
    resp = client.post("/auth/google", json={"credential": "whatever"})
    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"]


def test_google_login_creates_account_and_authenticates(isolated_db, monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(auth, "_verify_google_id_token", lambda credential: "recruiter@example.com")
    resp = client.post("/auth/google", json={"credential": "signed-token"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "recruiter@example.com"
    assert client.get("/auth/me").json()["email"] == "recruiter@example.com"


def test_google_login_is_idempotent_for_the_same_email(isolated_db, monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(auth, "_verify_google_id_token", lambda credential: "recruiter@example.com")
    first = client.post("/auth/google", json={"credential": "token-1"}).json()
    client.post("/auth/logout")
    second = client.post("/auth/google", json={"credential": "token-2"}).json()
    assert first["id"] == second["id"]


def test_google_login_enforces_allowed_domain(isolated_db, monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(auth, "GOOGLE_ALLOWED_DOMAIN", "acme.com")
    monkeypatch.setattr(auth, "_verify_google_id_token", lambda credential: "outsider@gmail.com")
    resp = client.post("/auth/google", json={"credential": "signed-token"})
    assert resp.status_code == 400
    assert "not on the allowed domain" in resp.json()["detail"]

    monkeypatch.setattr(auth, "_verify_google_id_token", lambda credential: "recruiter@acme.com")
    resp = client.post("/auth/google", json={"credential": "signed-token"})
    assert resp.status_code == 200, resp.text


def test_google_created_account_cannot_log_in_with_a_password(isolated_db, monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(auth, "_verify_google_id_token", lambda credential: "recruiter@example.com")
    client.post("/auth/google", json={"credential": "signed-token"})
    client.cookies.clear()
    resp = client.post("/auth/login", json={"email": "recruiter@example.com", "password": "guessed-password"})
    assert resp.status_code == 401


# ── roles (production-readiness phase) ──────────────────────────────────


def test_first_account_on_a_fresh_deployment_becomes_admin(isolated_db):
    resp = client.post("/auth/signup", json={"email": "first@example.com", "password": "hunter22"})
    assert resp.json()["role"] == "admin"


def test_second_account_defaults_to_recruiter(isolated_db):
    client.post("/auth/signup", json={"email": "first@example.com", "password": "hunter22"})
    client.post("/auth/logout")
    resp = client.post("/auth/signup", json={"email": "second@example.com", "password": "hunter22"})
    assert resp.json()["role"] == "recruiter"


def test_google_first_account_also_becomes_admin(isolated_db, monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(auth, "_verify_google_id_token", lambda credential: "founder@example.com")
    resp = client.post("/auth/google", json={"credential": "signed-token"})
    assert resp.json()["role"] == "admin"


def test_login_response_carries_role(isolated_db):
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")
    resp = client.post("/auth/login", json={"email": "r@example.com", "password": "hunter22"})
    assert resp.json()["role"] == "admin"


def test_recruiter_cannot_list_users_or_change_roles(isolated_db):
    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})  # bootstraps admin
    client.post("/auth/logout")
    recruiter = client.post("/auth/signup", json={"email": "recruiter@example.com", "password": "hunter22"})
    recruiter_id = recruiter.json()["id"]

    assert client.get("/users").status_code == 403
    assert client.patch(f"/users/{recruiter_id}/role", json={"role": "admin"}).status_code == 403


def test_admin_can_list_users_and_promote_a_recruiter(isolated_db):
    admin = client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})
    admin_id = admin.json()["id"]
    client.post("/auth/logout")
    recruiter = client.post("/auth/signup", json={"email": "recruiter@example.com", "password": "hunter22"})
    recruiter_id = recruiter.json()["id"]
    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "admin@example.com", "password": "hunter22"})

    listed = client.get("/users").json()
    assert {u["id"]: u["role"] for u in listed} == {admin_id: "admin", recruiter_id: "recruiter"}

    promoted = client.patch(f"/users/{recruiter_id}/role", json={"role": "admin"})
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "admin"
    assert {u["role"] for u in client.get("/users").json()} == {"admin"}


def test_client_and_interviewer_are_not_assignable_yet(isolated_db):
    admin = client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})
    admin_id = admin.json()["id"]
    resp = client.patch(f"/users/{admin_id}/role", json={"role": "client"})
    assert resp.status_code == 400
    assert "not an assignable role" in resp.json()["detail"]


def test_first_account_signup_does_not_notify_anyone(isolated_db, monkeypatch):
    from gtm_sourcing_agent import notifications

    calls = []
    monkeypatch.setattr(notifications, "notify_admins_of_new_signup", lambda *a, **k: calls.append(a) or True)
    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})
    assert calls == []  # first account IS the admin — no one else to notify


def test_second_account_signup_notifies_the_existing_admin(isolated_db, monkeypatch):
    from gtm_sourcing_agent import notifications

    calls = []
    monkeypatch.setattr(notifications, "notify_admins_of_new_signup", lambda *a, **k: calls.append(a) or True)
    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})
    client.post("/auth/logout")
    client.post("/auth/signup", json={"email": "recruiter@example.com", "password": "hunter22"})

    assert len(calls) == 1
    new_email, new_role, admin_emails = calls[0]
    assert new_email == "recruiter@example.com"
    assert new_role == "recruiter"
    assert admin_emails == ["admin@example.com"]


def test_signup_notification_failure_does_not_break_signup(isolated_db, monkeypatch):
    from gtm_sourcing_agent import notifications

    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})
    client.post("/auth/logout")

    def _boom(*a, **k):
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr(notifications, "notify_admins_of_new_signup", _boom)
    resp = client.post("/auth/signup", json={"email": "recruiter@example.com", "password": "hunter22"})
    assert resp.status_code == 200, resp.text


def test_returning_google_login_does_not_renotify(isolated_db, monkeypatch):
    from gtm_sourcing_agent import auth as auth_module, notifications

    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})
    client.post("/auth/logout")

    monkeypatch.setattr(auth_module, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(auth_module, "_verify_google_id_token", lambda credential: "recruiter@example.com")

    calls = []
    monkeypatch.setattr(notifications, "notify_admins_of_new_signup", lambda *a, **k: calls.append(a) or True)

    client.post("/auth/google", json={"credential": "token-1"})
    assert len(calls) == 1  # first Google sign-in creates the account -> notify

    client.post("/auth/logout")
    client.post("/auth/google", json={"credential": "token-2"})
    assert len(calls) == 1  # same account logging back in -> no second notification


def _capture_sent_emails(monkeypatch):
    """Patches notifications.send_email (used directly by api.py's
    /auth/forgot-password) to record calls instead of touching a real
    SMTP server, mirroring the notify_admins_of_new_signup fakes above."""
    from gtm_sourcing_agent import notifications

    calls = []
    monkeypatch.setattr(notifications, "send_email", lambda *a, **k: calls.append(a) or True)
    return calls


def test_forgot_password_response_is_identical_for_known_and_unknown_email(isolated_db, monkeypatch):
    _capture_sent_emails(monkeypatch)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")

    known = client.post("/auth/forgot-password", json={"email": "r@example.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_forgot_password_only_emails_for_a_known_account(isolated_db, monkeypatch):
    # Recipient routing (own address vs. the hardcoded/env override) is
    # covered by the tests above -- this one is purely about whether an
    # email goes out at all, so it disables the hardcoded default to
    # keep that assertion independent of it.
    from gtm_sourcing_agent import api as api_module

    calls = _capture_sent_emails(monkeypatch)
    monkeypatch.setattr(api_module, "FORGOT_PASSWORD_HARDCODED_RECIPIENT", None)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")

    client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert calls == []

    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    assert len(calls) == 1
    to_addresses, subject, body = calls[0]
    assert to_addresses == ["r@example.com"]
    assert "reset" in subject.lower()
    assert "/reset-password?token=" in body


def test_forgot_password_routes_to_override_recipient_when_set(isolated_db, monkeypatch):
    calls = _capture_sent_emails(monkeypatch)
    monkeypatch.setenv("FORGOT_PASSWORD_OVERRIDE_RECIPIENT", "admin-catchall@example.com")
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")

    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    assert len(calls) == 1
    to_addresses, _subject, body = calls[0]
    assert to_addresses == ["admin-catchall@example.com"]
    assert "Password reset requested for account: r@example.com" in body


def test_forgot_password_routes_to_hardcoded_recipient_by_default(isolated_db, monkeypatch):
    # The env var is the ops-level override; the hardcoded constant is
    # the code-level default that applies when it's unset -- this is
    # today's actual out-of-the-box behavior, not just a config option.
    from gtm_sourcing_agent import api as api_module

    calls = _capture_sent_emails(monkeypatch)
    monkeypatch.delenv("FORGOT_PASSWORD_OVERRIDE_RECIPIENT", raising=False)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")

    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    assert len(calls) == 1
    to_addresses, _subject, body = calls[0]
    assert to_addresses == [api_module.FORGOT_PASSWORD_HARDCODED_RECIPIENT]
    assert "Password reset requested for account: r@example.com" in body


def test_forgot_password_sends_to_requesting_email_when_no_override_configured(isolated_db, monkeypatch):
    from gtm_sourcing_agent import api as api_module

    calls = _capture_sent_emails(monkeypatch)
    monkeypatch.delenv("FORGOT_PASSWORD_OVERRIDE_RECIPIENT", raising=False)
    monkeypatch.setattr(api_module, "FORGOT_PASSWORD_HARDCODED_RECIPIENT", None)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")

    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    assert len(calls) == 1
    to_addresses, _subject, body = calls[0]
    assert to_addresses == ["r@example.com"]
    assert "Password reset requested for account:" not in body


def test_non_admin_cannot_call_test_email(isolated_db):
    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})
    client.post("/auth/logout")
    client.post("/auth/signup", json={"email": "recruiter@example.com", "password": "hunter22"})

    resp = client.post("/admin/test-email", json={"to": "recruiter@example.com"})
    assert resp.status_code == 403


def test_admin_test_email_reports_missing_env_vars(isolated_db, monkeypatch):
    # No SMTP_* env vars are set in the test environment, so this should
    # report exactly which ones are missing -- the actual bug hit in
    # production (a misnamed SMTP_FROM_ADDRESS) rather than a generic
    # failure.
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_ADDRESS"):
        monkeypatch.delenv(name, raising=False)
    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})

    resp = client.post("/admin/test-email", json={"to": "admin@example.com"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False
    assert "SMTP_FROM_ADDRESS" in body["error"]


def test_admin_test_email_reports_real_smtp_exception(isolated_db, monkeypatch):
    from gtm_sourcing_agent import notifications

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "wrong-password")
    monkeypatch.setenv("SMTP_FROM_ADDRESS", "user@example.com")

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a, **k):
            raise notifications.smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(notifications.smtplib, "SMTP", _FakeSMTP)
    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})

    resp = client.post("/admin/test-email", json={"to": "admin@example.com"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False
    assert "SMTPAuthenticationError" in body["error"]


def test_admin_test_email_reports_success(isolated_db, monkeypatch):
    from gtm_sourcing_agent import notifications

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "correct-password")
    monkeypatch.setenv("SMTP_FROM_ADDRESS", "user@example.com")

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a, **k):
            pass

        def sendmail(self, *a, **k):
            pass

    monkeypatch.setattr(notifications.smtplib, "SMTP", _FakeSMTP)
    client.post("/auth/signup", json={"email": "admin@example.com", "password": "hunter22"})

    resp = client.post("/admin/test-email", json={"to": "admin@example.com"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sent": True, "error": None}


def test_reset_password_with_unknown_token_is_400(isolated_db):
    resp = client.post("/auth/reset-password", json={"token": "not-a-real-token", "new_password": "newpassword1"})
    assert resp.status_code == 400
    assert "invalid or expired" in resp.json()["detail"]


def test_reset_password_rejects_short_password(isolated_db, monkeypatch):
    calls = _capture_sent_emails(monkeypatch)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")
    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    token = calls[0][2].split("token=")[1].split("\n")[0].strip()

    resp = client.post("/auth/reset-password", json={"token": token, "new_password": "short"})
    assert resp.status_code == 400
    assert "8 characters" in resp.json()["detail"]


def test_reset_password_changes_the_password_and_logs_in_with_the_new_one(isolated_db, monkeypatch):
    calls = _capture_sent_emails(monkeypatch)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")
    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    token = calls[0][2].split("token=")[1].split("\n")[0].strip()

    resp = client.post("/auth/reset-password", json={"token": token, "new_password": "brandnewpw"})
    assert resp.status_code == 200, resp.text

    assert client.post("/auth/login", json={"email": "r@example.com", "password": "hunter22"}).status_code == 401
    assert client.post("/auth/login", json={"email": "r@example.com", "password": "brandnewpw"}).status_code == 200


def test_reset_password_token_is_single_use(isolated_db, monkeypatch):
    calls = _capture_sent_emails(monkeypatch)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")
    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    token = calls[0][2].split("token=")[1].split("\n")[0].strip()

    first = client.post("/auth/reset-password", json={"token": token, "new_password": "brandnewpw"})
    assert first.status_code == 200, first.text

    second = client.post("/auth/reset-password", json={"token": token, "new_password": "anotherpw1"})
    assert second.status_code == 400
    assert "invalid or expired" in second.json()["detail"]


def test_reset_password_replaces_any_outstanding_token_for_the_account(isolated_db, monkeypatch):
    calls = _capture_sent_emails(monkeypatch)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")

    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    old_token = calls[0][2].split("token=")[1].split("\n")[0].strip()
    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    new_token = calls[1][2].split("token=")[1].split("\n")[0].strip()
    assert old_token != new_token

    stale = client.post("/auth/reset-password", json={"token": old_token, "new_password": "brandnewpw"})
    assert stale.status_code == 400

    fresh = client.post("/auth/reset-password", json={"token": new_token, "new_password": "brandnewpw"})
    assert fresh.status_code == 200, fresh.text


def test_reset_password_invalidates_existing_sessions(isolated_db, monkeypatch):
    calls = _capture_sent_emails(monkeypatch)
    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    # This client instance's cookie jar now holds a live session for the
    # account — reset_password must kill it even though the reset itself
    # happens over a separate, cookie-less request (as it would in
    # reality: a different browser/tab that clicked the email link).
    assert client.get("/auth/me").status_code == 200

    client.post("/auth/forgot-password", json={"email": "r@example.com"})
    token = calls[0][2].split("token=")[1].split("\n")[0].strip()
    resp = client.post("/auth/reset-password", json={"token": token, "new_password": "brandnewpw"})
    assert resp.status_code == 200, resp.text

    assert client.get("/auth/me").status_code == 401


def test_expired_reset_token_is_rejected(isolated_db):
    from datetime import UTC, datetime, timedelta

    from gtm_sourcing_agent import auth as auth_module, db
    from gtm_sourcing_agent.models_orm import PasswordResetToken

    client.post("/auth/signup", json={"email": "r@example.com", "password": "hunter22"})
    client.post("/auth/logout")
    token = auth_module.create_password_reset_token("r@example.com")
    assert token is not None

    # Directly age the token in the DB to simulate the TTL having
    # elapsed, rather than waiting an hour or monkeypatching a constant
    # that's only read at token-creation time.
    with db.get_session() as db_session:
        reset = db_session.get(PasswordResetToken, token)
        reset.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        db_session.commit()

    resp = client.post("/auth/reset-password", json={"token": token, "new_password": "brandnewpw"})
    assert resp.status_code == 400
    assert "invalid or expired" in resp.json()["detail"]
