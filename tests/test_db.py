"""Covers db.py's engine-selection logic — defaults to SQLite, switches
to Postgres when DATABASE_URL is set, and normalizes the postgres://
scheme managed providers hand out to the postgresql:// SQLAlchemy needs.
"""

import sqlite3

from sqlalchemy import inspect

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


def test_fresh_db_gets_migrated_to_head(tmp_path, monkeypatch):
    """A brand-new database file should end up with every table Alembic
    knows about, stamped at the latest revision — not just whatever
    create_all() would produce on its own.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    engine = db._get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "alembic_version" in tables
    assert "users" in tables
    assert "role" in {c["name"] for c in inspector.get_columns("users")}

    conn = sqlite3.connect(tmp_path / "test.db")
    try:
        (version,) = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version  # non-empty: migration actually ran, not just stamped blank
    finally:
        conn.close()


def test_legacy_db_missing_role_column_gets_retrofitted(tmp_path, monkeypatch):
    """Reproduces the exact failure this migration exists to prevent:
    a database created by an older version of the app (via
    Base.metadata.create_all(), before `users.role` existed) must come
    up clean through db._get_engine() — not raise "no such column:
    users.role" the way create_all() alone did.
    """
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id VARCHAR NOT NULL,
            email VARCHAR NOT NULL,
            password_hash VARCHAR NOT NULL,
            password_salt VARCHAR NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (email)
        )"""
    )
    conn.execute(
        "INSERT INTO users VALUES ('u1', 'legacy@talyn.dev', 'hash', 'salt', '2026-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    engine = db._get_engine()
    inspector = inspect(engine)
    assert "role" in {c["name"] for c in inspector.get_columns("users")}

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT id, email, role FROM users WHERE id = 'u1'").fetchone()
        assert row == ("u1", "legacy@talyn.dev", "recruiter")
    finally:
        conn.close()
