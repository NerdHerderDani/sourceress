"""add_feedback

Revision ID: 121a5f73bae6
Revises: 97754c6a030f
Create Date: 2026-01-28 09:50:40.477606

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '121a5f73bae6'
down_revision = '97754c6a030f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table('candidatefeedback'):
        return

    op.create_table(
        'candidatefeedback',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('searchrun.id'), nullable=False),
        sa.Column('login', sa.String(), sa.ForeignKey('candidate.login'), nullable=False),
        sa.Column('label', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(), nullable=False, server_default=''),
    )
    op.create_index('ix_candidatefeedback_created_at', 'candidatefeedback', ['created_at'])
    op.create_index('ix_candidatefeedback_run_id', 'candidatefeedback', ['run_id'])
    op.create_index('ix_candidatefeedback_login', 'candidatefeedback', ['login'])
    op.create_index('ix_candidatefeedback_label', 'candidatefeedback', ['label'])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table('candidatefeedback'):
        return

    # indexes might not exist depending on how table was created
    for ix in [
        'ix_candidatefeedback_label',
        'ix_candidatefeedback_login',
        'ix_candidatefeedback_run_id',
        'ix_candidatefeedback_created_at',
    ]:
        try:
            op.drop_index(ix, table_name='candidatefeedback')
        except Exception:
            pass

    op.drop_table('candidatefeedback')
