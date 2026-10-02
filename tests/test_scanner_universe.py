"""Exact daily upload selection and context membership, with offline providers."""
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

from sqlalchemy import select

from backend.database.models import Alert, WatchlistLevelMonitor
from backend.store import Store
from db_support import activated_watchlist, test_store
from discovery.config import DiscoverySettings, load_settings
from discovery.service import DiscoveryService
from research.config import load_settings as research_settings
from ripster_scanner.config import Config
from ripster_scanner.scan import ScanResult
from scanner.worker import CONTEXT_SYMBOLS, ScannerWorker
from test_discovery import FakeDiscoveryProvider, MORNING

MONDAY = datetime(2026, 9, 21, 14, tzinfo=timezone.utc)
TUESDAY = MONDAY + timedelta(days=1)
EXPECTED_CONTEXT = {'SPY', 'QQQ', 'MAGS', 'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA'}


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)

    def cycle(self, at, *, enabled=False, during_scan=None):
        provider = FakeDiscoveryProvider()
        worker = ScannerWorker(self.store, discovery_provider=provider if enabled else None,
                               discovery_settings=DiscoverySettings(enabled))
        scanned = []
        def scan(config, wrapped):
            symbol = config.symbols[0]
            scanned.append(symbol)
            if during_scan and len(scanned) == 1:
                during_scan()
            return [ScanResult(symbol)]
        with patch('scanner.worker.now', return_value=at), patch('backend.store.now', return_value=at), \
             patch('scanner.worker.load_config', side_effect=lambda *, symbols: Config('fake', 'fake', symbols)), \
             patch('scanner.worker.StockHistoricalDataClient'), \
             patch('scanner.worker.scan_watchlist', side_effect=scan):
            outcome = worker.run_once()
        return outcome, scanned, provider.calls

    def test_configuration_default_false_explicit_true_and_validation(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(load_settings().enabled)
            os.environ['DISCOVERY_ENABLED'] = 'true'
            self.assertFalse(load_settings().enabled)  # Obsolete name cannot silently re-enable it.
            for value, expected in [('true', True), ('false', False)]:
                os.environ['AUTO_DISCOVERY_ENABLED'] = value
                self.assertEqual(load_settings().enabled, expected)
            os.environ['AUTO_DISCOVERY_ENABLED'] = 'maybe'
            with self.assertRaisesRegex(ValueError, 'AUTO_DISCOVERY_ENABLED'):
                load_settings()

    def test_disabled_excludes_cached_automatic_sources_and_skips_requests(self):
        provider = FakeDiscoveryProvider()
        service = DiscoveryService(self.store.engine, provider, DiscoverySettings(True), research_settings())
        self.assertIn('AMD', service.build_universe((), at=MORNING))
        provider.calls.clear()
        service.settings = DiscoverySettings(False)
        universe = service.build_universe(('UPLOAD',), at=MORNING + timedelta(minutes=6))
        self.assertEqual(set(universe), {'UPLOAD'})
        self.assertEqual(provider.calls, [])

    def test_enabled_preserves_automatic_sources(self):
        outcome, scanned, calls = self.cycle(MORNING, enabled=True)
        self.assertEqual(outcome, 'scanned')
        self.assertEqual(len(calls), 3)
        self.assertEqual(set(scanned), EXPECTED_CONTEXT | {'AMD'})
        rows = {row['symbol']: row for row in self.store.read()['universe']}
        self.assertIn('MOST_ACTIVE', rows['AMD']['sources'])
        self.assertIn('TOP_GAINER', rows['AMD']['sources'])
        self.assertIn('TOP_LOSER', rows['TSLA']['sources'])

    def test_today_only_replaces_previous_and_keeps_history(self):
        old = activated_watchlist(self.store, ('OLD',), at=MONDAY)
        new = activated_watchlist(self.store, ('NEW', 'NVDA'), at=TUESDAY)
        outcome, scanned, calls = self.cycle(TUESDAY)
        self.assertEqual(outcome, 'scanned')
        self.assertEqual(set(scanned), EXPECTED_CONTEXT | {'NEW'})
        self.assertEqual(scanned.count('NVDA'), 1)
        self.assertEqual(len(scanned), len(set(scanned)))
        self.assertEqual(calls, [])
        self.assertEqual(self.store.active_snapshot()['id'], new)
        self.assertEqual(self.store.upload_status(old)['symbols'], ['OLD'])

    def test_previous_day_fallback_then_today_arrives(self):
        old = activated_watchlist(self.store, ('OLD',), at=MONDAY)
        before = self.store.upload_status(old)
        self.assertEqual(set(self.cycle(TUESDAY)[1]), EXPECTED_CONTEXT | {'OLD'})
        fallback = self.store.active_snapshot()['id']
        self.store = Store(self.store.engine)
        self.cycle(TUESDAY + timedelta(minutes=1))
        self.assertEqual(self.store.active_snapshot()['id'], fallback)
        self.assertEqual(self.store.upload_status(old), before)
        new = activated_watchlist(self.store, ('NEW',), at=TUESDAY + timedelta(minutes=2))
        self.assertEqual(set(self.cycle(TUESDAY + timedelta(minutes=3))[1]), EXPECTED_CONTEXT | {'NEW'})
        self.assertEqual(self.store.active_snapshot()['id'], new)

    def test_weekend_and_holiday_previous_session(self):
        for previous, today in [('2026-09-18', '2026-09-21'), ('2026-07-02', '2026-07-06'),
                                ('2026-09-18', '2026-09-20')]:
            with self.subTest(today=today):
                at = datetime.fromisoformat(previous + 'T14:00:00+00:00')
                activated_watchlist(self.store, ('PRIOR',), at=at)
                at = datetime.fromisoformat(today + 'T14:00:00+00:00')
                self.assertEqual(set(self.cycle(at)[1]), EXPECTED_CONTEXT | {'PRIOR'})

    def test_no_progressive_fallback_or_discovery_when_both_days_missing(self):
        old = activated_watchlist(self.store, ('OLD',), at=MONDAY - timedelta(days=3))
        outcome, scanned, calls = self.cycle(TUESDAY)
        self.assertEqual(outcome, 'scanned')
        self.assertEqual(set(scanned), EXPECTED_CONTEXT)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.read()['watchlist'], [])
        self.assertEqual(self.store.upload_status(old)['symbols'], ['OLD'])

    def test_membership_rollover_does_not_extend_fallback_another_day(self):
        old = activated_watchlist(self.store, ('OLD',), at=MONDAY)
        before = self.store.upload_status(old)
        self.assertIn('OLD', self.cycle(TUESDAY)[1])
        self.assertEqual(set(self.cycle(TUESDAY + timedelta(days=1))[1]), EXPECTED_CONTEXT)
        self.assertEqual(self.store.upload_status(old), before)

    def test_latest_activation_on_allowed_date_wins_without_merging(self):
        first = activated_watchlist(self.store, ('AAA',), at=TUESDAY)
        activated_watchlist(self.store, ('BBB',), at=TUESDAY + timedelta(minutes=1))
        self.assertEqual(set(self.cycle(TUESDAY + timedelta(minutes=2))[1]), EXPECTED_CONTEXT | {'BBB'})
        # Activation ordering, not simply upload ID, determines the selected upload.
        with patch('backend.store.now', return_value=TUESDAY + timedelta(minutes=3)):
            self.store.activate(first)
        self.assertEqual(set(self.cycle(TUESDAY + timedelta(minutes=4))[1]), EXPECTED_CONTEXT | {'AAA'})

    def test_empty_database_context_only_and_no_level_monitors(self):
        with patch('scanner.worker.AlpacaDiscoveryProvider') as discovery:
            self.assertEqual(set(self.cycle(TUESDAY)[1]), EXPECTED_CONTEXT)
        discovery.assert_not_called()
        self.assertEqual(set(CONTEXT_SYMBOLS), EXPECTED_CONTEXT)
        self.assertNotIn('VIX', CONTEXT_SYMBOLS)
        with self.store.session() as session:
            self.assertEqual(list(session.scalars(select(WatchlistLevelMonitor))), [])
            self.assertEqual(list(session.scalars(select(Alert))), [])

    def test_staged_unreviewed_upload_does_not_replace_activated_fallback(self):
        from ripster_scanner.watchlist import validate_candidates
        from ripster_scanner.watchlist_image import OCRToken
        activated_watchlist(self.store, ('OLD',), at=MONDAY)
        with patch('backend.store.now', return_value=TUESDAY):
            staged = self.store.snapshot((), source='image')
            self.store.update_import(staged, validate_candidates([OCRToken('NEW', 99)], {'NEW'}))
        self.assertEqual(set(self.cycle(TUESDAY)[1]), EXPECTED_CONTEXT | {'OLD'})

    def test_fallback_scan_is_superseded_by_new_activation_during_fetch(self):
        activated_watchlist(self.store, ('OLD',), at=MONDAY)
        def activate():
            activated_watchlist(self.store, ('NEW',), at=TUESDAY)
        outcome, _, _ = self.cycle(TUESDAY, during_scan=activate)
        self.assertEqual(outcome, 'superseded')
        self.assertEqual(self.store.active_snapshot()['symbols'], ['NEW'])

    def test_activation_immediately_after_fallback_cas_cannot_publish_old_symbols_under_new_id(self):
        activated_watchlist(self.store, ('OLD',), at=MONDAY)
        original = self.store.activate
        def activate(snapshot_id, *, expected_active=None):
            result = original(snapshot_id, expected_active=expected_active)
            if result and expected_active is not None:
                activated_watchlist(self.store, ('NEW',), at=TUESDAY)
            return result
        with patch.object(self.store, 'activate', side_effect=activate):
            self.assertEqual(self.cycle(TUESDAY)[0], 'superseded')
        self.assertEqual(self.store.active_snapshot()['symbols'], ['NEW'])
        self.assertEqual(self.store.read()['universe'], [])

    def test_new_york_date_across_utc_midnight_and_dst(self):
        for at, next_at in [('2026-09-21T23:50:00+00:00', '2026-09-22T00:10:00+00:00'),
                            ('2026-01-12T23:50:00+00:00', '2026-01-13T04:10:00+00:00')]:
            with self.subTest(at=at):
                upload = activated_watchlist(self.store, ('XYZ',), at=datetime.fromisoformat(at))
                self.assertEqual(set(self.cycle(datetime.fromisoformat(next_at))[1]), EXPECTED_CONTEXT | {'XYZ'})
                self.assertEqual(self.store.active_snapshot()['id'], upload)

    def test_context_etfs_use_existing_iex_stock_bar_request(self):
        from ripster_scanner.provider import AlpacaIEXProvider
        from test_scanner_reliability import candle_response
        from ripster_scanner.alpaca_http import StockHistoricalDataClient
        client = StockHistoricalDataClient('fake', 'fake')
        self.addCleanup(client._session.close)
        provider = AlpacaIEXProvider('fake', 'fake', client=client)
        for symbol in ('SPY', 'QQQ', 'MAGS'):
            with self.subTest(symbol=symbol), patch.object(client._session, 'request',
                    return_value=candle_response(symbol)) as request:
                self.assertFalse(provider.fetch(symbol, 3).frame.empty)
                self.assertEqual(request.call_args.kwargs['params']['feed'], 'iex')
                self.assertEqual(request.call_args.kwargs['params']['symbols'], symbol)
