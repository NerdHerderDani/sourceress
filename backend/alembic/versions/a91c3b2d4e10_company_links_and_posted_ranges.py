"""company links + posted ranges

Revision ID: a91c3b2d4e10
Revises: f1a9c0d2b3ef
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'a91c3b2d4e10'
down_revision = 'f1a9c0d2b3ef'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('company', sa.Column('github_org_url', sa.String(), nullable=False, server_default=''))
    op.add_column('company', sa.Column('linkedin_company_url', sa.String(), nullable=False, server_default=''))
    op.add_column('company', sa.Column('jobs_url', sa.String(), nullable=False, server_default=''))

    op.create_table(
        'companypostedrange',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('level', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('location', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('currency', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('low', sa.Integer(), nullable=False),
        sa.Column('mid', sa.Integer(), nullable=False),
        sa.Column('high', sa.Integer(), nullable=False),
        sa.Column('source_url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('notes', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['company.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_companypostedrange_created_at'), 'companypostedrange', ['created_at'], unique=False)
    op.create_index(op.f('ix_companypostedrange_company_id'), 'companypostedrange', ['company_id'], unique=False)
    op.create_index(op.f('ix_companypostedrange_role'), 'companypostedrange', ['role'], unique=False)
    op.create_index(op.f('ix_companypostedrange_level'), 'companypostedrange', ['level'], unique=False)
    op.create_index(op.f('ix_companypostedrange_location'), 'companypostedrange', ['location'], unique=False)
    op.create_index(op.f('ix_companypostedrange_currency'), 'companypostedrange', ['currency'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_companypostedrange_currency'), table_name='companypostedrange')
    op.drop_index(op.f('ix_companypostedrange_location'), table_name='companypostedrange')
    op.drop_index(op.f('ix_companypostedrange_level'), table_name='companypostedrange')
    op.drop_index(op.f('ix_companypostedrange_role'), table_name='companypostedrange')
    op.drop_index(op.f('ix_companypostedrange_company_id'), table_name='companypostedrange')
    op.drop_index(op.f('ix_companypostedrange_created_at'), table_name='companypostedrange')
    op.drop_table('companypostedrange')

    op.drop_column('company', 'jobs_url')
    op.drop_column('company', 'linkedin_company_url')
    op.drop_column('company', 'github_org_url')
