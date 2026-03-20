"""user_secrets_and_run_owner

Revision ID: c3a19f3c0d2a
Revises: 9414d4f645c1
Create Date: 2026-01-30

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = 'c3a19f3c0d2a'
down_revision = '9414d4f645c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: This migration was superseded by 4891fb30795d_auth_user_secrets
    # and kept only to avoid rewriting history. No-op.
    return


def downgrade() -> None:
    return
