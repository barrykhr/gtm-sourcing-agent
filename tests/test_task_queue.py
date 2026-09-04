"""Covers the orphaned-task recovery path added for production
readiness: task_queue.py's worker queue is in-memory (see its module
docstring) and never survives a process restart, so a task left
"pending" or "running" in the database by a killed process must be
recovered — not left looking like a request that never finished.
"""

from gtm_sourcing_agent import db, db_storage, task_queue


def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")


def test_reset_incomplete_tasks_marks_pending_and_running_as_failed(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    db_storage.create_job("r1")
    pending = db_storage.create_task("r1", "icp", {})
    running = db_storage.create_task("r1", "talent_map", {})
    db_storage.update_task(running["task_id"], status="running")
    done = db_storage.create_task("r1", "calibrate", {})
    db_storage.update_task(done["task_id"], status="succeeded", result={"ok": True})

    count = db_storage.reset_incomplete_tasks("orphaned by a restart")

    assert count == 2
    pending_after = db_storage.get_task(pending["task_id"])
    running_after = db_storage.get_task(running["task_id"])
    done_after = db_storage.get_task(done["task_id"])
    assert pending_after["status"] == "failed"
    assert pending_after["error"] == "orphaned by a restart"
    assert pending_after["finished_at"] is not None
    assert running_after["status"] == "failed"
    # a task that had already finished, one way or another, must be left alone
    assert done_after["status"] == "succeeded"
    assert done_after["error"] is None


def test_reset_incomplete_tasks_is_a_noop_when_nothing_is_stuck(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    db_storage.create_job("r1")
    task = db_storage.create_task("r1", "icp", {})
    db_storage.update_task(task["task_id"], status="succeeded", result={})

    assert db_storage.reset_incomplete_tasks("orphaned by a restart") == 0
    assert db_storage.get_task(task["task_id"])["status"] == "succeeded"


def test_recover_orphaned_tasks_delegates_to_db_storage(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    db_storage.create_job("r1")
    stuck = db_storage.create_task("r1", "icp", {})
    db_storage.update_task(stuck["task_id"], status="running")

    task_queue._recover_orphaned_tasks()

    assert db_storage.get_task(stuck["task_id"])["status"] == "failed"
