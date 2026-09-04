"""In-process background task worker — Phase 4 (async + scale,
docs/product-plan.md). Every LLM-touching stage call in api.py is
enqueued here instead of running inline in the request handler, so a
slow real model call (real Anthropic latency, not the mock's instant
canned response) never blocks the HTTP response or ties up a request
thread for its whole duration.

Deliberately a single dedicated worker thread pulling task ids off a
queue.Queue, not a pool. Concurrent writer threads against the SQLite
file caused real "database is locked" / "attempt to write a readonly
database" failures during development (see db.py) — a single sequential
worker sidesteps that entirely, with no WAL-mode tuning and no external
broker (Celery/Redis) this product doesn't need yet at this scale. If
job volume ever outgrows one worker, swap the queue for a real broker;
nothing above task_queue.py (api.py's routes) would need to change,
same "swap storage backends, never change what's above them" pattern
Phase 1 established for db_storage.py.

This module knows nothing about stages/*.py — api.py registers a
zero-context runner per task `kind` via register_runner(), keeping the
dependency direction one-way (api.py -> stages/*.py), unchanged from
before this phase.
"""

import logging
import queue
import threading
from typing import Any, Callable

from . import db_storage

logger = logging.getLogger(__name__)

TaskRunner = Callable[[str, dict[str, Any]], dict[str, Any]]

_queue: "queue.Queue[str]" = queue.Queue()
_runners: dict[str, TaskRunner] = {}
_worker_started = False
_start_lock = threading.Lock()


def _recover_orphaned_tasks() -> None:
    """Runs once per process, from _ensure_worker() below, before the
    worker thread starts and before this call's own enqueue() creates
    its task row. This process's in-memory queue starts empty regardless
    of what the database says — so any task left "pending" or "running"
    from a previous process (crash, redeploy) is orphaned: nothing will
    ever finish it. Mark those failed so the recruiter sees an honest
    "this didn't complete, try again" instead of a spinner that never
    resolves.

    This assumes exactly one server process/instance, same as the rest
    of this module (see the module docstring). Running more than one
    instance would make this actively wrong — a second instance's
    startup would mark the first instance's genuinely in-flight tasks
    as failed. Do not scale this app horizontally without replacing the
    in-memory queue with something that coordinates across processes.
    """
    count = db_storage.reset_incomplete_tasks(
        "Interrupted by a server restart before it finished. Please retry."
    )
    if count:
        logger.warning("task worker: recovered %d orphaned task(s) left by a previous process", count)


def register_runner(kind: str, fn: TaskRunner) -> None:
    """Register how to execute a task of the given `kind`. `fn(role_id,
    args)` must return a JSON-serializable result (a stage's own
    `.model_dump()`) or raise ValueError/RuntimeError, same contract
    stage functions already have via storage_backend."""
    _runners[kind] = fn


def enqueue(role_id: str, kind: str, args: dict[str, Any]) -> dict[str, Any]:
    if kind not in _runners:
        raise ValueError(f"no task runner registered for kind '{kind}'")
    # Recovery must run before this task's own row is created below —
    # otherwise the very first enqueue() of a process would immediately
    # mark its own brand-new "pending" task as orphaned.
    _ensure_worker()
    task = db_storage.create_task(role_id, kind, args)
    _queue.put(task["task_id"])
    return task


def _ensure_worker() -> None:
    global _worker_started
    with _start_lock:
        if _worker_started:
            return
        _recover_orphaned_tasks()
        threading.Thread(target=_worker_loop, name="gtm-task-worker", daemon=True).start()
        _worker_started = True


def _worker_loop() -> None:
    while True:
        task_id = _queue.get()
        try:
            _run_one(task_id)
        except Exception:  # the worker thread must never die — one bad task shouldn't wedge every task after it
            logger.exception("task worker: unhandled error processing task %s", task_id)
        finally:
            _queue.task_done()


def _run_one(task_id: str) -> None:
    task = db_storage.get_task(task_id)
    if task is None:
        logger.warning("task worker: task %s vanished before it could run", task_id)
        return
    runner = _runners.get(task["kind"])
    if runner is None:
        db_storage.update_task(task_id, status="failed", error=f"no runner registered for kind '{task['kind']}'")
        return
    db_storage.update_task(task_id, status="running")
    try:
        result = runner(task["role_id"], task["args"])
    except (ValueError, RuntimeError) as e:
        # same two exception types _run_stage used to map to 400/502 — now
        # surfaced as a failed task's .error instead of an HTTP status,
        # since there's no request left open to carry a status code by the
        # time a real model call finishes.
        db_storage.update_task(task_id, status="failed", error=str(e))
    except Exception as e:  # unexpected — still surface it, never leave a task stuck "running" forever
        logger.exception("task worker: unexpected error running task %s (kind=%s)", task_id, task["kind"])
        db_storage.update_task(task_id, status="failed", error=f"unexpected error: {e}")
    else:
        db_storage.update_task(task_id, status="succeeded", result=result)
