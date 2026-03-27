"""usage events

Revision ID: c9b8d7e6a5f4
Revises: f3a1b2c3d4e5
Create Date: 2026-03-25

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c9b8d7e6a5f4'
down_revision = 'f3a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'usageevent',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('owner_email', sa.String(), nullable=False, server_default=''),
        sa.Column('kind', sa.String(), nullable=False, server_default=''),
        sa.Column('mode', sa.String(), nullable=False, server_default=''),
        sa.Column('preset', sa.String(), nullable=False, server_default=''),
        sa.Column('model_used', sa.String(), nullable=False, server_default=''),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('est_cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('ok', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('error', sa.String(), nullable=False, server_default=''),
    )
    op.create_index('ix_usageevent_created_at', 'usageevent', ['created_at'])
    op.create_index('ix_usageevent_owner_email', 'usageevent', ['owner_email'])
    op.create_index('ix_usageevent_kind', 'usageevent', ['kind'])
    op.create_index('ix_usageevent_mode', 'usageevent', ['mode'])
    op.create_index('ix_usageevent_preset', 'usageevent', ['preset'])
    op.create_index('ix_usageevent_model_used', 'usageevent', ['model_used'])


def downgrade() -> None:
    op.drop_index('ix_usageevent_model_used', table_name='usageevent')
    op.drop_index('ix_usageevent_preset', table_name='usageevent')
    op.drop_index('ix_usageevent_mode', table_name='usageevent')
    op.drop_index('ix_usageevent_kind', table_name='usageevent')
    op.drop_index('ix_usageevent_owner_email', table_name='usageevent')
    op.drop_index('ix_usageevent_created_at', table_name='usageevent')
    op.drop_table('usageevent')
