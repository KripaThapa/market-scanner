"""Discovery union, history, failure isolation, sectors and candle completion."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import func, select

from backend.database.models import (DiscoveryEvent, DiscoveryMembership,
    DiscoverySourceStatus, SectorSnapshot, SymbolMetadata, ResearchObservation)
from db_support import test_store
from discovery.candle_state import candle_state
from discovery.alpaca import AlpacaDiscoveryProvider
from discovery.config import DiscoverySettings
from discovery.domain import DiscoveryItem, SourceType
from discovery.service import DiscoveryService
from research.config import load_settings as research_settings
from research.repository import ResearchRepository
from ripster_scanner.config import Config
from ripster_scanner.forming import FormingResult, SetupState
from ripster_scanner.scan import ScanResult
from scanner.worker import ScannerWorker

MORNING = datetime(2026, 9, 18, 13, 30, tzinfo=timezone.utc)


class FakeDiscoveryProvider:
    name = 'Memory Screener'

    def __init__(self):
        self.fail = set()
        self.calls = []
        self.rows = {
            SourceType.MOST_ACTIVE: [('AMD', {'volume': 100000, 'trade_count': 1200}),
                                     ('NVDA', {'volume': 90000})],
            SourceType.TOP_GAINER: [('AMD', {'percent_change': 4.2, 'price': 125})],
            SourceType.TOP_LOSER: [('TSLA', {'percent_change': -3.1, 'price': 200})],
        }

    def fetch(self, source_type, at):
        self.calls.append(source_type)
        if source_type in self.fail:
            raise RuntimeError('provider unavailable')
        return [DiscoveryItem(symbol, source_type, self.name, at, rank, metrics)
                for rank, (symbol, metrics) in enumerate(self.rows[source_type], 1)]


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.provider = FakeDiscoveryProvider()
        self.service = DiscoveryService(self.store.engine, self.provider,
            DiscoverySettings(True, 300, 10), research_settings())

    def test_all_sources_merge_once_and_history_tracks_transitions(self):
        universe = self.service.build_universe(('amd', 'MSFT'),
            {'AMD': 'Technology', 'MSFT': 'Technology'}, at=MORNING)
        self.assertEqual(set(universe), {'AMD', 'MSFT', 'NVDA', 'TSLA'})
        self.assertEqual(universe['AMD']['sources'],
            ['MOST_ACTIVE', 'TOP_GAINER', 'UPLOADED_WATCHLIST'])
        self.assertEqual(universe['TSLA']['sources'], ['TOP_LOSER'])
        self.assertEqual(universe['NVDA']['sector'], 'UNKNOWN')
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DiscoveryMembership)), 6)
            self.assertEqual(session.scalar(select(func.count()).select_from(DiscoveryEvent)), 6)
            metadata = session.get(SymbolMetadata, 'AMD')
            self.assertEqual((metadata.sector, metadata.metadata_source),
                             ('Technology', 'config/sectors.json'))
            first_retrieved = metadata.retrieved_at
        self.service.build_universe(('AMD', 'MSFT'), {'AMD': 'Technology', 'MSFT': 'Technology'},
                                    at=MORNING + timedelta(minutes=1))
        self.assertEqual(len(self.provider.calls), 3)  # No API hammering before refresh interval.
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DiscoveryEvent)), 6)
            self.assertEqual(session.get(SymbolMetadata, 'AMD').retrieved_at, first_retrieved)
        self.provider.rows[SourceType.MOST_ACTIVE] = [('NVDA', {'volume': 95000})]
        self.service.build_universe(('AMD',), {'AMD': 'Technology'},
                                    at=MORNING + timedelta(minutes=5))
        with self.store.session() as session:
            amd_most = session.scalar(select(DiscoveryMembership).where(
                DiscoveryMembership.symbol == 'AMD',
                DiscoveryMembership.source_type == 'MOST_ACTIVE'))
            self.assertFalse(amd_most.active)
            self.assertEqual(amd_most.first_seen_at.replace(tzinfo=timezone.utc), MORNING)
            self.assertEqual(session.scalar(select(DiscoveryEvent).where(
                DiscoveryEvent.symbol == 'AMD', DiscoveryEvent.source_type == 'MOST_ACTIVE')
                .order_by(DiscoveryEvent.id.desc())).active, False)

    def test_source_failure_retains_last_known_and_does_not_stop_others(self):
        self.service.build_universe(('AMD',), at=MORNING)
        self.provider.fail.add(SourceType.MOST_ACTIVE)
        self.provider.rows[SourceType.TOP_GAINER] = [('MSFT', {'percent_change': 2.1})]
        universe = self.service.build_universe(('AMD',), at=MORNING + timedelta(minutes=5))
        self.assertIn('NVDA', universe)  # Last-known successful Most Active result.
        self.assertIn('MSFT', universe)  # Gainer refresh succeeded independently.
        with self.store.session() as session:
            self.assertEqual(session.get(DiscoverySourceStatus, 'MOST_ACTIVE').status, 'FAILED')
            self.assertEqual(session.get(DiscoverySourceStatus, 'TOP_GAINER').status, 'OK')

    def test_alpaca_adapter_returns_provider_neutral_results(self):
        class Client:
            def get_most_actives(self, request):
                return SimpleNamespace(most_actives=[SimpleNamespace(symbol='amd', volume=1200,
                                                                       trade_count=50)])

            def get_market_movers(self, request):
                return SimpleNamespace(gainers=[SimpleNamespace(symbol='nvda', percent_change=3.2,
                    change=5, price=160)], losers=[SimpleNamespace(symbol='tsla',
                    percent_change=-2.0, change=-4, price=190)])

        adapter = AlpacaDiscoveryProvider('', '', client=Client(), top=10)
        active = adapter.fetch(SourceType.MOST_ACTIVE, MORNING)
        gainers = adapter.fetch(SourceType.TOP_GAINER, MORNING)
        losers = adapter.fetch(SourceType.TOP_LOSER, MORNING)
        self.assertEqual((active[0].symbol, active[0].metrics['volume']), ('AMD', 1200))
        self.assertEqual((gainers[0].symbol, gainers[0].metrics['percent_change']), ('NVDA', 3.2))
        self.assertEqual(losers[0].source_type, SourceType.TOP_LOSER)
        self.assertEqual(active[0].provider, 'Alpaca Screener')

    def test_universe_scanned_once_and_sector_snapshot_is_objective(self):
        snapshot = self.store.snapshot(('AMD', 'MSFT'))
        self.store.activate(snapshot)
        worker = ScannerWorker(self.store, discovery_provider=self.provider,
                               discovery_settings=DiscoverySettings(True, 300, 10))
        with patch('scanner.worker.now', return_value=MORNING), \
             patch('backend.store.now', return_value=MORNING), \
             patch('scanner.worker.load_config', side_effect=lambda *, symbols:
                   Config('fake', 'fake', symbols)), \
             patch('scanner.worker.StockHistoricalDataClient'), \
             patch('scanner.worker.scan_watchlist', side_effect=lambda config, provider:
                   [ScanResult(config.symbols[0],
                       {'trend': 'BULLISH' if config.symbols[0] != 'TSLA' else 'BEARISH',
                        'close': 100, 'vwap_position': 'ABOVE'},
                       {'trend': 'MIXED'},
                       FormingResult(SetupState.FORMING_LONG, 'fixture', 0)
                       if config.symbols[0] == 'AMD' else FormingResult())]) as scan, \
             patch.object(worker, 'sector_map', return_value={
                 'AMD': 'Technology', 'MSFT': 'Technology'}):
            self.assertEqual(worker.run_once(), 'scanned')
        self.assertEqual(len(scan.call_args_list), 4)
        self.assertEqual(len({call.args[0].symbols[0] for call in scan.call_args_list}), 4)
        internal = self.store.read()
        self.assertEqual(len(internal['universe']), 4)
        self.assertEqual(len(internal['watchlist']), 2)
        technology = next(item for item in internal['sectors'] if item['sector'] == 'Technology')
        self.assertEqual((technology['symbol_count'], technology['bullish_count'],
                          technology['forming_long_count']), (2, 2, 1))
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SectorSnapshot)), 2)
            observations = session.scalars(select(ResearchObservation)).all()
            self.assertEqual(len(observations), 4)
            self.assertEqual(next(row for row in observations if row.symbol == 'AMD').discovery_sources,
                             ['MOST_ACTIVE', 'TOP_GAINER', 'UPLOADED_WATCHLIST'])
        research = ResearchRepository(self.store.engine)
        self.assertEqual({r['symbol'] for r in research.list_observations(
            discovery_source='TOP_GAINER')}, {'AMD'})
        self.assertEqual({r['symbol'] for r in research.list_observations(
            sector='Technology')}, {'AMD', 'MSFT'})
        self.assertEqual(len(research.list_observations(candle_state='COMPLETED')), 0)
        self.assertEqual(len(research.list_observations(decision_eligible=False)), 4)


class CandleStateTests(unittest.TestCase):
    def test_opening_timestamp_boundary_and_timezone(self):
        start = '2026-09-18T09:30:00-04:00'
        self.assertEqual(candle_state(start, '3m', datetime(2026, 9, 18, 13, 32, 59,
                              tzinfo=timezone.utc)), 'PARTIAL')
        self.assertEqual(candle_state(start, '3m', datetime(2026, 9, 18, 13, 33,
                              tzinfo=timezone.utc)), 'COMPLETED')
        self.assertEqual(candle_state(start, '10m', datetime(2026, 9, 18, 13, 39,
                              tzinfo=timezone.utc)), 'PARTIAL')
        self.assertEqual(candle_state(start, '10m', datetime(2026, 9, 18, 13, 40,
                              tzinfo=timezone.utc)), 'COMPLETED')
        self.assertEqual(candle_state('2026-01-16T09:30:00-05:00', '3m',
            datetime(2026, 1, 16, 14, 33, tzinfo=timezone.utc)), 'COMPLETED')
        self.assertIsNone(candle_state(None, '3m', MORNING))


if __name__ == '__main__':
    unittest.main()
