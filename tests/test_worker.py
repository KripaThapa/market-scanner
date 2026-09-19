"""Worker lifecycle, isolation and persistence; no live Alpaca requests."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from backend.database.models import Base, ScanResultModel
from backend.store import Store
from ripster_scanner.config import Config
from ripster_scanner.scan import ScanResult
from scanner.worker import ScannerWorker
from db_support import test_store


def result(symbol):
    return ScanResult(symbol, {'trend': 'BULLISH', 'close': 125, 'ema_5': 120, 'ema_12': 119,
                              'ema_34': 118, 'ema_50': 117, 'vwap': 121, 'vwap_position': 'ABOVE'},
                      {'trend': 'MIXED', 'ema_5': 122})


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.worker = ScannerWorker(self.store)
        patcher = patch('scanner.worker.load_config', side_effect=lambda *, symbols: Config('fake', 'fake', symbols))
        self.config = patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch('scanner.worker.StockHistoricalDataClient')
        self.client = patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch('scanner.worker.scan_watchlist', side_effect=lambda config, client: [result(config.symbols[0])])
        self.scan = patcher.start(); self.addCleanup(patcher.stop)

    def activate(self, symbols=('NVDA', 'AMD')):
        snapshot = self.store.snapshot(symbols)
        self.store.activate(snapshot)
        return snapshot

    def test_no_active_watchlist_stays_ready_and_does_not_load_credentials(self):
        for _ in range(2):
            with self.assertLogs('scanner.worker', level='INFO') as logs:
                self.assertEqual(self.worker.run_once(), 'empty')
            self.assertIn('nothing to scan', '\n'.join(logs.output))
        self.config.assert_not_called()
        self.scan.assert_not_called()
        self.assertEqual(self.store.state()['status'], 'waiting')
        self.assertIsNotNone(self.store.state()['scanner_heartbeat'])

    def test_worker_saves_results_and_indicator_values(self):
        self.activate()
        self.assertEqual(self.worker.run_once(), 'scanned')
        self.assertEqual([row['symbol'] for row in self.store.read()['watchlist']], ['NVDA', 'AMD'])
        with self.store.session() as session:
            rows = session.scalars(select(ScanResultModel)).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].ema_50, 117)
            self.assertEqual(rows[0].analysis_3m['ema_5'], 122)
        self.config.assert_called_once_with(symbols=('NVDA', 'AMD'))
        self.assertEqual([call.args[0].symbols for call in self.scan.call_args_list], [('NVDA',), ('AMD',)])

    def test_ticker_failure_does_not_stop_other_symbols_or_next_cycle(self):
        self.activate(('NVDA', 'BAD', 'AMD'))
        def scan(config, client):
            if config.symbols == ('BAD',):
                raise RuntimeError('secret-provider-data')
            return [result(config.symbols[0])]
        self.scan.side_effect = scan
        for _ in range(2):
            self.assertEqual(self.worker.run_once(), 'scanned')
        rows = self.store.read()['watchlist']
        self.assertEqual([r['context_10m'] for r in rows], ['BULLISH', 'NO DATA', 'BULLISH'])
        self.assertIn('failed', rows[1]['error'])
        self.assertNotIn('secret', str(self.store.read()))

    def test_empty_market_data_still_publishes_other_symbols(self):
        self.activate()
        self.scan.side_effect = [[ScanResult('NVDA')], [result('AMD')]]
        self.assertEqual(self.worker.run_once(), 'scanned')
        self.assertEqual(self.store.read()['watchlist'][0]['context_10m'], 'NO DATA')

    def test_new_upload_during_scan_discards_old_results(self):
        old = self.activate()
        def scan(config, client):
            if config.symbols == ('NVDA',):
                self.activate(('TSLA',))
            return [result(config.symbols[0])]
        self.scan.side_effect = scan
        self.assertEqual(self.worker.run_once(), 'superseded')
        self.assertNotEqual(self.store.active_snapshot()['id'], old)
        self.assertEqual(self.store.read()['watchlist'][0]['symbol'], 'TSLA')
        self.assertIsNone(self.store.current_snapshot())

    def test_daily_rollover_and_restart_use_persisted_watchlist(self):
        old = self.activate()
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        with patch('scanner.worker.now', return_value=future), patch('backend.store.now', return_value=future):
            self.assertEqual(self.worker.run_once(), 'scanned')
            current = self.store.active_snapshot()
            self.assertNotEqual(current['id'], old)
            self.assertEqual(current['date'], '2099-01-01')
            self.assertEqual(ScannerWorker(Store(self.store.engine)).run_once(), 'scanned')
            self.assertEqual(self.store.active_snapshot()['id'], current['id'])

    def test_config_failure_keeps_previous_scan_and_worker_alive(self):
        self.activate()
        self.worker.run_once()
        previous = self.store.read()['watchlist']
        self.config.side_effect = RuntimeError('private credentials')
        self.assertEqual(self.worker.run_once(), 'failed')
        self.assertEqual(self.store.read()['watchlist'], previous)
        self.assertEqual(self.store.state()['status'], 'idle')
        self.assertNotIn('private', self.store.state()['last_error'])

    def test_scanner_lock_skips_duplicate_worker(self):
        with self.store.claim_lock('scanner') as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.worker.run_once(), 'busy')
        self.scan.assert_not_called()

    def test_json_fallback_is_opt_in_and_never_overrides_an_upload(self):
        with patch('scanner.worker.load_watchlist', return_value=('AMD',)) as fallback:
            self.assertEqual(self.worker.run_once(), 'empty')
            fallback.assert_not_called()
            worker = ScannerWorker(self.store, json_fallback=True)
            self.assertEqual(worker.run_once(), 'scanned')
            fallback.assert_called_once()
            self.activate(('NVDA',))
            self.assertEqual(worker.run_once(), 'scanned')
            fallback.assert_called_once()
            self.assertEqual(self.store.active_snapshot()['symbols'], ['NVDA'])

    def test_sector_mapping_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sectors.json'
            worker = ScannerWorker(self.store, sector_path=path)
            self.assertEqual(worker.sector_map(), {})
            path.write_text('{"NVDA":"Technology"}')
            self.assertEqual(worker.sector_map(), {'NVDA': 'Technology'})
            path.write_text('[]')
            with self.assertRaises(ValueError):
                worker.sector_map()

    def test_migration_is_repeatable_and_matches_models(self):
        config = AlembicConfig(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        with self.store.engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
            self.assertEqual(differences, [])
        self.store.check_ready()


if __name__ == '__main__':
    unittest.main()
