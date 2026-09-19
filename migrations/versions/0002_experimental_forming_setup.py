"""Persist experimental forming details and last seen time.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('forming_setups', sa.Column('last_seen_at', sa.DateTime(timezone=True)))
    for name in ('price', 'ema_5', 'ema_12', 'ema_34', 'ema_50'):
        op.add_column('forming_setups', sa.Column(name, sa.Float()))
    op.add_column('forming_setups', sa.Column('vwap_position', sa.String(10)))


def downgrade():
    op.drop_column('forming_setups', 'vwap_position')
    for name in ('ema_50', 'ema_34', 'ema_12', 'ema_5', 'price'):
        op.drop_column('forming_setups', name)
    op.drop_column('forming_setups', 'last_seen_at')
