"""Extend the existing reference cache; preserve all historical observations/alerts."""

from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    for name, length in (('company_name', 240), ('cik', 20), ('isin', 20),
                         ('cusip', 20), ('exchange', 80), ('country', 80), ('last_status', 20)):
        op.add_column('symbol_metadata', sa.Column(name, sa.String(length), nullable=True))
    for name in ('last_attempt_at', 'next_refresh_at'):
        op.add_column('symbol_metadata', sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column('active_universe_members', sa.Column('industry', sa.String(120), nullable=True))


def downgrade():
    # For disposable migration tests only; retain the schema on application rollback.
    with op.batch_alter_table('active_universe_members') as batch:
        batch.drop_column('industry')
    with op.batch_alter_table('symbol_metadata') as batch:
        for name in ('company_name', 'cik', 'isin', 'cusip', 'exchange', 'country',
                     'last_status', 'last_attempt_at', 'next_refresh_at'):
            batch.drop_column(name)
