"""Background sweep that auto-sends due outreach follow-ups (Outreach
automation batch). Mirrors task_queue.py's single-in-process-thread
design and its "exactly one server process" assumption (see that
module's docstring) — but runs on a timer instead of consuming a queue,
since there's nothing to enqueue here, just a periodic "what's due right
now" check.

Sends nothing unless db_storage.get_workspace_settings()
["auto_send_followups"] is True — off by default (see WorkspaceSettings'
docstring). This is the one place in the app that emails a candidate
with no recruiter clicking "send" that day, so it stays inert until a
recruiter explicitly opts in.
"""

import logging
import threading
import time
from typing import Any

from . import db_storage, notifications

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours -- a day-granularity cadence doesn't need finer polling

_started = False
_start_lock = threading.Lock()


def run_once() -> list[dict[str, Any]]:
    """Sends every currently-due follow-up if the workspace has opted
    in. Returns the entries actually sent (empty whether that's because
    nothing is due or because auto-send is off, same "no-op when
    unconfigured" convention as notifications.send_email). Exposed
    separately from the sleep loop below so it's directly callable —
    from tests, and from api.py if a manual "run the sweep now" action
    is ever added."""
    settings = db_storage.get_workspace_settings()
    if not settings["auto_send_followups"]:
        return []
    sent: list[dict[str, Any]] = []
    for entry in db_storage.due_followups():
        if not notifications.send_email(
            [entry["email"]], f"Following up: {entry['role_title']}", entry["draft_message"],
        ):
            logger.warning(
                "followup sweep: failed to send stage %s to %s (role %s)",
                entry["followup_stage"], entry["email"], entry["role_id"],
            )
            continue
        db_storage.log_communication(
            entry["role_id"], entry["candidate_id"], channel="email", direction="outbound",
            content=entry["draft_message"], contact_used=entry["email"], logged_by="auto-followup",
            followup_stage=entry["followup_stage"],
        )
        sent.append(entry)
    if sent:
        logger.info("followup sweep: auto-sent %d follow-up(s)", len(sent))
    return sent


def _loop() -> None:
    while True:
        time.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            run_once()
        except Exception:  # the sweep thread must never die over one bad candidate/send
            logger.exception("followup sweep: unhandled error")


def start() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        threading.Thread(target=_loop, name="gtm-followup-sweep", daemon=True).start()
        _started = True
