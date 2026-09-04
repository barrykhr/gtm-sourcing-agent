"""baseline schema

Retrofit-safe by design: this is the first Alembic migration in the
project, and the app previously relied on ``Base.metadata.create_all()``
at startup, which creates missing TABLES but never adds missing COLUMNS
to a table that already exists. Any already-deployed database may
therefore already have some or all of these tables (just missing the
most recently added columns, e.g. ``users.role`` / ``jobs.role_value``)
rather than being fully empty. Every step below checks the live schema
via the inspector first, so this migration is safe to run unmodified
against: a brand-new empty database, a legacy database with the full
table set but missing new columns, or anything in between.

Revision ID: d330f3a84db7
Revises:
Create Date: 2026-09-04 20:10:30.045138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd330f3a84db7'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def add_column_if_missing(table_name: str, column: sa.Column) -> None:
        if table_name not in existing_tables:
            return
        existing_columns = {c["name"] for c in inspector.get_columns(table_name)}
        if column.name not in existing_columns:
            op.add_column(table_name, column)

    if 'jobs' not in existing_tables:
        op.create_table('jobs',
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('role_family', sa.String(), nullable=True),
        sa.Column('client_name', sa.String(), nullable=True),
        sa.Column('share_token', sa.String(), nullable=True),
        sa.Column('lifecycle_status', sa.String(), nullable=False),
        sa.Column('owner_email', sa.String(), nullable=True),
        sa.Column('role_value', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('role_id'),
        sa.UniqueConstraint('share_token')
        )
    else:
        # Present in every deployed shape of this table; only the fee
        # field is new enough that create_all() would have skipped it.
        add_column_if_missing('jobs', sa.Column('role_value', sa.Float(), nullable=True))

    if 'users' not in existing_tables:
        op.create_table('users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('password_salt', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
        )
    else:
        # NOT NULL with no app-level backfill step, so give existing
        # rows a real value via a server_default, then drop the
        # server_default so the column matches the ORM model exactly
        # (the Python-side default in models_orm.py handles new rows).
        if 'role' not in {c["name"] for c in inspector.get_columns('users')}:
            op.add_column('users', sa.Column('role', sa.String(), nullable=False, server_default='recruiter'))
            # batch mode: SQLite has no ALTER COLUMN, so dropping the
            # server_default has to go through a table rebuild there;
            # Postgres runs it as a plain ALTER either way.
            with op.batch_alter_table('users') as batch_op:
                batch_op.alter_column('role', server_default=None)

    if 'activity_log' not in existing_tables:
        op.create_table('activity_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('user_email', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('detail', sa.String(), nullable=False),
        sa.Column('candidate_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    if 'candidates' not in existing_tables:
        op.create_table('candidates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('current_company', sa.String(), nullable=False),
        sa.Column('current_title', sa.String(), nullable=False),
        sa.Column('location', sa.String(), nullable=False),
        sa.Column('source_url', sa.String(), nullable=False),
        sa.Column('first_seen_job_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['first_seen_job_id'], ['jobs.role_id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    if 'communication_log_entries' not in existing_tables:
        op.create_table('communication_log_entries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('candidate_evaluation_id', sa.String(), nullable=False),
        sa.Column('channel', sa.String(), nullable=False),
        sa.Column('direction', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('transcript', sa.String(), nullable=True),
        sa.Column('contact_used', sa.String(), nullable=False),
        sa.Column('logged_by', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    if 'job_recruiters' not in existing_tables:
        op.create_table('job_recruiters',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('assignment', sa.String(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'email', name='uq_job_recruiter')
        )

    if 'job_sections' not in existing_tables:
        op.create_table('job_sections',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('section_key', sa.String(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'section_key', name='uq_job_section')
        )

    if 'sessions' not in existing_tables:
        op.create_table('sessions',
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('token')
        )

    if 'tasks' not in existing_tables:
        op.create_table('tasks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('args', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    if 'candidate_evaluations' not in existing_tables:
        op.create_table('candidate_evaluations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('candidate_evaluation_id', sa.String(), nullable=False),
        sa.Column('canonical_candidate_id', sa.String(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('prioritization', sa.JSON(), nullable=True),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('conversation_summary', sa.String(), nullable=False),
        sa.Column('conversation_summary_updated_at', sa.DateTime(), nullable=True),
        sa.Column('conversation_summary_entry_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['canonical_candidate_id'], ['candidates.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'candidate_evaluation_id', name='uq_role_candidate_eval')
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Full teardown, in FK-safe order. Guarded so downgrade() is also
    # safe to run against a database that never had every table.
    for table_name in (
        'candidate_evaluations',
        'tasks',
        'sessions',
        'job_sections',
        'job_recruiters',
        'communication_log_entries',
        'candidates',
        'activity_log',
        'users',
        'jobs',
    ):
        if table_name in existing_tables:
            op.drop_table(table_name)
