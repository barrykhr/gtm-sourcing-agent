"""Outbound integration webhooks (Phase 8, docs/product-plan.md). Mocked
at send_webhook_request — the one real network call in webhooks.py, same
pattern as mocking llm_client.generate — so these tests never touch the
network."""

import httpx

from gtm_sourcing_agent import webhooks


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_send_webhook_reports_success(monkeypatch):
    monkeypatch.setattr(webhooks, "send_webhook_request", lambda url, payload: _FakeResponse(200))
    result = webhooks.send_webhook("https://example.com/hook", "webhook.test", {"role_id": "acme-ae-2026"})
    assert result == {"ok": True, "detail": "delivered (HTTP 200)"}


def test_send_webhook_reports_http_error_status(monkeypatch):
    monkeypatch.setattr(webhooks, "send_webhook_request", lambda url, payload: _FakeResponse(500))
    result = webhooks.send_webhook("https://example.com/hook", "webhook.test", {})
    assert result["ok"] is False
    assert "500" in result["detail"]


def test_send_webhook_reports_connection_failure_without_raising(monkeypatch):
    def _raise(url, payload):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(webhooks, "send_webhook_request", _raise)
    result = webhooks.send_webhook("https://unreachable.example/hook", "webhook.test", {})
    assert result["ok"] is False
    assert "could not reach" in result["detail"]


def test_send_webhook_includes_event_and_payload(monkeypatch):
    captured = {}

    def _capture(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return _FakeResponse(200)

    monkeypatch.setattr(webhooks, "send_webhook_request", _capture)
    webhooks.send_webhook("https://example.com/hook", "candidate.decision.pursue", {"candidate_id": "cand-1"})
    assert captured["url"] == "https://example.com/hook"
    assert captured["payload"] == {"event": "candidate.decision.pursue", "candidate_id": "cand-1"}
