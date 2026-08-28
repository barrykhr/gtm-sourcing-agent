"""Outbound integration webhooks — Phase 8 (docs/product-plan.md). A real
HTTP POST to a URL the recruiter configures themselves for their own job
(the same pattern as a Slack incoming webhook or a Zapier catch hook),
never a fabricated "sent" state (Architecture §1.4/§7's never-fake-
capabilities rule) — this module either genuinely delivers the payload or
reports exactly why it didn't.

Delivery is always best-effort: a bad or unreachable URL must never break
the real recruiter action (setting a decision, sending a test payload) it
rides along with, so `send_webhook` never raises — every outcome, success
or failure, comes back as a result dict for the caller to log.
"""

from typing import Any

import httpx

_TIMEOUT_SECONDS = 5.0


def send_webhook_request(url: str, payload: dict[str, Any]) -> httpx.Response:
    """The one network call in this module — its own function so tests
    can monkeypatch this single boundary (same pattern as llm_client's
    generate()) instead of mocking httpx itself."""
    return httpx.post(url, json=payload, timeout=_TIMEOUT_SECONDS)


def send_webhook(url: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = {"event": event, **payload}
    try:
        response = send_webhook_request(url, body)
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"could not reach webhook URL: {e}"}
    if response.status_code >= 400:
        return {"ok": False, "detail": f"webhook URL returned HTTP {response.status_code}"}
    return {"ok": True, "detail": f"delivered (HTTP {response.status_code})"}
