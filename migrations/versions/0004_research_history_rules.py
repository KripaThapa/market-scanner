"""Append-only research evidence, objective outcomes, and rule proposals.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('strategy_versions',
        sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('config_snapshot', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    candle_columns = [sa.Column(name, sa.Float()) for name in
        ('open', 'high', 'low', 'close', 'volume', 'ema_5', 'ema_12', 'ema_34', 'ema_50', 'vwap')]
    op.create_table('research_candles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('timeframe', sa.String(3), nullable=False),
        sa.Column('candle_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('feed', sa.String(40), nullable=False),
        sa.Column('session_policy', sa.String(80), nullable=False),
        sa.Column('source_timezone', sa.String(60), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        *candle_columns,
        sa.UniqueConstraint('symbol', 'timeframe', 'candle_at', 'provider', 'feed',
                            'content_hash', name='uq_research_candle_revision'))
    for name in ('symbol', 'candle_at', 'captured_at'):
        op.create_index(f'ix_research_candles_{name}', 'research_candles', [name])
    observation_columns = [sa.Column(f'ema_{span}_{tf}', sa.Float())
                           for tf in ('3m', '10m') for span in (5, 12, 34, 50)]
    op.create_table('research_observations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('dedupe_key', sa.String(220), nullable=False, unique=True),
        sa.Column('snapshot_id', sa.Integer(), sa.ForeignKey('watchlist_uploads.id'), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('trading_date', sa.String(10), nullable=False),
        sa.Column('strategy_version', sa.String(80), sa.ForeignKey('strategy_versions.id'), nullable=False),
        sa.Column('watchlist_source', sa.String(20), nullable=False),
        sa.Column('watchlist_filename', sa.String(180)),
        sa.Column('sector', sa.String(100)),
        sa.Column('price', sa.Float()),
        sa.Column('context_10m', sa.String(20), nullable=False),
        sa.Column('context_3m', sa.String(20), nullable=False),
        sa.Column('setup_state', sa.String(30), nullable=False),
        sa.Column('detector_reason', sa.Text()),
        sa.Column('three_min_candle_at', sa.DateTime(timezone=True)),
        sa.Column('ten_min_candle_at', sa.DateTime(timezone=True)),
        *observation_columns,
        sa.Column('vwap_3m', sa.Float()), sa.Column('vwap_10m', sa.Float()),
        sa.Column('vwap_position_3m', sa.String(10)),
        sa.Column('vwap_position_10m', sa.String(10)),
        sa.Column('volume_3m', sa.Float()), sa.Column('volume_10m', sa.Float()),
        sa.Column('inside_research_window', sa.Boolean(), nullable=False),
        sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('feed', sa.String(40), nullable=False),
        sa.Column('session_policy', sa.String(80), nullable=False),
        sa.Column('market_timezone', sa.String(60), nullable=False),
        sa.Column('research_timezone', sa.String(60), nullable=False),
        sa.Column('data_status', sa.String(30), nullable=False))
    for name in ('snapshot_id', 'symbol', 'observed_at', 'trading_date', 'strategy_version'):
        op.create_index(f'ix_research_observations_{name}', 'research_observations', [name])
    op.create_table('research_outcomes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('observation_id', sa.Integer(), sa.ForeignKey('research_observations.id'),
                  nullable=False, unique=True),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('available_future_candles', sa.Integer(), nullable=False),
        *[sa.Column(name, sa.Float()) for name in
          ('future_3_candle_return', 'future_5_candle_return', 'future_10_candle_return',
           'maximum_favorable_excursion', 'maximum_adverse_excursion',
           'time_to_mfe_minutes', 'time_to_mae_minutes')])
    op.create_table('rule_proposals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('strategy_version', sa.String(80), sa.ForeignKey('strategy_versions.id'), nullable=False),
        sa.Column('rule_version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=False),
        sa.Column('condition', sa.Text(), nullable=False),
        sa.Column('threshold_config', sa.Text()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('rule_proposals')
    op.drop_table('research_outcomes')
    for name in ('strategy_version', 'trading_date', 'observed_at', 'symbol', 'snapshot_id'):
        op.drop_index(f'ix_research_observations_{name}', table_name='research_observations')
    op.drop_table('research_observations')
    for name in ('captured_at', 'candle_at', 'symbol'):
        op.drop_index(f'ix_research_candles_{name}', table_name='research_candles')
    op.drop_table('research_candles')
    op.drop_table('strategy_versions')
