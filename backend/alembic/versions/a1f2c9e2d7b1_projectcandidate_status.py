"""projectcandidate_status

Revision ID: a1f2c9e2d7b1
Revises: 00e9d9b26ba6
Create Date: 2026-02-06

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = 'a1f2c9e2d7b1'
down_revision = '00e9d9b26ba6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add simple pipeline status to project candidates
    op.add_column(
        'projectcandidate',
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='new'),
    )
    op.create_index(op.f('ix_projectcandidate_status'), 'projectcandidate', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_projectcandidate_status'), table_name='projectcandidate')
    op.drop_column('projectcandidate', 'status')
