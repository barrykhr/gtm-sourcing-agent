"""add position and client ids

Revision ID: 67be47eb735d
Revises: 8f2a1c9d4e6b
Create Date: 2026-09-22 08:10:00.000000

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67be47eb735d'
down_revision: Union[str, Sequence[str], None] = '8f2a1c9d4e6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'clients',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('position_code', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('client_id', sa.String(), nullable=True))
        batch_op.create_unique_constraint('uq_jobs_position_code', ['position_code'])
        batch_op.create_foreign_key('fk_jobs_client_id_clients', 'clients', ['client_id'], ['id'])

    # Backfill: every existing job needs a position_code (recruiters
    # quote it by hand, so it can't be left blank), and every existing
    # client_name needs a real Client row behind it, mirroring what
    # db_storage.create_job/set_job_client now do for new/edited jobs.
    conn = op.get_bind()
    jobs = conn.execute(sa.text("SELECT role_id, client_name FROM jobs ORDER BY created_at ASC")).fetchall()

    client_ids: dict[str, str] = {}
    next_client_n = 1

    for n, (role_id, client_name) in enumerate(jobs, start=1):
        position_code = f"POS-{n:04d}"
        client_id = None
        if client_name:
            key = client_name.strip().lower()
            if key:
                if key not in client_ids:
                    client_id = f"CLI-{next_client_n:04d}"
                    next_client_n += 1
                    conn.execute(
                        sa.text("INSERT INTO clients (id, name, created_at) VALUES (:id, :name, :now)"),
                        {"id": client_id, "name": client_name.strip(), "now": datetime.now(UTC)},
                    )
                    client_ids[key] = client_id
                client_id = client_ids[key]
        conn.execute(
            sa.text("UPDATE jobs SET position_code = :code, client_id = :client_id WHERE role_id = :role_id"),
            {"code": position_code, "client_id": client_id, "role_id": role_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_constraint('fk_jobs_client_id_clients', type_='foreignkey')
        batch_op.drop_constraint('uq_jobs_position_code', type_='unique')
        batch_op.drop_column('client_id')
        batch_op.drop_column('position_code')

    op.drop_table('clients')
