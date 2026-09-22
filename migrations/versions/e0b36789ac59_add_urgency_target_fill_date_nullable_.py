"""add urgency/target_fill_date, make tasks.role_id nullable

Revision ID: e0b36789ac59
Revises: 67be47eb735d
Create Date: 2026-09-22 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0b36789ac59'
down_revision: Union[str, Sequence[str], None] = '67be47eb735d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('urgency', sa.String(), nullable=False, server_default='normal'))
        batch_op.add_column(sa.Column('target_fill_date', sa.String(), nullable=True))

    # tasks.role_id is now nullable — workload_planning tasks (TAT/
    # prioritization batch) span a recruiter's whole roster rather than
    # one job. Existing rows are all job-scoped already, so no data
    # migration is needed here, just relaxing the constraint.
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.alter_column('role_id', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.alter_column('role_id', existing_type=sa.String(), nullable=False)

    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('target_fill_date')
        batch_op.drop_column('urgency')
