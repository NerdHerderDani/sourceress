"""company comp bands

Revision ID: d8a5f2b1c3de
Revises: c2e7a1d0f8aa
Create Date: 2026-03-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'd8a5f2b1c3de'
down_revision = 'c2e7a1d0f8aa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'companycompband',
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
    op.create_index(op.f('ix_companycompband_created_at'), 'companycompband', ['created_at'], unique=False)
    op.create_index(op.f('ix_companycompband_company_id'), 'companycompband', ['company_id'], unique=False)
    op.create_index(op.f('ix_companycompband_role'), 'companycompband', ['role'], unique=False)
    op.create_index(op.f('ix_companycompband_level'), 'companycompband', ['level'], unique=False)
    op.create_index(op.f('ix_companycompband_location'), 'companycompband', ['location'], unique=False)
    op.create_index(op.f('ix_companycompband_currency'), 'companycompband', ['currency'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_companycompband_currency'), table_name='companycompband')
    op.drop_index(op.f('ix_companycompband_location'), table_name='companycompband')
    op.drop_index(op.f('ix_companycompband_level'), table_name='companycompband')
    op.drop_index(op.f('ix_companycompband_role'), table_name='companycompband')
    op.drop_index(op.f('ix_companycompband_company_id'), table_name='companycompband')
    op.drop_index(op.f('ix_companycompband_created_at'), table_name='companycompband')
    op.drop_table('companycompband')
