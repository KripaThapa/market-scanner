"""Private candle replay sessions and human observations.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('strategy_replay_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instrument', sa.String(40), nullable=False),
        sa.Column('asset_type', sa.String(12), nullable=False),
        sa.Column('market_date', sa.String(10), nullable=False),
        sa.Column('timezone', sa.String(60), nullable=False),
        sa.Column('visible_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('visible_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('current_replay_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('strategy_version', sa.String(80)),
        sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('feed', sa.String(40), nullable=False),
        sa.Column('session_configuration', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('blind_mode', sa.Boolean(), nullable=False),
        sa.Column('outcome_revealed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('instrument', 'asset_type', 'market_date', 'current_replay_time'):
        op.create_index(f'ix_strategy_replay_sessions_{column}', 'strategy_replay_sessions', [column])
    op.create_table('strategy_replay_candles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('replay_id', sa.Integer(), sa.ForeignKey('strategy_replay_sessions.id'), nullable=False),
        sa.Column('candle_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open', sa.Float(), nullable=False), sa.Column('high', sa.Float(), nullable=False),
        sa.Column('low', sa.Float(), nullable=False), sa.Column('close', sa.Float(), nullable=False),
        sa.Column('volume', sa.Float(), nullable=False), sa.Column('trade_count', sa.Float()),
        sa.UniqueConstraint('replay_id', 'candle_at', name='uq_replay_source_candle'))
    op.create_index('ix_strategy_replay_candles_replay_id', 'strategy_replay_candles', ['replay_id'])
    op.create_index('ix_strategy_replay_candles_candle_at', 'strategy_replay_candles', ['candle_at'])
    op.create_table('strategy_replay_observations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('replay_id', sa.Integer(), sa.ForeignKey('strategy_replay_sessions.id'), nullable=False),
        sa.Column('instrument', sa.String(40), nullable=False),
        sa.Column('market_date', sa.String(10), nullable=False),
        sa.Column('replay_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decision', sa.String(30), nullable=False),
        sa.Column('free_text_reason', sa.Text(), nullable=False),
        sa.Column('strategy_version', sa.String(80)),
        sa.Column('observed_price', sa.Float()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('replay_id', 'instrument', 'market_date', 'replay_time'):
        op.create_index(f'ix_strategy_replay_observations_{column}', 'strategy_replay_observations', [column])


def downgrade():
    op.drop_table('strategy_replay_observations')
    op.drop_table('strategy_replay_candles')
    op.drop_table('strategy_replay_sessions')
