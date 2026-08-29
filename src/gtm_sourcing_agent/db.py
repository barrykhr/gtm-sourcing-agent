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
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from .models_orm import Base

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "gtm_sourcing_agent.db"

_engines: dict[str, Engine] = {}


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
    if url not in _engines:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite:") else {}
        engine = create_engine(url, connect_args=connect_args)
        Base.metadata.create_all(engine)
        _engines[url] = engine
    return _engines[url]


def get_session() -> Session:
    return Session(bind=_get_engine())
