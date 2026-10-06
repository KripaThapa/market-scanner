"""SELECT-only watchlist audit. Run inside the existing application environment.

No schema upgrades, Store initialization, provider calls or alert creation.
Only known display/evidence fields are printed; connection settings stay private.
"""
import json
from sqlalchemy import inspect, text
from backend.database.config import make_engine


def audit(day='2026-10-05', symbols=('CBRS', 'MSFT')):
    engine = make_engine()
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout = '10s'"))
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            result = {'date': day, 'mode': 'READ ONLY', 'schema': {}, 'active': [],
                      'uploads': [], 'symbols': [], 'monitors': [], 'alerts': []}
            def columns(table):
                return {column['name'] for column in inspector.get_columns(table)} if table in tables else set()
            def read(query, params=None):
                return [dict(row) for row in connection.execute(text(query), params or {}).mappings()]
            params = {'day':day, 'a':symbols[0], 'b':symbols[1]}
            if 'alembic_version' in tables:
                result['schema']['version'] = read('SELECT version_num FROM alembic_version')
            if 'app_state' in tables:
                result['active'] = read('SELECT active_watchlist_id FROM app_state WHERE id=1')
            upload_columns = columns('watchlist_uploads')
            result['schema']['structured_dates_available'] = 'trading_date' in upload_columns
            if upload_columns:
                allowed = [name for name in ('id','date','trading_date','processing_status','validated_count',
                    'uploaded_at','processed_at') if name in upload_columns]
                # Legacy UTC bookkeeping is explicitly labeled, never interpreted
                # as proof of the New York trading date.
                predicate = 'trading_date = :day' if 'trading_date' in upload_columns else 'date = :day'
                result['uploads'] = read(f'SELECT {",".join(allowed)} FROM watchlist_uploads WHERE {predicate} ORDER BY id', params)
                ids = [row['id'] for row in result['uploads']]
                symbol_columns = columns('watchlist_symbols')
                if ids and symbol_columns:
                    allowed = [name for name in ('watchlist_upload_id','symbol','validation_status','original_note',
                        'structured_rows','level_instructions') if name in symbol_columns]
                    # IDs are integers read from the database, never user text.
                    id_list = ','.join(str(int(value)) for value in ids)
                    result['symbols'] = read(f'SELECT {",".join(allowed)} FROM watchlist_symbols WHERE '
                        f'watchlist_upload_id IN ({id_list}) AND symbol IN (:a,:b) ORDER BY watchlist_upload_id,symbol', params)
            monitor_columns = columns('watchlist_level_monitors')
            result['schema']['level_monitors_available'] = bool(monitor_columns)
            if monitor_columns:
                allowed = [name for name in ('key','symbol','direction','semantic','trigger_level','active',
                    'activated_at','previous_price','previous_bar_at','previous_observed_at') if name in monitor_columns]
                result['monitors'] = read(f'SELECT {",".join(allowed)} FROM watchlist_level_monitors '
                    'WHERE watchlist_date=:day AND symbol IN (:a,:b) ORDER BY key', params)
            alert_columns = columns('alerts')
            if 'snapshot' in alert_columns:
                result['alerts'] = read("SELECT id,symbol,alert_type,created_at,snapshot->>'trading_date' AS trading_date,"
                    "snapshot->>'trigger_level' AS level,snapshot->>'price' AS price,"
                    "snapshot->>'crossing_timestamp' AS crossing_timestamp FROM alerts "
                    "WHERE symbol IN (:a,:b) AND alert_type LIKE 'WATCHLIST_LEVEL_%' "
                    "AND snapshot->>'trading_date'=:day ORDER BY id", params)
            return result
    finally:
        engine.dispose()


if __name__ == '__main__':
    try:
        print(json.dumps(audit(), default=str, indent=2))
    except Exception as error:
        # Do not print connection exceptions or parameters.
        print(json.dumps({'error': type(error).__name__, 'mode':'READ ONLY'}))
        raise SystemExit(1)
