"""SQLite engine/session management for db_storage.py. `DB_PATH` is a
mutable module attribute (mirrors storage.WORKSPACE_DIR) so tests can
monkeypatch it to an isolated tmp_path file, same pattern as
tests/test_storage.py.
"""

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from .models_orm import Base

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "gtm_sourcing_agent.db"

_engines: dict[str, Engine] = {}


def _get_engine() -> Engine:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    if key not in _engines:
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        _engines[key] = engine
    return _engines[key]


def get_session() -> Session:
    return Session(bind=_get_engine())
