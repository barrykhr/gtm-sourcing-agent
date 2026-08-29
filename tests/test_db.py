"""Covers db.py's engine-selection logic — defaults to SQLite, switches
to Postgres when DATABASE_URL is set, and normalizes the postgres://
scheme managed providers hand out to the postgresql:// SQLAlchemy needs.
"""

from gtm_sourcing_agent import db


def test_database_url_defaults_to_sqlite_db_path(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    assert db._database_url() == f"sqlite:///{tmp_path / 'test.db'}"


def test_database_url_uses_env_var_when_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host:5432/dbname")
    assert db._database_url() == "postgresql://user:pw@host:5432/dbname"


def test_database_url_normalizes_postgres_scheme(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@host:5432/dbname")
    assert db._database_url() == "postgresql://user:pw@host:5432/dbname"


def test_get_session_still_works_against_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    session = db.get_session()
    try:
        assert session.bind is not None
    finally:
        session.close()
