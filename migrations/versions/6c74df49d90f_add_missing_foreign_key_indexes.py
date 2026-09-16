"""add missing foreign key indexes

Revision ID: 6c74df49d90f
Revises: 1a9c8b70ec0b
Create Date: 2026-09-16 04:39:55.073500

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c74df49d90f'
down_revision: Union[str, Sequence[str], None] = '1a9c8b70ec0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Purely additive: adds indexes on foreign-key columns that had none
    (verified against a clean Postgres load of the current baseline —
    every other FK column is already covered as the leading column of
    an existing unique constraint's index; these are not). CREATE INDEX
    never reads or modifies row data, so this is safe to run against a
    table that already has rows, at any size, with no downtime beyond
    the index build itself.
    """
    op.create_index("ix_tasks_role_id", "tasks", ["role_id"])
    op.create_index("ix_activity_log_role_id", "activity_log", ["role_id"])
    op.create_index(
        "ix_communication_log_entries_role_id_candidate_evaluation_id",
        "communication_log_entries", ["role_id", "candidate_evaluation_id"],
    )
    op.create_index(
        "ix_candidate_evaluations_canonical_candidate_id",
        "candidate_evaluations", ["canonical_candidate_id"],
    )
    op.create_index("ix_candidates_first_seen_job_id", "candidates", ["first_seen_job_id"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_candidates_first_seen_job_id", table_name="candidates")
    op.drop_index("ix_candidate_evaluations_canonical_candidate_id", table_name="candidate_evaluations")
    op.drop_index(
        "ix_communication_log_entries_role_id_candidate_evaluation_id",
        table_name="communication_log_entries",
    )
    op.drop_index("ix_activity_log_role_id", table_name="activity_log")
    op.drop_index("ix_tasks_role_id", table_name="tasks")
