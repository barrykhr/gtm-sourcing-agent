"""Engine/session management for db_storage.py. Defaults to a local
SQLite file (`DB_PATH` is a mutable module attribute, mirrors
storage.WORKSPACE_DIR, so tests can monkeypatch it to an isolated
tmp_path file — same pattern as tests/test_storage.py).

Set DATABASE_URL to use Postgres instead (Render injects this
automatically once a Postgres instance is attached to the service).
SQLite has no persistence guarantee across a container restart/redeploy
on most hosts — a real deployment holding real candidate data needs
DATABASE_URL set, not the SQLite default.
"""

import os
import threading
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from .models_orm import Base

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "gtm_sourcing_agent.db"
REPO_ROOT = Path(__file__).resolve().parents[2]

_engines: dict[str, Engine] = {}
# Alembic's EnvironmentContext keeps module-level global state across
# enter/exit (see alembic.runtime.environment), which isn't safe to run
# from two threads at once — this app has more than one background
# thread that can call get_session() (task_queue.py's worker,
# followup_sweep.py's sweep), any of which might be the first to touch
# a not-yet-migrated URL at the same moment another thread is migrating
# a different one. Observed concretely as a KeyError deep inside
# Alembic's teardown under test load; this lock serializes engine
# creation (a one-time, per-URL cost) without serializing normal query
# traffic, which never touches this lock.
_engine_lock = threading.Lock()


def _run_migrations(url: str) -> None:
    """Bring the schema at `url` up to the latest Alembic revision.

    `Base.metadata.create_all()` (below) only ever creates tables that
    don't exist yet — it never adds a column to a table that's already
    there. A deployed database that predates a model change (e.g. the
    `users.role` column) would silently keep missing it forever unless
    something actually runs migrations. Doing it here means every path
    that opens the database — the app on startup, a one-off script, a
    test — gets a schema that matches models_orm.py, without depending
    on the hosting platform being configured with a separate release
    step. migrations/versions/d330f3a84db7 is written to be safe to run
    against an already-populated legacy database, not just an empty one.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        # Managed Postgres providers (Render included) hand out
        # postgres:// URLs; SQLAlchemy's psycopg2 dialect requires the
        # postgresql:// scheme spelled out.
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        return url
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def _get_engine() -> Engine:
    url = _database_url()
    if url in _engines:
        return _engines[url]
    with _engine_lock:
        if url in _engines:  # a racing thread may have finished while we waited for the lock
            return _engines[url]
        if url.startswith("sqlite:"):
            connect_args = {"check_same_thread": False}
            pool_kwargs = {}
        else:
            connect_args = {}
            # Managed Postgres (Render included) closes idle connections
            # server-side after a timeout; pool_pre_ping detects a dead
            # connection and transparently reconnects instead of the
            # request failing. Pool size is deliberately small — this is
            # a single small-team app, not a high-concurrency service.
            pool_kwargs = {
                "pool_pre_ping": True,
                "pool_size": 5,
                "max_overflow": 10,
                "pool_recycle": 1800,
            }
        engine = create_engine(url, connect_args=connect_args, **pool_kwargs)
        _run_migrations(url)
        # Safety net only: covers a brand-new table that's in
        # models_orm.py but doesn't have a migration yet. Real schema
        # changes belong in a migration, not a reliance on this line.
        Base.metadata.create_all(engine)
        _engines[url] = engine
    return _engines[url]


def get_session() -> Session:
    return Session(bind=_get_engine())
