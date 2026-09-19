"""Persist scanner-calculated candles for symbol detail charts.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('scan_results', sa.Column('candles_10m', sa.JSON()))
    op.add_column('scan_results', sa.Column('candles_3m', sa.JSON()))
    op.add_column('forming_setups', sa.Column('first_candle_at', sa.String(40)))


def downgrade():
    op.drop_column('forming_setups', 'first_candle_at')
    op.drop_column('scan_results', 'candles_3m')
    op.drop_column('scan_results', 'candles_10m')
