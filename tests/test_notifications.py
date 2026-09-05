"""Covers notifications.py's admin new-signup email — configured entirely
through SMTP_* env vars, a no-op when unset, and never allowed to raise.
"""

import smtplib

import pytest

from gtm_sourcing_agent import notifications


@pytest.fixture
def unconfigured(monkeypatch):
    for var in (
        notifications.ENV_HOST,
        notifications.ENV_PORT,
        notifications.ENV_USERNAME,
        notifications.ENV_PASSWORD,
        notifications.ENV_FROM_ADDRESS,
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(notifications.ENV_HOST, "smtp.example.com")
    monkeypatch.setenv(notifications.ENV_PORT, "587")
    monkeypatch.setenv(notifications.ENV_USERNAME, "apikey")
    monkeypatch.setenv(notifications.ENV_PASSWORD, "secret")
    monkeypatch.setenv(notifications.ENV_FROM_ADDRESS, "talyn@example.com")


def test_is_configured_false_when_env_vars_missing(unconfigured):
    assert notifications.is_configured() is False


def test_is_configured_true_when_all_required_vars_set(configured):
    assert notifications.is_configured() is True


def test_send_email_returns_false_when_not_configured(unconfigured):
    assert notifications.send_email(["admin@example.com"], "subject", "body") is False


def test_send_email_returns_false_with_no_recipients(configured):
    assert notifications.send_email([], "subject", "body") is False


class _FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        self.username, self.password = username, password

    def sendmail(self, from_addr, to_addrs, message):
        _FakeSMTP.sent.append((from_addr, to_addrs, message))


def test_send_email_succeeds_with_a_working_smtp_server(configured, monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    ok = notifications.send_email(["admin@example.com"], "New account", "someone signed up")
    assert ok is True
    assert len(_FakeSMTP.sent) == 1
    from_addr, to_addrs, message = _FakeSMTP.sent[0]
    assert from_addr == "talyn@example.com"
    assert to_addrs == ["admin@example.com"]
    assert "New account" in message
    assert "someone signed up" in message


class _RaisingSMTP:
    def __init__(self, host, port, timeout=None):
        raise ConnectionRefusedError("nope")


def test_send_email_never_raises_when_smtp_fails(configured, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _RaisingSMTP)
    assert notifications.send_email(["admin@example.com"], "subject", "body") is False


def test_notify_admins_returns_false_with_no_admin_emails(configured):
    assert notifications.notify_admins_of_new_signup("new@example.com", "recruiter", []) is False


def test_notify_admins_sends_to_every_admin(configured, monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    ok = notifications.notify_admins_of_new_signup(
        "new@example.com", "recruiter", ["admin1@example.com", "admin2@example.com"]
    )
    assert ok is True
    _, to_addrs, message = _FakeSMTP.sent[0]
    assert to_addrs == ["admin1@example.com", "admin2@example.com"]
    assert "new@example.com" in message
    assert "recruiter" in message
