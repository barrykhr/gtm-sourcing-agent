"""add interview intelligence phase 2 (competencies, evidence, follow-ups)

Revision ID: 8f2a1c9d4e6b
Revises: c207223c325b
Create Date: 2026-09-21 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f2a1c9d4e6b'
down_revision: Union[str, Sequence[str], None] = 'c207223c325b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Purely additive: one new nullable column on an existing table, plus
    three brand-new tables. Safe to run against a production database
    with rows already in it.
    """
    op.add_column('interview_sessions', sa.Column('intelligence_error', sa.String(), nullable=True))

    op.create_table(
        'interview_competencies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('interview_id', sa.String(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('competency', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('rationale', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['interview_id'], ['interview_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_interview_competencies_interview_id', 'interview_competencies', ['interview_id'])

    op.create_table(
        'interview_evidence',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('competency_id', sa.Integer(), nullable=False),
        sa.Column('segment_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['competency_id'], ['interview_competencies.id']),
        sa.ForeignKeyConstraint(['segment_id'], ['transcript_segments.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_interview_evidence_competency_id', 'interview_evidence', ['competency_id'])
    op.create_index('ix_interview_evidence_segment_id', 'interview_evidence', ['segment_id'])

    op.create_table(
        'follow_up_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('interview_id', sa.String(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('question', sa.String(), nullable=False),
        sa.Column('rationale', sa.String(), nullable=False),
        sa.Column('related_competency', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['interview_id'], ['interview_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_follow_up_questions_interview_id', 'follow_up_questions', ['interview_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_follow_up_questions_interview_id', table_name='follow_up_questions')
    op.drop_table('follow_up_questions')
    op.drop_index('ix_interview_evidence_segment_id', table_name='interview_evidence')
    op.drop_index('ix_interview_evidence_competency_id', table_name='interview_evidence')
    op.drop_table('interview_evidence')
    op.drop_index('ix_interview_competencies_interview_id', table_name='interview_competencies')
    op.drop_table('interview_competencies')
    op.drop_column('interview_sessions', 'intelligence_error')
