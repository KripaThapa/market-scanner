"""Discovery, sector history, and execution-candle metadata.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('discovery_memberships',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('trading_date', sa.String(10), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('source_type', sa.String(30), nullable=False),
        sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('rank', sa.Integer()), sa.Column('metrics', sa.JSON(), nullable=False),
        sa.UniqueConstraint('trading_date', 'symbol', 'source_type', name='uq_discovery_membership'))
    for column in ('trading_date', 'symbol', 'source_type'):
        op.create_index(f'ix_discovery_memberships_{column}', 'discovery_memberships', [column])
    op.create_table('discovery_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('trading_date', sa.String(10), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('source_type', sa.String(30), nullable=False),
        sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('rank', sa.Integer()), sa.Column('metrics', sa.JSON(), nullable=False))
    for column in ('trading_date', 'symbol', 'source_type', 'discovered_at'):
        op.create_index(f'ix_discovery_events_{column}', 'discovery_events', [column])
    op.create_table('discovery_source_status',
        sa.Column('source_type', sa.String(30), primary_key=True),
        sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True)),
        sa.Column('last_success_at', sa.DateTime(timezone=True)),
        sa.Column('error', sa.String(200)))
    op.create_table('symbol_metadata',
        sa.Column('symbol', sa.String(20), primary_key=True),
        sa.Column('sector', sa.String(100), nullable=False),
        sa.Column('industry', sa.String(120)),
        sa.Column('metadata_source', sa.String(80), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_symbol_metadata_sector', 'symbol_metadata', ['sector'])
    op.create_table('active_universe_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('snapshot_id', sa.Integer(), sa.ForeignKey('watchlist_uploads.id'), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('sources', sa.JSON(), nullable=False),
        sa.Column('source_metrics', sa.JSON(), nullable=False),
        sa.Column('sector', sa.String(100), nullable=False),
        sa.Column('candle_state', sa.String(12)),
        sa.Column('decision_eligible', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('snapshot_id', 'symbol', name='uq_universe_symbol'))
    for column in ('snapshot_id', 'symbol'):
        op.create_index(f'ix_active_universe_members_{column}', 'active_universe_members', [column])
    op.create_table('sector_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('snapshot_id', sa.Integer(), sa.ForeignKey('watchlist_uploads.id'), nullable=False),
        sa.Column('sector', sa.String(100), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('trading_date', sa.String(10), nullable=False),
        sa.Column('symbols', sa.JSON(), nullable=False),
        sa.Column('symbol_count', sa.Integer(), nullable=False),
        sa.Column('bullish_count', sa.Integer(), nullable=False),
        sa.Column('bearish_count', sa.Integer(), nullable=False),
        sa.Column('mixed_count', sa.Integer(), nullable=False),
        sa.Column('forming_long_count', sa.Integer(), nullable=False),
        sa.Column('forming_short_count', sa.Integer(), nullable=False))
    for column in ('snapshot_id', 'sector', 'observed_at', 'trading_date'):
        op.create_index(f'ix_sector_snapshots_{column}', 'sector_snapshots', [column])
    op.add_column('research_observations', sa.Column('discovery_sources', sa.JSON()))
    op.add_column('research_observations', sa.Column('candle_state', sa.String(12)))
    op.add_column('research_observations', sa.Column('decision_eligible', sa.Boolean()))
    with op.batch_alter_table('research_observations') as batch:
        batch.add_column(sa.Column('sector_snapshot_id', sa.Integer(),
                                   sa.ForeignKey('sector_snapshots.id',
                                                 name='fk_observation_sector_snapshot')))
    op.create_table('research_observation_sources',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('observation_id', sa.Integer(), sa.ForeignKey('research_observations.id'), nullable=False),
        sa.Column('source_type', sa.String(30), nullable=False),
        sa.UniqueConstraint('observation_id', 'source_type', name='uq_observation_source'))
    op.create_index('ix_research_observation_sources_observation_id',
                    'research_observation_sources', ['observation_id'])
    op.create_index('ix_research_observation_sources_source_type',
                    'research_observation_sources', ['source_type'])
    op.create_index('ix_research_observations_candle_state', 'research_observations', ['candle_state'])
    op.create_index('ix_research_observations_sector', 'research_observations', ['sector'])
    op.create_index('ix_research_observations_decision_eligible', 'research_observations',
                    ['decision_eligible'])


def downgrade():
    op.drop_index('ix_research_observations_sector', table_name='research_observations')
    op.drop_index('ix_research_observation_sources_source_type', table_name='research_observation_sources')
    op.drop_index('ix_research_observation_sources_observation_id', table_name='research_observation_sources')
    op.drop_table('research_observation_sources')
    op.drop_index('ix_research_observations_decision_eligible', table_name='research_observations')
    op.drop_index('ix_research_observations_candle_state', table_name='research_observations')
    for column in ('sector_snapshot_id', 'decision_eligible', 'candle_state', 'discovery_sources'):
        op.drop_column('research_observations', column)
    for column in ('trading_date', 'observed_at', 'sector', 'snapshot_id'):
        op.drop_index(f'ix_sector_snapshots_{column}', table_name='sector_snapshots')
    op.drop_table('sector_snapshots')
    for column in ('symbol', 'snapshot_id'):
        op.drop_index(f'ix_active_universe_members_{column}', table_name='active_universe_members')
    op.drop_table('active_universe_members')
    op.drop_index('ix_symbol_metadata_sector', table_name='symbol_metadata')
    op.drop_table('symbol_metadata')
    op.drop_table('discovery_source_status')
    for column in ('discovered_at', 'source_type', 'symbol', 'trading_date'):
        op.drop_index(f'ix_discovery_events_{column}', table_name='discovery_events')
    op.drop_table('discovery_events')
    for column in ('source_type', 'symbol', 'trading_date'):
        op.drop_index(f'ix_discovery_memberships_{column}', table_name='discovery_memberships')
    op.drop_table('discovery_memberships')
