"""Restartable historical FORMING baseline evidence.

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('baseline_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('start_date', sa.String(10), nullable=False),
        sa.Column('end_date', sa.String(10), nullable=False),
        sa.Column('strategy_version', sa.String(80), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('trading_days_total', sa.Integer(), nullable=False),
        sa.Column('trading_days_completed', sa.Integer(), nullable=False),
        sa.Column('symbol_failures', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('start_date', 'end_date', 'strategy_version',
                            name='uq_baseline_run_period_version'))
    for name in ('start_date', 'end_date', 'strategy_version', 'status'):
        op.create_index(f'ix_baseline_runs_{name}', 'baseline_runs', [name])
    op.create_table('baseline_days',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('baseline_runs.id'), nullable=False),
        sa.Column('market_date', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('symbols_total', sa.Integer(), nullable=False),
        sa.Column('symbols_completed', sa.Integer(), nullable=False),
        sa.Column('symbols_failed', sa.Integer(), nullable=False),
        sa.Column('coverage_limitation', sa.Text()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('run_id', 'market_date', name='uq_baseline_run_day'))
    for name in ('run_id', 'market_date', 'status'):
        op.create_index(f'ix_baseline_days_{name}', 'baseline_days', [name])
    op.create_table('baseline_symbol_days',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('market_date', sa.String(10), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('strategy_version', sa.String(80), nullable=False),
        sa.Column('replay_id', sa.Integer(), sa.ForeignKey('strategy_replay_sessions.id')),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('sector', sa.String(100)), sa.Column('provenance', sa.JSON(), nullable=False),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('market_date', 'symbol', 'strategy_version',
                            name='uq_baseline_symbol_day_version'))
    for name in ('market_date', 'symbol', 'strategy_version', 'status'):
        op.create_index(f'ix_baseline_symbol_days_{name}', 'baseline_symbol_days', [name])
    op.create_table('baseline_evaluations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol_day_id', sa.Integer(), sa.ForeignKey('baseline_symbol_days.id'), nullable=False),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('context_10m', sa.String(20), nullable=False),
        sa.Column('state_3m', sa.String(30), nullable=False),
        sa.Column('price', sa.Float()), sa.Column('ema_5', sa.Float()),
        sa.Column('ema_12', sa.Float()), sa.Column('ema_34', sa.Float()),
        sa.Column('ema_50', sa.Float()), sa.Column('vwap', sa.Float()),
        sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('feed', sa.String(40), nullable=False),
        sa.Column('candle_state', sa.String(12), nullable=False),
        sa.Column('decision_eligible', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('symbol_day_id', 'evaluated_at',
                            name='uq_baseline_symbol_evaluation'))
    op.create_index('ix_baseline_evaluations_symbol_day_id', 'baseline_evaluations', ['symbol_day_id'])
    op.create_index('ix_baseline_evaluations_evaluated_at', 'baseline_evaluations', ['evaluated_at'])
    op.create_index('ix_baseline_evaluations_state_3m', 'baseline_evaluations', ['state_3m'])
    op.create_table('baseline_episodes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol_day_id', sa.Integer(), sa.ForeignKey('baseline_symbol_days.id'), nullable=False),
        sa.Column('setup_state', sa.String(30), nullable=False),
        sa.Column('first_forming_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('observation_price', sa.Float()),
        sa.Column('context_10m', sa.String(20), nullable=False),
        sa.Column('available_future_bars', sa.Integer(), nullable=False),
        sa.Column('return_after_3_bars', sa.Float()),
        sa.Column('return_after_5_bars', sa.Float()),
        sa.Column('return_after_10_bars', sa.Float()),
        sa.Column('maximum_favorable_excursion', sa.Float()),
        sa.Column('maximum_adverse_excursion', sa.Float()),
        sa.Column('evaluated_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('symbol_day_id', 'setup_state', 'first_forming_at',
                            name='uq_baseline_episode_anchor'))
    for name in ('symbol_day_id', 'setup_state', 'first_forming_at'):
        op.create_index(f'ix_baseline_episodes_{name}', 'baseline_episodes', [name])


def downgrade():
    op.drop_table('baseline_episodes')
    op.drop_table('baseline_evaluations')
    op.drop_table('baseline_symbol_days')
    op.drop_table('baseline_days')
    op.drop_table('baseline_runs')
