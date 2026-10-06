"""Level transitions against migrated test storage; no provider/network calls."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch

from sqlalchemy import event, select, update, delete
from sqlalchemy.exc import SQLAlchemyError

from backend.database.models import Alert, WatchlistUpload, WatchlistSymbol, WatchlistLevelMonitor
from backend.alerts import alert_row, public_alert
from backend.level_alerts import activate_levels, collect_level_alerts, trading_date
from backend.store import Store
from db_support import test_store
from scanner.worker import CONTEXT_SYMBOLS
from scanner.price_observation import PriceObservation, PriceObservingProvider
from ripster_scanner.candle_model import ALPACA_IEX_SOURCE, CandleSeries
from ripster_scanner.watchlist import ExtractedWatchlistRow, validate_watchlist_rows

AT = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)


class LevelAlertTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.minute = 0
        self.note = 'LONG > 100; SHORT < 90. Original reason — retain exactly!'
        self.snapshot = self.upload(self.note)

    def upload(self, note, *, symbol='AAA', date='2026-09-21'):
        with patch('backend.store.now', return_value=AT):
            snapshot = self.store.snapshot((symbol,), source='image')
        with self.store.session() as session:
            row = session.scalar(select(WatchlistSymbol).where(WatchlistSymbol.watchlist_upload_id == snapshot))
            row.original_note = note
            row.level_instructions = None
            session.flush()
            # Domain identity tests supply a date; integration tests verify ingestion.
            activate_levels(session, session.get(WatchlistUpload, snapshot), date=date, at=AT)
        return snapshot

    def observe(self, price, *, symbol='AAA', snapshot=None, at=None, bar=None):
        self.minute += 1
        at = at or AT + timedelta(minutes=self.minute)
        observation = PriceObservation(Decimal(str(price)), bar or at - timedelta(minutes=1), at, ALPACA_IEX_SOURCE)
        with self.store.session() as session:
            collect_level_alerts(session, snapshot or self.snapshot, {symbol: observation}, at)

    def alerts(self):
        with self.store.session() as session:
            return [(row.id, row.alert_type, row.snapshot, public_alert(alert_row(row)))
                    for row in session.scalars(select(Alert).order_by(Alert.id))]

    def test_long_equal_above_repeat_and_recross_one_event(self):
        for price in (99, 100, 101, 102, 99, 103):
            self.observe(price)
        rows = self.alerts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'WATCHLIST_LEVEL_LONG')
        self.assertEqual(rows[0][2]['previous_price'], '100.00000000')

    def test_short_equal_below_repeat_and_recross_one_event(self):
        for price in (95, 90, 89, 88, 95, 89):
            self.observe(price)
        self.assertEqual([row[1] for row in self.alerts()], ['WATCHLIST_LEVEL_SHORT'])

    def test_first_observation_beyond_level_is_only_a_baseline(self):
        self.observe(101)
        self.observe(102)
        self.assertEqual(self.alerts(), [])
        self.observe(100)
        self.observe(101)
        self.assertEqual(len(self.alerts()), 1)

    def test_restart_and_replacement_keep_dedup_and_immutable_original_note(self):
        self.observe(99)
        self.observe(101)
        before = self.alerts()
        self.store = Store(self.store.engine)
        self.snapshot = self.upload('LONG > 100.00; edited reason')
        self.observe(99)
        self.observe(101)
        self.assertEqual(self.alerts(), before)
        self.assertEqual(before[0][2]['original_note'], self.note)
        self.assertEqual(before[0][3]['reason'], self.note)

    def test_two_distinct_same_direction_levels_trigger_independently(self):
        self.snapshot = self.upload('LONG > 100; LONG > 105')
        for price in (99, 101, 106):
            self.observe(price)
        self.assertEqual([row[2]['trigger_level'] for row in self.alerts()], ['100.00000000', '105.00000000'])

    def test_non_actionable_note_retained_without_monitor(self):
        self.snapshot = self.upload('No go under 90; Support 85 Resistance 100')
        self.observe(80)
        self.observe(110)
        self.assertEqual(self.alerts(), [])
        with self.store.session() as session:
            self.assertFalse(list(session.scalars(select(WatchlistLevelMonitor).where(WatchlistLevelMonitor.active.is_(True)))))

    def test_no_future_stale_or_out_of_order_observations(self):
        self.observe(99)
        self.observe(101, at=AT + timedelta(seconds=30), bar=AT)
        self.observe(101, bar=AT - timedelta(days=1))
        self.observe(101, bar=AT + timedelta(days=1))
        self.assertEqual(self.alerts(), [])

    def test_daily_identity_and_expiry(self):
        self.observe(99)
        self.observe(101)
        next_day = AT + timedelta(days=1)
        self.observe(99, at=next_day)
        self.observe(101, at=next_day + timedelta(minutes=1))
        self.assertEqual(len(self.alerts()), 1)
        self.snapshot = self.upload('LONG > 100', date='2026-09-22')
        self.observe(99, at=next_day + timedelta(minutes=2))
        self.observe(101, at=next_day + timedelta(minutes=3))
        self.assertEqual(len(self.alerts()), 2)

    def test_public_allowlist_and_no_forming_identity(self):
        self.observe(99)
        self.observe(101)
        row = self.alerts()[0][3]
        self.assertEqual(set(row), {'id', 'symbol', 'timestamp', 'alert_type', 'price',
                                   'context_10m', 'reason', 'direction', 'trigger_level'})
        with self.store.session() as session:
            alert = session.scalar(select(Alert))
            self.assertIsNone(alert.strategy_version)
            self.assertIsNone(alert.transition_number)

    def test_database_rejects_event_updates_and_deletes(self):
        self.observe(99)
        self.observe(101)
        for statement in (update(Alert).values(reason='changed'), delete(Alert)):
            with self.assertRaises(SQLAlchemyError), self.store.session() as session:
                session.execute(statement)
        self.assertEqual(len(self.alerts()), 1)

    def test_database_unique_key_rejects_duplicate_daily_event(self):
        self.observe(99)
        self.observe(101)
        with self.assertRaises(SQLAlchemyError), self.store.session() as session:
            original = session.scalar(select(Alert))
            session.add(Alert(symbol=original.symbol, alert_type=original.alert_type,
                              level_key=original.level_key, snapshot=original.snapshot,
                              created_at=AT))
        self.assertEqual(len(self.alerts()), 1)

    def test_publication_offset_does_not_change_new_york_identity(self):
        self.observe(99)
        # The supplied timestamp's calendar date is tomorrow, but NY is still today.
        offset = timezone(timedelta(hours=14))
        at = (AT + timedelta(minutes=2)).astimezone(offset)
        self.observe(101, at=at)
        self.assertEqual(self.alerts()[0][2]['trading_date'], '2026-09-21')
        self.assertEqual(self.alerts()[0][2]['day_timezone'], 'America/New_York')

    def test_failed_event_rolls_back_cursor_and_does_not_stop_other_levels(self):
        self.snapshot = self.upload('LONG > 100; LONG > 105')
        self.observe(99)
        def fail(mapper, connection, target):
            if target.snapshot.get('trigger_level') == '100.00000000':
                raise RuntimeError('private database details')
        event.listen(Alert, 'before_insert', fail)
        try:
            with self.assertLogs('backend.level_alerts', level='WARNING') as logs:
                self.observe(106)
        finally:
            event.remove(Alert, 'before_insert', fail)
        self.assertNotIn('private database details', str(logs.output))
        self.assertEqual(len(self.alerts()), 1)
        self.observe(107)
        self.assertEqual(len(self.alerts()), 2)


class ObservationTests(unittest.TestCase):
    def test_capture_uses_existing_raw_close_and_returns_unchanged_series(self):
        import pandas as pd
        from types import SimpleNamespace
        frame = pd.DataFrame({'close': [99, 101]}, index=pd.DatetimeIndex([AT, AT + timedelta(minutes=1)]))
        bars = CandleSeries(frame, ALPACA_IEX_SOURCE)
        from unittest.mock import Mock
        provider = SimpleNamespace(source=ALPACA_IEX_SOURCE, fetch=Mock(return_value=bars))
        wrapper = PriceObservingProvider(provider)
        self.assertIs(wrapper.fetch('AAA', 3), bars)
        self.assertEqual(wrapper.observations['AAA'].price, Decimal('101'))
        provider.fetch.assert_called_once_with('AAA', 3)

    def test_multiple_visual_rows_same_symbol_survive_validation(self):
        rows = tuple(ExtractedWatchlistRow('AAA', note, 99, (0, i, 100, i + 20))
                     for i, note in enumerate(('LONG > 100', 'LONG > 105')))
        imported = validate_watchlist_rows(rows, {'AAA'})
        self.assertEqual(imported.validated, ('AAA',))
        self.assertEqual(imported.rows, rows)


class LevelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)

    def ingest(self, entries, at=AT, *, activate=True, started_at=None):
        rows = tuple(ExtractedWatchlistRow(symbol, note, 99, (0, i * 30, 100, i * 30 + 20))
                     for i, (symbol, note) in enumerate(entries))
        imported = validate_watchlist_rows(rows, {symbol for symbol, _ in entries})
        with patch('backend.store.now', return_value=started_at or at):
            snapshot = self.store.snapshot((), source='image')
        with patch('backend.store.now', return_value=at):
            self.store.update_import(snapshot, imported)
            if activate:
                self.store.activate(snapshot)
        return snapshot

    def cycle(self, prices, at, *, fail_strategy=(), fail_provider=()):
        import pandas as pd
        from unittest.mock import Mock
        from types import SimpleNamespace
        from discovery.config import DiscoverySettings
        from ripster_scanner.config import Config
        from ripster_scanner.scan import ScanResult
        from scanner.worker import ScannerWorker
        def fetch(symbol, lookback_days):
            if symbol in fail_provider:
                raise TimeoutError('private-provider-url')
            frame = pd.DataFrame({'close': [prices.get(symbol, 50)]},
                index=pd.DatetimeIndex([at - timedelta(seconds=30)]))
            return CandleSeries(frame, ALPACA_IEX_SOURCE, symbol=symbol)
        provider = SimpleNamespace(source=ALPACA_IEX_SOURCE, fetch=Mock(side_effect=fetch))
        def scan(config, wrapped):
            symbol = config.symbols[0]
            wrapped.fetch(symbol, config.lookback_days)
            if symbol in fail_strategy:
                raise ValueError('indicator calculation failed')
            # No FORMING, EMA, VWAP, volume, sector or even strategy summaries.
            return [ScanResult(symbol, source=ALPACA_IEX_SOURCE)]
        worker = ScannerWorker(self.store, discovery_settings=DiscoverySettings(False))
        with patch('backend.store.now', return_value=at), patch('scanner.worker.now', return_value=at), \
             patch('scanner.price_observation.datetime') as clock, \
             patch('scanner.worker.StockHistoricalDataClient'), \
             patch('scanner.worker.build_provider', return_value=provider), \
             patch('scanner.worker.load_config', side_effect=lambda *, symbols: Config('fake', 'fake', symbols)), \
             patch('scanner.worker.scan_watchlist', side_effect=scan):
            clock.now.return_value = at
            self.assertEqual(worker.run_once(), 'scanned')
        self.assertEqual(provider.fetch.call_count, len(set(prices) | set(CONTEXT_SYMBOLS)))

    def event_snapshots(self):
        with self.store.session() as session:
            return [row.snapshot for row in session.scalars(select(Alert).where(Alert.level_key.is_not(None)).order_by(Alert.id))]

    def test_all_actionable_uploaded_levels_armed_and_independent_of_strategy(self):
        snapshot = self.ingest([('AAA', 'LONG > 100; SHORT < 90'),
                                ('BBB', 'LONG > 200'), ('CCC', 'No go')])
        with self.store.session() as session:
            monitors = list(session.scalars(select(WatchlistLevelMonitor)))
            self.assertEqual(len(monitors), 3)
            self.assertTrue(all(m.active and m.source_watchlist_id == snapshot for m in monitors))
        self.cycle({'AAA': 99, 'BBB': 199, 'CCC': 1}, AT + timedelta(minutes=1))
        self.cycle({'AAA': 101, 'BBB': 201, 'CCC': 1000}, AT + timedelta(minutes=2), fail_strategy=('AAA',))
        self.cycle({'AAA': 89, 'BBB': 202, 'CCC': 1}, AT + timedelta(minutes=3))
        events = self.event_snapshots()
        self.assertEqual(sorted((e['symbol'], e['direction']) for e in events),
                         [('AAA', 'LONG'), ('AAA', 'SHORT'), ('BBB', 'LONG')])
        self.assertTrue(all(e['trading_date'] == '2026-09-21' for e in events))

    def test_provider_failure_keeps_baseline_and_replacement_preserves_dedup(self):
        self.ingest([('AAA', 'LONG > 100')])
        self.cycle({'AAA': 99}, AT + timedelta(minutes=1))
        self.cycle({'AAA': 101}, AT + timedelta(minutes=2), fail_provider=('AAA',))
        self.assertEqual(self.event_snapshots(), [])
        self.cycle({'AAA': 101}, AT + timedelta(minutes=3))
        before = self.event_snapshots()
        self.ingest([('AAA', 'LONG > 100.00; changed note')], AT + timedelta(minutes=4))
        self.cycle({'AAA': 99}, AT + timedelta(minutes=5))
        self.cycle({'AAA': 101}, AT + timedelta(minutes=6))
        self.assertEqual(self.event_snapshots(), before)

    def test_ingestion_time_not_upload_start_printed_date_or_utc_date(self):
        completed = datetime(2026, 9, 22, 0, 30, tzinfo=timezone.utc)
        snapshot = self.ingest([('AAA', 'Printed 2099-01-01; LONG > 100')], completed)
        with self.store.session() as session:
            upload = session.get(WatchlistUpload, snapshot)
            self.assertEqual(upload.date, '2026-09-22')
            self.assertEqual(upload.trading_date, '2026-09-21')
        self.assertEqual(trading_date(datetime(2026, 1, 15, 4, 30, tzinfo=timezone.utc)), '2026-01-14')
        next_day = datetime(2026, 9, 22, 4, 1, tzinfo=timezone.utc)
        snapshot = self.ingest([('AAA', 'LONG > 100')], next_day,
                               started_at=next_day - timedelta(minutes=2))
        with self.store.session() as session:
            self.assertEqual(session.get(WatchlistUpload, snapshot).trading_date, '2026-09-22')

    def test_utc_midnight_does_not_roll_current_ny_watchlist_or_suppress_levels(self):
        ingested = datetime(2026, 9, 21, 23, 58, tzinfo=timezone.utc)
        snapshot = self.ingest([('AAA', 'LONG > 100')], ingested)
        self.cycle({'AAA': 99}, ingested + timedelta(minutes=1))
        self.cycle({'AAA': 101}, ingested + timedelta(minutes=3))
        self.assertEqual(self.store.active_snapshot()['id'], snapshot)
        self.assertEqual(self.event_snapshots()[0]['trading_date'], '2026-09-21')

    def test_new_york_midnight_expires_levels_and_requires_new_ingestion(self):
        ingested = datetime(2026, 9, 22, 3, 57, tzinfo=timezone.utc)
        old = self.ingest([('AAA', 'LONG > 100')], ingested)
        self.cycle({'AAA': 99}, ingested + timedelta(minutes=1))
        self.cycle({'AAA': 101}, ingested + timedelta(minutes=3))
        self.assertEqual(self.event_snapshots(), [])
        self.assertIn('AAA', {row['symbol'] for row in self.store.read()['universe']})
        self.assertEqual(self.store.active_snapshot()['source'], 'rollover')
        with patch('backend.store.now', return_value=ingested + timedelta(minutes=4)):
            with self.assertRaises(ValueError):
                self.store.activate(old)
        self.ingest([('AAA', 'LONG > 100')], ingested + timedelta(minutes=4))
        self.cycle({'AAA': 99}, ingested + timedelta(minutes=5))
        self.cycle({'AAA': 101}, ingested + timedelta(minutes=6))
        self.assertEqual(self.event_snapshots()[0]['trading_date'], '2026-09-22')

    def test_duplicate_visual_rows_all_levels_persist_and_removal_stops_monitor(self):
        self.ingest([('AAA', 'LONG > 100'), ('AAA', 'LONG > 105')])
        self.cycle({'AAA': 99}, AT + timedelta(minutes=1))
        self.cycle({'AAA': 106}, AT + timedelta(minutes=2))
        self.assertEqual(len(self.event_snapshots()), 2)
        self.ingest([('AAA', 'No go')], AT + timedelta(minutes=3))
        with self.store.session() as session:
            self.assertTrue(all(not m.active for m in session.scalars(select(WatchlistLevelMonitor))))

    def test_unsuccessful_ingestion_does_not_assign_date_or_activate_levels(self):
        active = self.ingest([('AAA', 'LONG > 100')])
        rejected = self.ingest([], activate=False)
        with self.store.session() as session:
            self.assertIsNone(session.get(WatchlistUpload, rejected).trading_date)
        self.assertEqual(self.store.active_snapshot()['id'], active)

    def test_superseded_publication_cannot_advance_level_cursor(self):
        old = self.ingest([('AAA', 'LONG > 100')])
        self.cycle({'AAA': 99}, AT + timedelta(minutes=1))
        self.ingest([('AAA', 'LONG > 100')], AT + timedelta(minutes=2))
        at = AT + timedelta(minutes=3)
        with patch('backend.store.now', return_value=at):
            self.assertFalse(self.store.publish(old, [], price_observations={
                'AAA': PriceObservation(Decimal('101'), at, at, ALPACA_IEX_SOURCE)}))
        self.assertEqual(self.event_snapshots(), [])
        with self.store.session() as session:
            monitor = session.scalar(select(WatchlistLevelMonitor))
            self.assertEqual(monitor.previous_price, Decimal('99'))
        self.cycle({'AAA': 101}, AT + timedelta(minutes=4))
        self.assertEqual(len(self.event_snapshots()), 1)

    def test_concurrent_postgres_publications_create_one_level_event(self):
        if self.store.engine.dialect.name != 'postgresql':
            self.skipTest('Row-lock concurrency requires isolated PostgreSQL')
        from concurrent.futures import ThreadPoolExecutor
        snapshot = self.ingest([('AAA', 'LONG > 100')])
        self.cycle({'AAA': 99}, AT + timedelta(minutes=1))
        at = AT + timedelta(minutes=2)
        observations = {'AAA': PriceObservation(Decimal('101'), at, at, ALPACA_IEX_SOURCE)}
        with patch('backend.store.now', return_value=at), ThreadPoolExecutor(max_workers=2) as executor:
            publications = list(executor.map(lambda _: self.store.publish(
                snapshot, [], price_observations=observations), range(2)))
        self.assertEqual(publications, [True, True])
        self.assertEqual(len(self.event_snapshots()), 1)

    def test_private_activation_and_public_alert_allowlists(self):
        from fastapi.testclient import TestClient
        from backend.api import create_app
        from backend.internal_api import create_internal_app
        snapshot = self.ingest([('AAA', 'LONG > 100; original instruction')], activate=False)
        with self.store.session() as session:
            self.assertEqual(list(session.scalars(select(WatchlistLevelMonitor))), [])
        with patch('backend.store.now', return_value=AT), \
             TestClient(create_internal_app(store=self.store), base_url='http://localhost') as internal:
            response = internal.post('/api/internal/strategy-lab/watchlist/activate', json={'snapshot_id': snapshot})
            self.assertEqual(response.status_code, 200, response.text)
        self.cycle({'AAA': 99}, AT + timedelta(minutes=1))
        self.cycle({'AAA': 101}, AT + timedelta(minutes=2))
        with patch('backend.store.now', return_value=AT), TestClient(create_app(store=self.store), base_url='http://localhost') as client:
            for route in ('/api/dashboard', '/api/alerts'):
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                items = payload['alerts'] if route == '/api/dashboard' else payload['items']
                self.assertEqual(items[0]['trigger_level'], '100.00000000')
                self.assertIsNone(items[0]['game_plan'])  # No invented column split on a legacy row.
                for private in ('source_watchlist_id', 'source_row_id', 'source_bbox',
                                'provider', 'feed', 'level_key', 'previous_price', 'original_note'):
                    self.assertNotIn(f'"{private}"', response.text)
