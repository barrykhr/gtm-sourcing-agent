import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Reuse the app's own DATABASE_URL resolution (postgres:// -> postgresql://
# rewrite, SQLite fallback) instead of duplicating that logic in
# alembic.ini — one source of truth for "what database are we talking
# to," same reasoning as everywhere else in this codebase.
from gtm_sourcing_agent.db import _database_url  # noqa: E402
from gtm_sourcing_agent.models_orm import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
# set_main_option() is backed by configparser, which treats a bare '%' in
# a value as the start of an interpolation reference and raises
# ValueError if what follows isn't valid interpolation syntax — a
# percent-encoded password in DATABASE_URL (e.g. '%40' for '@', which a
# managed Postgres provider's generated password can easily contain)
# trips this. '%%' is configparser's own escape for a literal '%', so
# double every '%' here — same fix as db.py's _run_migrations, needed
# independently since this call also goes through set_main_option and
# isn't reached through that function when `alembic` is invoked directly
# from the CLI (see migrations/README) rather than via db.py.
config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        # SQLite (local dev default) can't ALTER most columns directly —
        # batch mode rebuilds the table under the hood instead. Postgres
        # (production) ignores this and just runs plain ALTER statements.
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            compare_type=True, render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
