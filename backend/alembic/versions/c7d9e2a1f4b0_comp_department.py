"""comp add department

Revision ID: c7d9e2a1f4b0
Revises: b3f1c2d4a5e6
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c7d9e2a1f4b0'
down_revision = 'b3f1c2d4a5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('companycompband', sa.Column('dept', sa.String(), nullable=False, server_default='engineering'))
    op.create_index(op.f('ix_companycompband_dept'), 'companycompband', ['dept'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_companycompband_dept'), table_name='companycompband')
    op.drop_column('companycompband', 'dept')
