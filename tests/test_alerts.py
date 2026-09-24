"""Completed-observation alert transitions; migrated storage, no provider calls."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.api import create_app
from backend.database.models import Alert, AlertState, FormingSetup
from backend.store import Store
from db_support import test_store
from ripster_scanner.config import Config, FormingThresholds
from ripster_scanner.forming import FormingResult, SetupState
from ripster_scanner.scan import ScanResult
from ripster_scanner.strategy import strategy_version_id
from scanner.worker import ScannerWorker
from test_research import result as research_result

VERSION = 'experimental-forming-v1/b067b3150de3'
START = datetime(2026, 9, 18, 13, 42, tzinfo=timezone.utc)


def observed(state='FORMING_LONG', minute=0, *, partial=False, price=100, symbol='AAA'):
    decision = START + timedelta(minutes=minute)
    evaluated = decision + timedelta(minutes=1 if partial else 3)
    base = research_result(symbol, forming=state != 'NONE')
    candle = {**base.candles_3m[-1], 'timestamp': decision.isoformat(), 'close': price}
    ten = {**base.candles_10m[-1], 'timestamp': START.replace(minute=40).isoformat()}
    return replace(base,
        analysis_3m={**base.analysis_3m, 'close': price},
        forming=FormingResult(SetupState(state), 'private exact detector explanation', 0),
        candles_3m=[candle], candles_10m=[ten],
        forming_candle_at=decision.isoformat() if state != 'NONE' else None,
        evaluated_at=evaluated)


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.snapshot = self.store.snapshot(('AAA',))
        self.store.activate(self.snapshot)
        self.client = TestClient(create_app(store=self.store), base_url='http://localhost')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def publish(self, result, *, errors=None):
        at = result.evaluated_at or START + timedelta(hours=1)
        with patch('backend.store.now', return_value=at):
            return self.store.publish(self.snapshot, [result], errors=errors,
                strategy_thresholds=FormingThresholds())

    def alerts(self):
        with self.store.session() as session:
            return [{'id': row.id, 'snapshot': deepcopy(row.snapshot),
                     'state': row.alert_type, 'version': row.strategy_version,
                     'number': row.transition_number}
                    for row in session.scalars(select(Alert).order_by(Alert.id))]

    def test_completed_transitions_reentry_and_repetition_both_directions(self):
        for first, other in [('FORMING_LONG', 'FORMING_SHORT'), ('FORMING_SHORT', 'FORMING_LONG')]:
            with self.subTest(first=first):
                # Distinct symbols keep both directions independent.
                symbol = 'AAA' if first == 'FORMING_LONG' else 'BBB'
                sequence = ['NONE', first, first, 'NONE', first, other, other]
                for index, state in enumerate(sequence):
                    self.publish(observed(state, index * 3, symbol=symbol))
                with self.store.session() as session:
                    actual = session.scalars(select(Alert.alert_type).where(Alert.symbol == symbol).order_by(Alert.id)).all()
                self.assertEqual(actual, [first, first, other])
        self.assertEqual(len(self.alerts()), 6)
        self.assertEqual(len({row['id'] for row in self.alerts()}), 6)

    def test_partial_forming_then_completed_creates_only_one(self):
        self.publish(observed(partial=True))
        self.assertEqual(self.alerts(), [])
        with self.store.session() as session:
            self.assertIsNone(session.get(AlertState, ('AAA', VERSION)))
            self.assertIsNotNone(session.scalar(select(FormingSetup)))
        self.publish(observed())
        self.publish(observed(minute=3))
        self.assertEqual(len(self.alerts()), 1)
        self.assertEqual(self.alerts()[0]['snapshot']['candle_state'], 'COMPLETED')
        self.assertTrue(self.alerts()[0]['snapshot']['decision_eligible'])

    def test_partial_none_and_partial_opposite_do_not_reset_confirmed_state(self):
        self.publish(observed())
        self.publish(observed('NONE', 3, partial=True))
        self.publish(observed('FORMING_SHORT', 6, partial=True))
        self.publish(observed(minute=9))
        self.assertEqual(len(self.alerts()), 1)

    def test_failed_missing_and_restart_do_not_reset(self):
        self.publish(observed())
        self.publish(observed('NONE', 3), errors={'AAA': 'provider failed'})
        self.publish(ScanResult('AAA'))
        self.store.publish(self.snapshot, [])
        self.store = Store(self.store.engine)
        self.publish(observed(minute=6))
        self.assertEqual(len(self.alerts()), 1)
        with self.store.session() as session:
            self.assertEqual(session.get(AlertState, ('AAA', VERSION)).setup_state, 'FORMING_LONG')

    def test_watchlist_replacement_and_removal_do_not_reset(self):
        self.publish(observed())
        other = self.store.snapshot(('BBB',))
        self.store.activate(other)
        self.store.publish(other, [ScanResult('BBB')])
        replacement = self.store.snapshot(('AAA',))
        self.store.activate(replacement)
        self.assertFalse(self.publish(observed('NONE', 3)))  # superseded publication
        self.snapshot = replacement
        self.publish(observed(minute=6))
        self.assertEqual(len(self.alerts()), 1)

    def test_snapshot_preserves_alert_time_values_and_later_state_cannot_mutate(self):
        initial = observed(price=101)
        self.publish(initial)
        before = self.alerts()[0]
        snap = before['snapshot']
        self.assertEqual(snap['price'], 101)
        self.assertEqual(snap['frames']['3m']['ema_5'], initial.candles_3m[-1]['ema_5'])
        self.assertEqual(snap['frames']['3m']['volume'], 1000)
        self.assertEqual(snap['frames']['10m']['context'], 'BULLISH')
        self.assertEqual(snap['provider'], 'Fake')
        self.assertEqual(snap['feed'], 'MEMORY')
        self.assertEqual(snap['source_timeframe'], '1m')
        self.assertEqual(snap['sector'], 'UNKNOWN')
        self.assertEqual(before['version'], VERSION)
        self.publish(observed(minute=3, price=150))
        self.publish(observed('NONE', 6, price=70))
        self.assertEqual(self.alerts(), [before])
        for operation in ('UPDATE alerts SET reason = \'changed\' WHERE id = :id',
                          'DELETE FROM alerts WHERE id = :id'):
            with self.assertRaises(SQLAlchemyError):
                with self.store.engine.begin() as connection:
                    connection.execute(text(operation), {'id': before['id']})
        self.assertEqual(self.alerts(), [before])

    def test_future_missing_and_out_of_order_evidence_does_not_reset_state(self):
        self.publish(observed())
        future = observed('NONE', 9)
        future = replace(future, evaluated_at=START + timedelta(minutes=4))
        self.publish(future)
        missing = replace(observed('NONE', 3), candles_10m=[])
        self.publish(missing)
        self.publish(observed(minute=6))
        self.publish(observed('NONE', 3))
        self.publish(observed(minute=9))
        self.assertEqual(len(self.alerts()), 1)

    def test_exact_repeat_is_idempotent_and_completed_revision_is_a_new_observation(self):
        self.publish(observed())
        self.publish(observed())
        self.assertEqual(len(self.alerts()), 1)
        revised = replace(observed('FORMING_SHORT'), evaluated_at=START + timedelta(minutes=4))
        self.publish(revised)
        self.assertEqual([a['state'] for a in self.alerts()], ['FORMING_LONG', 'FORMING_SHORT'])

    def test_chart_events_survive_episode_closure_and_use_exact_utc_candle(self):
        first = observed()
        second = observed(minute=6)
        self.publish(first)
        self.publish(observed('NONE', 3))
        self.publish(second)
        # Current chart includes earlier candles but its current state is NONE.
        final = observed('NONE', 9)
        final = replace(final, candles_3m=first.candles_3m + second.candles_3m + final.candles_3m)
        self.publish(final)
        detail = self.client.get('/api/symbols/AAA').json()
        chart = self.client.get('/api/symbols/AAA/chart?timeframe=3m').json()
        self.assertEqual(detail['alerts'], chart['alerts'])
        self.assertEqual([a['decision_candle_at'] for a in chart['alerts']],
                         [START.isoformat(), (START + timedelta(minutes=6)).isoformat()])
        self.assertEqual(chart['alerts'][0]['timestamp'], (START + timedelta(minutes=3)).isoformat())
        self.assertEqual(detail['setup_state'], 'NONE')
        self.assertEqual(self.client.get('/api/symbols/AAA/chart?timeframe=10m').json()['alerts'], [])
        self.publish(observed('NONE', 12))
        self.assertEqual(self.client.get('/api/symbols/AAA').json()['alerts'], [])
        self.assertEqual(len(self.alerts()), 2)

    def test_public_dtos_are_allowlists_and_unknown_is_not_a_sector(self):
        self.publish(observed())
        dashboard = self.client.get('/api/dashboard').json()
        alerts = self.client.get('/api/alerts').json()
        self.assertTrue(dashboard['capabilities']['alerts'])
        self.assertTrue(alerts['implemented'])
        self.assertEqual(dashboard['alerts'], alerts['items'])
        self.assertEqual(set(alerts['items'][0]),
            {'id', 'symbol', 'timestamp', 'alert_type', 'price', 'context_10m', 'reason'})
        self.assertEqual(dashboard['counts']['sectors_represented'], 0)
        self.assertEqual(dashboard['counts']['missing_sector_data'], 1)
        for path in ('/api/dashboard', '/api/alerts', '/api/symbols/AAA', '/api/symbols/AAA/chart?timeframe=3m'):
            body = self.client.get(path).text
            for secret in ('private exact', 'MEMORY', 'strategy_version', 'session_policy',
                           'decision_eligible', 'source_timeframe', 'transition_number', 'ema_5', 'provider'):
                self.assertNotIn(secret, body)

    def test_alert_db_failure_isolated_from_publication_and_retried(self):
        def reject_alert(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith('INSERT INTO alerts '):
                raise RuntimeError('private database credentials')
        event.listen(self.store.engine, 'before_cursor_execute', reject_alert)
        try:
            with self.assertLogs('backend.alerts', level='WARNING') as captured:
                self.assertTrue(self.publish(observed()))
            self.assertNotIn('private database', '\n'.join(captured.output))
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', reject_alert)
        self.assertEqual(self.alerts(), [])
        self.assertEqual(self.store.read()['universe'][0]['setup_state'], 'FORMING_LONG')
        with self.store.session() as session:
            self.assertIsNone(session.get(AlertState, ('AAA', VERSION)))
        self.assertTrue(self.publish(observed()))
        self.assertEqual(len(self.alerts()), 1)

    def test_worker_cycles_continue_after_alert_failure(self):
        from discovery.config import DiscoverySettings
        worker = ScannerWorker(self.store, discovery_settings=DiscoverySettings(False))
        result = observed()
        def reject_alert(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith('INSERT INTO alerts '):
                raise RuntimeError('private write failure')
        with patch('scanner.worker.load_config', return_value=Config('fake', 'fake', ('AAA',))), \
             patch('scanner.worker.StockHistoricalDataClient'), \
             patch('scanner.worker.scan_watchlist', return_value=[result]), \
             patch('scanner.worker.now', return_value=result.evaluated_at), \
             patch('backend.store.now', return_value=result.evaluated_at):
            event.listen(self.store.engine, 'before_cursor_execute', reject_alert)
            try:
                self.assertEqual(worker.run_once(), 'scanned')
            finally:
                event.remove(self.store.engine, 'before_cursor_execute', reject_alert)
            self.assertEqual(worker.run_once(), 'scanned')
        self.assertEqual(self.store.state()['status'], 'idle')
        self.assertIsNotNone(self.store.state()['scanner_heartbeat'])
        self.assertEqual(len(self.alerts()), 1)
        self.assertEqual(strategy_version_id(FormingThresholds()), VERSION)

    def test_migration_preserves_legacy_alert_without_invented_snapshot(self):
        config = AlembicConfig(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        with self.store.engine.begin() as connection:
            config.attributes['connection'] = connection
            command.downgrade(config, '0012')
            connection.execute(text("INSERT INTO alerts (id, symbol, alert_type, reason, created_at) "
                "VALUES (700, 'AAA', 'legacy', 'original', :at)"), {'at': START})
            command.upgrade(config, 'head')
            command.upgrade(config, 'head')
        with self.store.session() as session:
            legacy = session.get(Alert, 700)
            self.assertEqual((legacy.symbol, legacy.alert_type, legacy.reason), ('AAA', 'legacy', 'original'))
            self.assertIsNone(legacy.snapshot)
            self.assertIsNone(legacy.strategy_version)
            self.assertIsNone(legacy.decision_candle_at)
            self.assertIsNone(legacy.transition_number)
            self.assertEqual(session.scalars(select(AlertState)).all(), [])

    def test_one_symbols_alert_failure_does_not_block_another(self):
        def reject_one(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith('INSERT INTO alerts ') and 'AAA' in (parameters.values() if isinstance(parameters, dict) else parameters):
                raise RuntimeError('private write failure')
        event.listen(self.store.engine, 'before_cursor_execute', reject_one)
        try:
            with patch('backend.store.now', return_value=START + timedelta(minutes=3)), self.assertLogs('backend.alerts'):
                self.assertTrue(self.store.publish(self.snapshot, [observed(), observed(symbol='BBB')]))
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', reject_one)
        with self.store.session() as session:
            self.assertEqual(session.scalars(select(Alert.symbol)).all(), ['BBB'])
            self.assertIsNone(session.get(AlertState, ('AAA', VERSION)))
            self.assertEqual(session.get(AlertState, ('BBB', VERSION)).setup_state, 'FORMING_LONG')

    def test_future_context_candle_cannot_generate_alert(self):
        result = observed()
        future = {**result.candles_10m[-1], 'timestamp': (START + timedelta(hours=1)).isoformat()}
        self.publish(replace(result, candles_10m=[future]))
        self.assertEqual(self.alerts(), [])
        self.publish(result)
        self.assertEqual(len(self.alerts()), 1)

    def test_known_sector_mapping_is_used_without_counting_unknown(self):
        results = [observed(), observed(symbol='BBB'), observed(symbol='CCC')]
        with patch('backend.store.now', return_value=START + timedelta(minutes=3)):
            self.store.publish(self.snapshot, results, {'AAA': 'Technology', 'BBB': 'Technology'})
        counts = self.client.get('/api/dashboard').json()['counts']
        self.assertEqual(counts['sectors_represented'], 1)
        self.assertEqual(counts['missing_sector_data'], 1)
        self.assertEqual(self.alerts()[0]['snapshot']['sector'], 'Technology')

    def test_real_database_insert_error_rolls_back_only_alert_savepoint(self):
        postgres = self.store.engine.dialect.name == 'postgresql'
        with self.store.engine.begin() as connection:
            if postgres:
                connection.execute(text("""CREATE FUNCTION reject_test_alert() RETURNS trigger AS $$
                    BEGIN RAISE EXCEPTION 'test alert insert rejected'; END;
                    $$ LANGUAGE plpgsql"""))
                connection.execute(text('CREATE TRIGGER reject_test_alert BEFORE INSERT ON alerts '
                                        'FOR EACH ROW EXECUTE FUNCTION reject_test_alert()'))
            else:
                connection.execute(text("""CREATE TRIGGER reject_test_alert BEFORE INSERT ON alerts
                    BEGIN SELECT RAISE(ABORT, 'test alert insert rejected'); END"""))
        try:
            with self.assertLogs('backend.alerts'):
                self.assertTrue(self.publish(observed()))
            self.assertEqual(self.alerts(), [])
            self.assertEqual(self.store.read()['universe'][0]['setup_state'], 'FORMING_LONG')
        finally:
            with self.store.engine.begin() as connection:
                connection.execute(text('DROP TRIGGER reject_test_alert' + (' ON alerts' if postgres else '')))
                if postgres:
                    connection.execute(text('DROP FUNCTION reject_test_alert()'))
        self.publish(observed())
        self.assertEqual(len(self.alerts()), 1)

    def test_concurrent_postgres_publications_do_not_duplicate_alerts(self):
        if self.store.engine.dialect.name != 'postgresql':
            self.skipTest('Row-lock concurrency requires isolated PostgreSQL')
        from concurrent.futures import ThreadPoolExecutor
        result = observed()
        with patch('backend.store.now', return_value=result.evaluated_at), ThreadPoolExecutor(max_workers=2) as executor:
            publications = list(executor.map(lambda _: self.store.publish(self.snapshot, [result]), range(2)))
        self.assertEqual(publications, [True, True])
        self.assertEqual(len(self.alerts()), 1)
