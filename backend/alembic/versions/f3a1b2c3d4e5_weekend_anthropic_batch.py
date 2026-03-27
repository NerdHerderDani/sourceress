"""weekend jobs anthropic batch

Revision ID: f3a1b2c3d4e5
Revises: d2f4a9b1c0e7
Create Date: 2026-03-25

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f3a1b2c3d4e5'
down_revision = 'd2f4a9b1c0e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('weekendjob', sa.Column('anthropic_batch_id', sa.String(), nullable=False, server_default=''))
    op.add_column('weekendjob', sa.Column('anthropic_batch_status', sa.String(), nullable=False, server_default=''))
    op.add_column('weekendjob', sa.Column('anthropic_model', sa.String(), nullable=False, server_default=''))
    op.add_column('weekendjob', sa.Column('anthropic_submitted_at', sa.DateTime(), nullable=True))
    op.add_column('weekendjob', sa.Column('anthropic_completed_at', sa.DateTime(), nullable=True))
    op.add_column('weekendjob', sa.Column('result_count', sa.Integer(), nullable=False, server_default='0'))

    op.create_index(op.f('ix_weekendjob_anthropic_batch_id'), 'weekendjob', ['anthropic_batch_id'], unique=False)
    op.create_index(op.f('ix_weekendjob_anthropic_batch_status'), 'weekendjob', ['anthropic_batch_status'], unique=False)
    op.create_index(op.f('ix_weekendjob_anthropic_submitted_at'), 'weekendjob', ['anthropic_submitted_at'], unique=False)
    op.create_index(op.f('ix_weekendjob_anthropic_completed_at'), 'weekendjob', ['anthropic_completed_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_weekendjob_anthropic_completed_at'), table_name='weekendjob')
    op.drop_index(op.f('ix_weekendjob_anthropic_submitted_at'), table_name='weekendjob')
    op.drop_index(op.f('ix_weekendjob_anthropic_batch_status'), table_name='weekendjob')
    op.drop_index(op.f('ix_weekendjob_anthropic_batch_id'), table_name='weekendjob')

    op.drop_column('weekendjob', 'result_count')
    op.drop_column('weekendjob', 'anthropic_completed_at')
    op.drop_column('weekendjob', 'anthropic_submitted_at')
    op.drop_column('weekendjob', 'anthropic_model')
    op.drop_column('weekendjob', 'anthropic_batch_status')
    op.drop_column('weekendjob', 'anthropic_batch_id')
