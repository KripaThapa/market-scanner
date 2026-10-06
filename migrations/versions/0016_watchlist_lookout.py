"""Add structured watchlist rows and lookout display metadata; no historical rewrites."""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('watchlist_symbols', sa.Column('structured_rows', sa.JSON(), nullable=True))
    op.add_column('watchlist_level_monitors', sa.Column('semantic', sa.String(20), nullable=True))
    op.add_column('watchlist_level_monitors', sa.Column('watchlist_details', sa.JSON(), nullable=True))
    op.add_column('alerts', sa.Column('trading_date', sa.String(10), nullable=True))
    op.create_index('ix_alerts_trading_date', 'alerts', ['trading_date'])


def downgrade():
    # Application rollback retains the additive schema and historical evidence.
    # Removing these columns is reserved for disposable migration verification.
    op.drop_index('ix_alerts_trading_date', table_name='alerts')
    op.drop_column('alerts', 'trading_date')
    op.drop_column('watchlist_level_monitors', 'watchlist_details')
    op.drop_column('watchlist_level_monitors', 'semantic')
    op.drop_column('watchlist_symbols', 'structured_rows')
