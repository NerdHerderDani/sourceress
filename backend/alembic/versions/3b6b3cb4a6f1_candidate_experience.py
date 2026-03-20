"""candidate experience

Revision ID: 3b6b3cb4a6f1
Revises: 00e9d9b26ba6
Create Date: 2026-03-20

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = '3b6b3cb4a6f1'
down_revision = '00e9d9b26ba6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'candidateexperience',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('login', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('raw_text', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('company', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('location', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('bullets', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['login'], ['candidate.login']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_candidateexperience_created_at'), 'candidateexperience', ['created_at'], unique=False)
    op.create_index(op.f('ix_candidateexperience_login'), 'candidateexperience', ['login'], unique=False)
    op.create_index(op.f('ix_candidateexperience_source'), 'candidateexperience', ['source'], unique=False)
    op.create_index(op.f('ix_candidateexperience_start_date'), 'candidateexperience', ['start_date'], unique=False)
    op.create_index(op.f('ix_candidateexperience_end_date'), 'candidateexperience', ['end_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_candidateexperience_end_date'), table_name='candidateexperience')
    op.drop_index(op.f('ix_candidateexperience_start_date'), table_name='candidateexperience')
    op.drop_index(op.f('ix_candidateexperience_source'), table_name='candidateexperience')
    op.drop_index(op.f('ix_candidateexperience_login'), table_name='candidateexperience')
    op.drop_index(op.f('ix_candidateexperience_created_at'), table_name='candidateexperience')
    op.drop_table('candidateexperience')
