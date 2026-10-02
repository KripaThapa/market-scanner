"""Daily watchlist level monitors and immutable, deduplicated level events."""

from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def protect(include_levels):
    condition = 'OLD.transition_number IS NOT NULL'
    if include_levels:
        condition += ' OR OLD.level_key IS NOT NULL'
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(f"""CREATE OR REPLACE FUNCTION protect_alert_event() RETURNS trigger AS $$
            BEGIN
                IF {condition} THEN RAISE EXCEPTION 'Alert events are immutable'; END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql""")
    else:
        for operation in ('UPDATE', 'DELETE'):
            op.execute(f'DROP TRIGGER immutable_alert_{operation.lower()}')
            op.execute(f"""CREATE TRIGGER immutable_alert_{operation.lower()} BEFORE {operation} ON alerts
                WHEN {condition}
                BEGIN SELECT RAISE(ABORT, 'Alert events are immutable'); END""")


def upgrade():
    op.add_column('watchlist_uploads', sa.Column('trading_date', sa.String(10), nullable=True))
    op.add_column('watchlist_symbols', sa.Column('level_instructions', sa.JSON(), nullable=True))
    op.add_column('alerts', sa.Column('level_key', sa.String(100), nullable=True))
    op.create_index('uq_alert_level_key', 'alerts', ['level_key'], unique=True)
    op.create_table('watchlist_level_monitors',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('watchlist_date', sa.String(10), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('direction', sa.String(5), nullable=False),
        sa.Column('trigger_level', sa.Numeric(24, 8), nullable=False),
        sa.Column('original_note', sa.Text(), nullable=True),
        sa.Column('source_watchlist_id', sa.Integer(), sa.ForeignKey('watchlist_uploads.id'), nullable=False),
        sa.Column('source_row_id', sa.Integer(), nullable=False),
        sa.Column('source_bbox', sa.JSON(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('previous_price', sa.Numeric(24, 8), nullable=True),
        sa.Column('previous_bar_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('previous_observed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_watchlist_level_monitors_watchlist_date', 'watchlist_level_monitors', ['watchlist_date'])
    op.create_index('ix_watchlist_level_monitors_symbol', 'watchlist_level_monitors', ['symbol'])
    protect(True)


def downgrade():
    # Disposable migration verification only; keep evidence on application rollback.
    protect(False)
    op.drop_table('watchlist_level_monitors')
    op.drop_index('uq_alert_level_key', table_name='alerts')
    op.drop_column('alerts', 'level_key')
    op.drop_column('watchlist_symbols', 'level_instructions')
    op.drop_column('watchlist_uploads', 'trading_date')
