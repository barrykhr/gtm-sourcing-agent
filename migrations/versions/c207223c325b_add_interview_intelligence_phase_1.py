"""add interview intelligence phase 1 (notetaker)

Revision ID: c207223c325b
Revises: 6c74df49d90f
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c207223c325b'
down_revision: Union[str, Sequence[str], None] = '6c74df49d90f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Purely additive: two brand-new tables, nothing existing touched.
    Safe to run against a production database with rows already in it.
    """
    op.create_table(
        'interview_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('candidate_evaluation_id', sa.String(), nullable=False),
        sa.Column('recruiter_email', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('recording_file_key', sa.String(), nullable=True),
        sa.Column('recording_filename', sa.String(), nullable=True),
        sa.Column('recording_content_type', sa.String(), nullable=True),
        sa.Column('transcript_status', sa.String(), nullable=False),
        sa.Column('intelligence_status', sa.String(), nullable=False),
        sa.Column('summary', sa.JSON(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['jobs.role_id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_interview_sessions_role_id', 'interview_sessions', ['role_id'])
    op.create_index(
        'ix_interview_sessions_role_id_candidate_evaluation_id',
        'interview_sessions', ['role_id', 'candidate_evaluation_id'],
    )

    op.create_table(
        'transcript_segments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('interview_id', sa.String(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('speaker', sa.String(), nullable=False),
        sa.Column('text', sa.String(), nullable=False),
        sa.Column('start_time', sa.Float(), nullable=False),
        sa.Column('end_time', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['interview_id'], ['interview_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_transcript_segments_interview_id', 'transcript_segments', ['interview_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_transcript_segments_interview_id', table_name='transcript_segments')
    op.drop_table('transcript_segments')
    op.drop_index('ix_interview_sessions_role_id_candidate_evaluation_id', table_name='interview_sessions')
    op.drop_index('ix_interview_sessions_role_id', table_name='interview_sessions')
    op.drop_table('interview_sessions')
