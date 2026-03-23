"""company sec cik

Revision ID: e4b8a2d9c7aa
Revises: d8a5f2b1c3de
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e4b8a2d9c7aa'
down_revision = 'd8a5f2b1c3de'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('company', sa.Column('sec_cik', sa.String(), nullable=False, server_default=''))
    op.create_index(op.f('ix_company_sec_cik'), 'company', ['sec_cik'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_company_sec_cik'), table_name='company')
    op.drop_column('company', 'sec_cik')
