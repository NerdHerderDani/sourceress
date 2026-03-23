"""company tags

Revision ID: b3f1c2d4a5e6
Revises: a91c3b2d4e10
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b3f1c2d4a5e6'
down_revision = 'a91c3b2d4e10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('company', sa.Column('tags', sa.String(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('company', 'tags')
