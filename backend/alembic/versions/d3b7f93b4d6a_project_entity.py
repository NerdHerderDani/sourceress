"""project entity

Revision ID: d3b7f93b4d6a
Revises: 4c1d2a0a9b12
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'd3b7f93b4d6a'
down_revision = '4c1d2a0a9b12'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'projectentity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('external_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('summary_json', sa.JSON(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('note', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_projectentity_created_at'), 'projectentity', ['created_at'], unique=False)
    op.create_index(op.f('ix_projectentity_updated_at'), 'projectentity', ['updated_at'], unique=False)
    op.create_index(op.f('ix_projectentity_project_id'), 'projectentity', ['project_id'], unique=False)
    op.create_index(op.f('ix_projectentity_source'), 'projectentity', ['source'], unique=False)
    op.create_index(op.f('ix_projectentity_external_id'), 'projectentity', ['external_id'], unique=False)
    op.create_index(op.f('ix_projectentity_status'), 'projectentity', ['status'], unique=False)
    op.create_index('ux_projectentity_proj_src_ext', 'projectentity', ['project_id', 'source', 'external_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_projectentity_proj_src_ext', table_name='projectentity')
    op.drop_index(op.f('ix_projectentity_status'), table_name='projectentity')
    op.drop_index(op.f('ix_projectentity_external_id'), table_name='projectentity')
    op.drop_index(op.f('ix_projectentity_source'), table_name='projectentity')
    op.drop_index(op.f('ix_projectentity_project_id'), table_name='projectentity')
    op.drop_index(op.f('ix_projectentity_updated_at'), table_name='projectentity')
    op.drop_index(op.f('ix_projectentity_created_at'), table_name='projectentity')
    op.drop_table('projectentity')
