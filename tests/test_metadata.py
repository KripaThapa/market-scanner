"""Reference enrichment with fake transports only; no external provider calls."""

from datetime import timedelta
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend.api import create_app
from backend.database.models import Alert, SymbolMetadata, ResearchObservation
from discovery.config import DiscoverySettings
from discovery.fmp import FMPMetadataProvider
from discovery.metadata import SymbolMetadataService
from discovery.metadata_provider import CompanyMetadata, MetadataResult
from discovery.service import DiscoveryService
from research.config import load_settings
from ripster_scanner.config import Config, FormingThresholds
from ripster_scanner.strategy import strategy_version_id
from scanner.worker import CONTEXT_SYMBOLS, ScannerWorker
from db_support import test_store, activated_watchlist
from test_alerts import observed, START, VERSION


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.provider = Mock(name='provider')
        self.provider.name = 'Fake Reference'
        self.provider.fetch.side_effect = lambda symbol: MetadataResult('OK', CompanyMetadata(
            symbol, 'Example', 'Technology', 'Semiconductors', '000123', 'US123', '123', 'NASDAQ', 'US'))
        self.service = SymbolMetadataService(self.store.engine, self.provider)

    def resolve(self, symbols=('AAA',), *, days=0, fallback=None):
        return self.service.resolve(symbols, fallback, at=START + timedelta(days=days))

    def test_missing_persists_and_fresh_survives_service_restart_without_calls(self):
        self.assertEqual(self.resolve()['AAA']['sector'], 'Technology')
        with self.store.session() as session:
            row = session.get(SymbolMetadata, 'AAA')
            self.assertEqual((row.company_name, row.industry, row.cik), ('Example', 'Semiconductors', '000123'))
            self.assertEqual(row.metadata_source, 'Fake Reference')
        self.service = SymbolMetadataService(self.store.engine, self.provider)
        self.resolve(days=6)
        self.assertEqual(self.provider.fetch.call_count, 1)
        self.resolve(days=7)
        self.assertEqual(self.provider.fetch.call_count, 2)

    def test_failure_retains_cache_and_negative_deadline(self):
        self.resolve()
        self.provider.fetch.side_effect = requests.Timeout('secret-url')
        self.assertEqual(self.resolve(days=8)['AAA']['sector'], 'Technology')
        self.resolve(days=8)
        self.assertEqual(self.provider.fetch.call_count, 2)
        self.resolve(days=9)
        self.assertEqual(self.provider.fetch.call_count, 3)

    def test_outage_new_symbols_unknown_and_circuit_bounds_calls(self):
        self.provider.fetch.side_effect = requests.Timeout('secret-url')
        rows = self.resolve(('AAA', 'BBB'))
        self.assertEqual([r['sector'] for r in rows.values()], ['UNKNOWN', 'UNKNOWN'])
        self.resolve(('AAA', 'BBB'))
        self.assertEqual(self.provider.fetch.call_count, 1)

    def test_not_found_and_partial_are_negatively_cached(self):
        for status in ('NOT_FOUND', 'PARTIAL'):
            with self.subTest(status=status):
                self.provider.fetch.side_effect = None
                self.provider.fetch.return_value = MetadataResult(status)
                symbol = 'NONE' if status == 'NOT_FOUND' else 'PART'
                self.resolve((symbol,))
                count = self.provider.fetch.call_count
                self.resolve((symbol,))
                self.assertEqual(self.provider.fetch.call_count, count)
                self.resolve((symbol,), days=1)
                self.assertEqual(self.provider.fetch.call_count, count + 1)

    def test_32_symbols_then_zero_calls_next_cycle(self):
        symbols = tuple(f'S{i}' for i in range(32))
        self.resolve(symbols)
        self.assertEqual(self.provider.fetch.call_count, 32)
        self.resolve(symbols)
        self.assertEqual(self.provider.fetch.call_count, 32)

    def test_request_budget_defers_remaining_symbols(self):
        self.service.max_requests = 1
        rows = self.resolve(('AAA', 'BBB'))
        self.assertEqual(rows['BBB']['sector'], 'UNKNOWN')
        self.resolve(('AAA', 'BBB'))
        self.assertEqual(self.provider.fetch.call_count, 2)

    def test_time_budget_defers_requests(self):
        with patch('discovery.metadata.time.monotonic', side_effect=[0, 21]):
            self.resolve()
        self.provider.fetch.assert_not_called()

    def test_commit_failure_never_publishes_unpersisted_metadata(self):
        def fail(session):
            if any(isinstance(row, SymbolMetadata) and row.company_name == 'Example'
                   for row in session.identity_map.values()):
                raise RuntimeError('private database failure')
        event.listen(Session, 'before_commit', fail)
        try:
            with self.assertLogs('discovery.metadata', level='WARNING') as logs:
                row = self.resolve()['AAA']
        finally:
            event.remove(Session, 'before_commit', fail)
        self.assertEqual(row['sector'], 'UNKNOWN')
        self.assertNotIn('private database failure', str(logs.output))
        with self.store.session() as session:
            self.assertEqual(session.get(SymbolMetadata, 'AAA').sector, 'UNKNOWN')
        self.resolve()
        self.assertEqual(self.provider.fetch.call_count, 1)

    def test_partial_classification_retains_known_fields_and_retries_later(self):
        self.resolve()
        self.provider.fetch.side_effect = None
        self.provider.fetch.return_value = MetadataResult('PARTIAL', CompanyMetadata(
            'AAA', company_name='Updated', sector='Energy'))
        row = self.resolve(days=8)['AAA']
        self.assertEqual((row['sector'], row['industry']), ('Energy', 'Semiconductors'))
        self.resolve(days=8)
        self.assertEqual(self.provider.fetch.call_count, 2)
        self.resolve(days=9)
        self.assertEqual(self.provider.fetch.call_count, 3)

    def test_legacy_unknown_alert_stays_unknown_after_enrichment(self):
        snapshot = self.store.snapshot(('AAA',))
        self.store.activate(snapshot)
        first = observed()
        with patch('backend.store.now', return_value=first.evaluated_at):
            self.store.publish(snapshot, [first])
        self.resolve()
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(Alert)).snapshot['sector'], 'UNKNOWN')

    def test_config_absent_unknown_and_conflicting_mapping_never_erase_cache(self):
        discovery = DiscoveryService(self.store.engine, None, DiscoverySettings(False),
            load_settings(), metadata_service=self.service)
        for fallback in (None, {'AAA': 'UNKNOWN'}, {'AAA': 'Energy'}):
            universe = discovery.build_universe(('AAA',), fallback, at=START)
            self.assertEqual(universe['AAA']['sector'], 'Technology')
        self.assertEqual(self.provider.fetch.call_count, 1)

    def test_config_fallback_then_provider_takes_precedence(self):
        self.provider.fetch.side_effect = None
        self.provider.fetch.return_value = MetadataResult('UNAVAILABLE')
        self.assertEqual(self.resolve(fallback={'AAA': 'Energy'})['AAA']['sector'], 'Energy')
        self.provider.fetch.return_value = MetadataResult('OK', CompanyMetadata('AAA', 'Example', 'Technology', 'Software'))
        self.assertEqual(self.resolve(days=1)['AAA']['sector'], 'Technology')

    def test_unknown_provider_fields_do_not_erase_existing(self):
        self.resolve()
        self.provider.fetch.side_effect = None
        self.provider.fetch.return_value = MetadataResult('PARTIAL', CompanyMetadata('AAA', sector='UNKNOWN'))
        row = self.resolve(days=8)['AAA']
        self.assertEqual((row['sector'], row['industry']), ('Technology', 'Semiconductors'))

    def test_future_alerts_snapshot_cache_without_rewriting_history_or_api_leaks(self):
        snapshot = self.store.snapshot(('AAA',))
        self.store.activate(snapshot)
        universe = {'AAA': {'sources': [], **self.resolve()['AAA']}}
        first = observed()
        with patch('backend.store.now', return_value=first.evaluated_at):
            self.store.publish(snapshot, [first], universe=universe)
        self.provider.fetch.side_effect = None
        self.provider.fetch.return_value = MetadataResult('OK', CompanyMetadata('AAA', 'Changed', 'Energy', 'Oil'))
        self.resolve(days=8)
        with self.store.session() as session:
            alert = session.scalar(select(Alert))
            self.assertEqual(alert.snapshot['sector'], 'Technology')
            observation = session.scalar(select(ResearchObservation))
            self.assertEqual(observation.sector, 'Technology')
        with TestClient(create_app(store=self.store), base_url='http://localhost') as client:
            response = client.get('/api/dashboard')
            self.assertEqual(response.status_code, 200)
            text = response.text
            for private in ('Fake Reference', '000123', 'US123', 'metadata_source', 'retrieved_at', 'cik', 'cusip', 'isin'):
                self.assertNotIn(private, text)
            row = response.json()['universe'][0]
            self.assertEqual((row['sector'], row['industry']), ('Technology', 'Semiconductors'))
        second = replace(observed('FORMING_SHORT', minute=3), evaluated_at=START + timedelta(days=8, minutes=6))
        universe['AAA'].update(self.resolve(days=8)['AAA'])
        with patch('backend.store.now', return_value=second.evaluated_at):
            self.store.publish(snapshot, [second], universe=universe)
        with self.store.session() as session:
            rows = list(session.scalars(select(Alert).order_by(Alert.id)))
            self.assertEqual([r.snapshot['sector'] for r in rows], ['Technology', 'Energy'])
        self.assertEqual(strategy_version_id(FormingThresholds()), VERSION)

    def test_provider_timeout_does_not_stop_worker_or_publication(self):
        activated_watchlist(self.store, ('AAA', 'BBB'), at=START)
        self.provider.fetch.side_effect = requests.Timeout('private-url')
        worker = ScannerWorker(self.store, discovery_settings=DiscoverySettings(False), metadata_service=self.service)
        with patch('scanner.worker.now', return_value=START), \
             patch('backend.store.now', return_value=START), \
             patch('scanner.worker.load_config', side_effect=lambda *, symbols: Config('fake', 'fake', symbols)), \
             patch('scanner.worker.StockHistoricalDataClient'), \
             patch('scanner.worker.scan_watchlist', side_effect=lambda config, provider: [observed(symbol=config.symbols[0])]) as scan:
            self.assertEqual(worker.run_once(), 'scanned')
            self.assertEqual(worker.run_once(), 'scanned')
        self.assertEqual(scan.call_count, 2 * (2 + len(CONTEXT_SYMBOLS)))
        self.assertEqual(self.provider.fetch.call_count, 1)


class FMPProviderTests(unittest.TestCase):
    def fetch(self, payload=None, *, status=200, error=None):
        client = Mock()
        if error:
            client.get.side_effect = error
        else:
            response = Mock(status_code=status)
            response.json.return_value = payload
            client.get.return_value.__enter__ = Mock(return_value=response)
            client.get.return_value.__exit__ = Mock(return_value=False)
        result = FMPMetadataProvider('fake-secret', client=client).fetch('AAA')
        self.assertEqual(client.get.call_args.kwargs['timeout'], (3, 5))
        self.assertFalse(client.get.call_args.kwargs['allow_redirects'])
        self.assertNotIn('fake-secret', repr(result))
        return result

    def test_provider_shapes_and_missing_fields(self):
        self.assertEqual(self.fetch([]).status, 'NOT_FOUND')
        for payload in ({}, None, [{'symbol': 'BBB'}], [None], [{}, {}]):
            self.assertEqual(self.fetch(payload).status, 'MALFORMED')
        for field in ('sector', 'industry', 'companyName'):
            row = {'symbol': 'AAA', 'sector': 'Technology', 'industry': 'Software', 'companyName': 'Example'}
            row.pop(field)
            self.assertEqual(self.fetch([row]).status, 'PARTIAL')
        self.assertEqual(self.fetch([{'symbol': 'AAA', 'sector': 'Technology', 'industry': 'Software', 'companyName': 'Example', 'price': 100}]).status, 'OK')

    def test_http_timeout_network_json_failures(self):
        for status in (301, 401, 403, 404, 429, 500):
            self.assertEqual(self.fetch(status=status).status, 'HTTP_ERROR')
        for error, expected in ((requests.Timeout('private'), 'TIMEOUT'),
                                (requests.ConnectionError('private'), 'UNAVAILABLE'),
                                (ValueError('private'), 'MALFORMED')):
            self.assertEqual(self.fetch(error=error).status, expected)

    def test_reflected_key_is_never_persistable(self):
        row = self.fetch([{'symbol': 'AAA', 'sector': 'fake-secret'}])
        self.assertIsNone(row.metadata.sector)
