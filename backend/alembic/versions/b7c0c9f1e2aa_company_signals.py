"""company + company signals

Revision ID: b7c0c9f1e2aa
Revises: d3b7f93b4d6a
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'b7c0c9f1e2aa'
down_revision = 'd3b7f93b4d6a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'company',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('norm_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('origin', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('industry_tags', sa.JSON(), nullable=False),
        sa.Column('domains', sa.JSON(), nullable=False),
        sa.Column('notes', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('comp_json', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_company_created_at'), 'company', ['created_at'], unique=False)
    op.create_index(op.f('ix_company_updated_at'), 'company', ['updated_at'], unique=False)
    op.create_index(op.f('ix_company_name'), 'company', ['name'], unique=False)
    op.create_index(op.f('ix_company_norm_name'), 'company', ['norm_name'], unique=False)
    op.create_index(op.f('ix_company_origin'), 'company', ['origin'], unique=False)
    op.create_index('ux_company_norm', 'company', ['norm_name'], unique=True)

    op.create_table(
        'companysignal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('signal_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('value_json', sa.JSON(), nullable=False),
        sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['company.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_companysignal_created_at'), 'companysignal', ['created_at'], unique=False)
    op.create_index(op.f('ix_companysignal_company_id'), 'companysignal', ['company_id'], unique=False)
    op.create_index(op.f('ix_companysignal_source'), 'companysignal', ['source'], unique=False)
    op.create_index(op.f('ix_companysignal_signal_type'), 'companysignal', ['signal_type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_companysignal_signal_type'), table_name='companysignal')
    op.drop_index(op.f('ix_companysignal_source'), table_name='companysignal')
    op.drop_index(op.f('ix_companysignal_company_id'), table_name='companysignal')
    op.drop_index(op.f('ix_companysignal_created_at'), table_name='companysignal')
    op.drop_table('companysignal')

    op.drop_index('ux_company_norm', table_name='company')
    op.drop_index(op.f('ix_company_origin'), table_name='company')
    op.drop_index(op.f('ix_company_norm_name'), table_name='company')
    op.drop_index(op.f('ix_company_name'), table_name='company')
    op.drop_index(op.f('ix_company_updated_at'), table_name='company')
    op.drop_index(op.f('ix_company_created_at'), table_name='company')
    op.drop_table('company')
