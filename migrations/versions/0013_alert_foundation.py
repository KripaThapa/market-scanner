"""Immutable FORMING alerts and durable completed-observation transition state.

Revision ID: 0013
Revises: 0012
Legacy alerts remain unchanged, without invented snapshots.
"""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('alerts') as batch:
        batch.add_column(sa.Column('transition_number', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('strategy_version', sa.String(80), nullable=True))
        batch.add_column(sa.Column('decision_candle_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('snapshot', sa.JSON(), nullable=True))
        batch.create_foreign_key('fk_alert_strategy_version', 'strategy_versions', ['strategy_version'], ['id'])
        batch.create_unique_constraint('uq_alert_transition', ['symbol', 'strategy_version', 'transition_number'])
        batch.create_index('ix_alert_symbol_candle', ['symbol', 'decision_candle_at'])
    op.create_table('alert_states',
        sa.Column('symbol', sa.String(20), primary_key=True),
        sa.Column('strategy_version', sa.String(80), sa.ForeignKey('strategy_versions.id'), primary_key=True),
        sa.Column('setup_state', sa.String(30), nullable=False),
        sa.Column('last_candle_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_evaluated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('transition_number', sa.Integer(), nullable=False))
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("""CREATE FUNCTION protect_alert_event() RETURNS trigger AS $$
            BEGIN
                IF OLD.transition_number IS NOT NULL THEN
                    RAISE EXCEPTION 'Alert events are immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql""")
        op.execute('CREATE TRIGGER immutable_alert_event BEFORE UPDATE OR DELETE ON alerts '
                   'FOR EACH ROW EXECUTE FUNCTION protect_alert_event()')
    else:
        for operation in ('UPDATE', 'DELETE'):
            op.execute(f"""CREATE TRIGGER immutable_alert_{operation.lower()} BEFORE {operation} ON alerts
                WHEN OLD.transition_number IS NOT NULL
                BEGIN SELECT RAISE(ABORT, 'Alert events are immutable'); END""")


def downgrade():
    op.drop_table('alert_states')
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER immutable_alert_event ON alerts')
        op.execute('DROP FUNCTION protect_alert_event()')
    else:
        op.execute('DROP TRIGGER immutable_alert_update')
        op.execute('DROP TRIGGER immutable_alert_delete')
    with op.batch_alter_table('alerts') as batch:
        batch.drop_index('ix_alert_symbol_candle')
        batch.drop_constraint('uq_alert_transition', type_='unique')
        batch.drop_constraint('fk_alert_strategy_version', type_='foreignkey')
        for name in ('snapshot', 'decision_candle_at', 'strategy_version', 'transition_number'):
            batch.drop_column(name)
