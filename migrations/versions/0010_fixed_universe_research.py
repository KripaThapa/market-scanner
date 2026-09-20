"""Persist isolated fixed-universe research experiments.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('baseline_runs') as batch:
        batch.drop_constraint('uq_baseline_run_period_version', type_='unique')
        batch.add_column(sa.Column('run_type', sa.String(40), nullable=False,
                                   server_default='LIVE_RECORDED_UNIVERSE'))
        batch.add_column(sa.Column('universe_key', sa.String(64), nullable=False,
                                   server_default='LIVE'))
        batch.add_column(sa.Column('universe_symbols', sa.JSON(), nullable=False,
                                   server_default='[]'))
        batch.add_column(sa.Column('research_metadata', sa.JSON(), nullable=False,
                                   server_default='{}'))
        batch.create_unique_constraint('uq_baseline_run_experiment',
            ['start_date', 'end_date', 'strategy_version', 'run_type', 'universe_key'])
        batch.create_index('ix_baseline_runs_run_type', ['run_type'])

    with op.batch_alter_table('baseline_symbol_days') as batch:
        batch.drop_constraint('uq_baseline_symbol_day_version', type_='unique')
        batch.add_column(sa.Column('baseline_run_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_baseline_symbol_days_baseline_run',
                                 'baseline_runs', ['baseline_run_id'], ['id'])
        batch.create_index('ix_baseline_symbol_days_baseline_run_id', ['baseline_run_id'])
        batch.create_unique_constraint('uq_baseline_run_symbol_day_version',
            ['baseline_run_id', 'market_date', 'symbol', 'strategy_version'])


def downgrade():
    with op.batch_alter_table('baseline_symbol_days') as batch:
        batch.drop_constraint('uq_baseline_run_symbol_day_version', type_='unique')
        batch.drop_index('ix_baseline_symbol_days_baseline_run_id')
        batch.drop_constraint('fk_baseline_symbol_days_baseline_run', type_='foreignkey')
        batch.drop_column('baseline_run_id')
        batch.create_unique_constraint('uq_baseline_symbol_day_version',
            ['market_date', 'symbol', 'strategy_version'])

    with op.batch_alter_table('baseline_runs') as batch:
        batch.drop_index('ix_baseline_runs_run_type')
        batch.drop_constraint('uq_baseline_run_experiment', type_='unique')
        batch.drop_column('research_metadata')
        batch.drop_column('universe_symbols')
        batch.drop_column('universe_key')
        batch.drop_column('run_type')
        batch.create_unique_constraint('uq_baseline_run_period_version',
            ['start_date', 'end_date', 'strategy_version'])
