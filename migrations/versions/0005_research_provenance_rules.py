"""Explicit source timeframe, observation creation, and versioned rule snapshot.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('strategy_versions', sa.Column('rules_snapshot', sa.JSON()))
    op.add_column('research_candles', sa.Column('source_timeframe', sa.String(3),
                                               nullable=False, server_default='1m'))
    op.add_column('research_observations', sa.Column('source_timeframe', sa.String(3),
                                                    nullable=False, server_default='1m'))
    op.add_column('research_observations', sa.Column('created_at', sa.DateTime(timezone=True)))
    op.execute('UPDATE research_observations SET created_at = observed_at')
    with op.batch_alter_table('research_observations') as batch:
        batch.alter_column('created_at', nullable=False)
    op.create_index('ix_research_observations_setup_state', 'research_observations',
                    ['setup_state'])


def downgrade():
    op.drop_index('ix_research_observations_setup_state', table_name='research_observations')
    op.drop_column('research_observations', 'created_at')
    op.drop_column('research_observations', 'source_timeframe')
    op.drop_column('research_candles', 'source_timeframe')
    op.drop_column('strategy_versions', 'rules_snapshot')
