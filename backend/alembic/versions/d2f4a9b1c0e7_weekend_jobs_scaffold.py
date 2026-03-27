"""weekend jobs scaffold

Revision ID: d2f4a9b1c0e7
Revises: c7d9e2a1f4b0
Create Date: 2026-03-25

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd2f4a9b1c0e7'
down_revision = 'c7d9e2a1f4b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'weekendjob',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('owner_email', sa.String(), nullable=False, server_default=''),
        sa.Column('title', sa.String(), nullable=False, server_default=''),
        sa.Column('notes', sa.String(), nullable=False, server_default=''),
        sa.Column('status', sa.String(), nullable=False, server_default='queued'),
        sa.Column('error', sa.String(), nullable=False, server_default=''),
        sa.Column('upload_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('extracted_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index(op.f('ix_weekendjob_created_at'), 'weekendjob', ['created_at'], unique=False)
    op.create_index(op.f('ix_weekendjob_owner_email'), 'weekendjob', ['owner_email'], unique=False)
    op.create_index(op.f('ix_weekendjob_status'), 'weekendjob', ['status'], unique=False)

    op.create_table(
        'weekendartifact',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('weekendjob.id'), nullable=False),
        sa.Column('kind', sa.String(), nullable=False, server_default='upload'),
        sa.Column('filename', sa.String(), nullable=False, server_default=''),
        sa.Column('rel_path', sa.String(), nullable=False, server_default=''),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sha256', sa.String(), nullable=False, server_default=''),
        sa.Column('content_type', sa.String(), nullable=False, server_default=''),
    )
    op.create_index(op.f('ix_weekendartifact_created_at'), 'weekendartifact', ['created_at'], unique=False)
    op.create_index(op.f('ix_weekendartifact_job_id'), 'weekendartifact', ['job_id'], unique=False)
    op.create_index(op.f('ix_weekendartifact_kind'), 'weekendartifact', ['kind'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_weekendartifact_kind'), table_name='weekendartifact')
    op.drop_index(op.f('ix_weekendartifact_job_id'), table_name='weekendartifact')
    op.drop_index(op.f('ix_weekendartifact_created_at'), table_name='weekendartifact')
    op.drop_table('weekendartifact')

    op.drop_index(op.f('ix_weekendjob_status'), table_name='weekendjob')
    op.drop_index(op.f('ix_weekendjob_owner_email'), table_name='weekendjob')
    op.drop_index(op.f('ix_weekendjob_created_at'), table_name='weekendjob')
    op.drop_table('weekendjob')
