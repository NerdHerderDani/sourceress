"""company wikidata id

Revision ID: c2e7a1d0f8aa
Revises: b7c0c9f1e2aa
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c2e7a1d0f8aa'
down_revision = 'b7c0c9f1e2aa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('company', sa.Column('wikidata_id', sa.String(), nullable=False, server_default=''))
    op.create_index(op.f('ix_company_wikidata_id'), 'company', ['wikidata_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_company_wikidata_id'), table_name='company')
    op.drop_column('company', 'wikidata_id')
