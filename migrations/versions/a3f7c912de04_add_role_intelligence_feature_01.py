"""add role intelligence tables (Feature 01)

Revision ID: a3f7c912de04
Revises: e0b36789ac59
Create Date: 2026-10-07 00:00:00.000000

"""
from datetime import datetime, UTC
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f7c912de04'
down_revision: Union[str, Sequence[str], None] = 'e0b36789ac59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ORGANIZATION_ID = "default"


def upgrade() -> None:
    """Upgrade schema. Purely additive — no existing table is altered."""
    op.create_table(
        'organizations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'role_requirements',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.Column('priority', sa.String(), nullable=False),
        sa.Column('evidence_level', sa.String(), nullable=False),
        sa.Column('source_span', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_role_requirements_role_id', 'role_requirements', ['role_id'])

    op.create_table(
        'role_icps',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=True),
        sa.Column('fields', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', name='uq_role_icp'),
    )

    op.create_table(
        'role_ambiguities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('candidate_resolutions', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('resolution_note', sa.String(), nullable=False),
        sa.Column('resolved_requirement_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['resolved_requirement_id'], ['role_requirements.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_role_ambiguities_role_id', 'role_ambiguities', ['role_id'])

    op.create_table(
        'role_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=True),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('before', sa.JSON(), nullable=True),
        sa.Column('after', sa.JSON(), nullable=True),
        sa.Column('changed_by', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_role_versions_role_id', 'role_versions', ['role_id'])

    op.create_table(
        'agent_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=True),
        sa.Column('user_email', sa.String(), nullable=False),
        sa.Column('role_id', sa.String(), nullable=True),
        sa.Column('agent_name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_runs_role_id', 'agent_runs', ['role_id'])

    op.create_table(
        'agent_actions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_run_id', sa.String(), nullable=False),
        sa.Column('tool_name', sa.String(), nullable=False),
        sa.Column('input_summary', sa.String(), nullable=False),
        sa.Column('output_summary', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_actions_agent_run_id', 'agent_actions', ['agent_run_id'])

    # Seed the single organization row every Feature 01 record attaches to
    # today (see Organization's docstring in models_orm.py) — not real
    # multi-tenancy, just a placeholder so the columns above aren't dead.
    org_table = sa.table(
        'organizations', sa.column('id', sa.String()), sa.column('name', sa.String()), sa.column('created_at', sa.DateTime())
    )
    op.bulk_insert(org_table, [{'id': DEFAULT_ORGANIZATION_ID, 'name': 'Default', 'created_at': datetime.now(UTC)}])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_agent_actions_agent_run_id', table_name='agent_actions')
    op.drop_table('agent_actions')
    op.drop_index('ix_agent_runs_role_id', table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_index('ix_role_versions_role_id', table_name='role_versions')
    op.drop_table('role_versions')
    op.drop_index('ix_role_ambiguities_role_id', table_name='role_ambiguities')
    op.drop_table('role_ambiguities')
    op.drop_table('role_icps')
    op.drop_index('ix_role_requirements_role_id', table_name='role_requirements')
    op.drop_table('role_requirements')
    op.drop_table('organizations')
