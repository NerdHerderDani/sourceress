"""comp add bonus/equity

Revision ID: f1a9c0d2b3ef
Revises: e4b8a2d9c7aa
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f1a9c0d2b3ef'
down_revision = 'e4b8a2d9c7aa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('companycompband', sa.Column('bonus', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('companycompband', sa.Column('equity', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('companycompband', 'equity')
    op.drop_column('companycompband', 'bonus')
