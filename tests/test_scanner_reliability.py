"""Real SDK request paths with in-memory transports; no network or sleeps."""

from dataclasses import replace
from datetime import timedelta
import json
import re
import unittest
from unittest.mock import patch

from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient as SDKStockClient
from requests import Response
from requests.exceptions import ConnectTimeout, ReadTimeout

from backend.database.models import DiscoverySourceStatus
from db_support import test_store
from discovery.alpaca import AlpacaDiscoveryProvider
from discovery.config import DiscoverySettings
from discovery.service import DiscoveryService
from research.config import load_settings
from ripster_scanner.alpaca_http import StockHistoricalDataClient, ScreenerClient
from ripster_scanner.config import Config, FormingThresholds
from ripster_scanner.provider import AlpacaIEXProvider
from ripster_scanner.scan import scan_watchlist
from ripster_scanner.strategy import strategy_version_id
from scanner.worker import ScannerWorker
from test_discovery import FakeDiscoveryProvider, MORNING
from test_watchlist import bars


def response(payload, status=200):
    result = Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    return result


def candle_response(symbol):
    rows = [{'t': at.isoformat(), 'o': float(row.open), 'h': float(row.high),
             'l': float(row.low), 'c': float(row.close), 'v': float(row.volume),
             'n': 1, 'vw': float(row.close)}
            for at, row in bars().iterrows()]
    return response({'bars': {symbol: rows}, 'next_page_token': None})


class HTTPTimeoutTests(unittest.TestCase):
    def test_timeout_reaches_transport_for_each_client_and_retry_is_finite(self):
        for client_type in (StockHistoricalDataClient, ScreenerClient):
            for status in (429, 504):
                with self.subTest(client=client_type.__name__, status=status):
                    client = client_type('fake', 'fake')
                    self.addCleanup(client._session.close)
                    with patch.object(client._session, 'request',
                                      return_value=response({'message': 'unavailable'}, status)) as request, \
                         patch('alpaca.common.rest.time.sleep') as sleep:
                        with self.assertRaises(APIError):
                            client.get('/test')
                    self.assertEqual(request.call_count, 4)
                    self.assertEqual(sleep.call_count, 3)
                    for call in request.call_args_list:
                        self.assertEqual(call.kwargs['timeout'], (5, 20))
                    self.assertTrue(all(call.args == (3,) for call in sleep.call_args_list))

    def test_timeout_propagates_without_retry_sleep(self):
        for client_type in (StockHistoricalDataClient, ScreenerClient):
            for error in (ConnectTimeout, ReadTimeout):
                with self.subTest(client=client_type.__name__, error=error.__name__):
                    client = client_type('fake', 'fake')
                    self.addCleanup(client._session.close)
                    with patch.object(client._session, 'request', side_effect=error('private')) as request, \
                         patch('alpaca.common.rest.time.sleep') as sleep:
                        with self.assertRaises(error):
                            client.get('/test')
                    self.assertEqual(request.call_count, 1)
                    self.assertEqual(request.call_args.kwargs['timeout'], (5, 20))
                    sleep.assert_not_called()

    def test_successful_paginated_candles_preserve_strategy_output(self):
        config = Config('fake', 'fake', ('AMD',))
        outputs = []
        for client_type in (SDKStockClient, StockHistoricalDataClient):
            client = client_type('fake', 'fake')
            self.addCleanup(client._session.close)
            payload = candle_response('AMD').json()['bars']['AMD']
            pages = [response({'bars': {'AMD': payload[:100]}, 'next_page_token': 'page2'}),
                     response({'bars': {'AMD': payload[100:]}, 'next_page_token': None})]
            with patch.object(client._session, 'request', side_effect=pages) as request:
                result = scan_watchlist(config, AlpacaIEXProvider('fake', 'fake', client=client))[0]
            outputs.append(replace(result, evaluated_at=None))
            self.assertEqual(request.call_count, 2)
            if client_type is StockHistoricalDataClient:
                self.assertTrue(all(call.kwargs['timeout'] == (5, 20)
                                    for call in request.call_args_list))
        self.assertEqual(outputs[0], outputs[1])
        self.assertTrue(outputs[1].has_data)
        self.assertEqual(strategy_version_id(FormingThresholds()),
                         'experimental-forming-v1/b067b3150de3')

    def test_default_adapters_construct_timeout_clients(self):
        candle = AlpacaIEXProvider('fake', 'fake')
        discovery = AlpacaDiscoveryProvider('fake', 'fake')
        self.addCleanup(candle.client._session.close)
        self.addCleanup(discovery.client._session.close)
        self.assertIsInstance(candle.client, StockHistoricalDataClient)
        self.assertIsInstance(discovery.client, ScreenerClient)


class WorkerReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        snapshot = self.store.snapshot(('AAA', 'BBB'), source='image')
        self.store.activate(snapshot)
        patcher = patch('scanner.worker.load_config', side_effect=lambda *, symbols:
                        Config('fake', 'fake', symbols))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_symbol_failures_continue_publish_and_advance_heartbeat(self):
        for error in (ReadTimeout, ConnectTimeout, RuntimeError):
            with self.subTest(error=error.__name__):
                worker = ScannerWorker(self.store, discovery_settings=DiscoverySettings(False))
                attempted = []
                def request(session, method, url, **kwargs):
                    self.assertEqual(kwargs['timeout'], (5, 20))
                    symbol = kwargs['params']['symbols']
                    attempted.append(symbol)
                    if symbol == 'AAA':
                        raise error('private-provider-body-secret')
                    return candle_response(symbol)
                before = self.store.state()['scanner_heartbeat']
                with patch('requests.sessions.Session.request', autospec=True, side_effect=request), \
                     self.assertLogs(level='INFO') as captured:
                    self.assertEqual(worker.run_once(), 'scanned')
                    self.assertEqual(worker.run_once(), 'scanned')
                self.assertEqual(attempted, ['AAA', 'BBB', 'AAA', 'BBB'])
                state = self.store.state()
                self.assertEqual(state['status'], 'idle')
                self.assertIsNotNone(state['scanner_heartbeat'])
                if before:
                    self.assertGreaterEqual(state['scanner_heartbeat'], before)
                rows = {row['symbol']: row for row in self.store.read()['watchlist']}
                self.assertEqual(rows['AAA']['context_10m'], 'NO DATA')
                self.assertIsNotNone(rows['AAA']['error'])
                self.assertNotEqual(rows['BBB']['context_10m'], 'NO DATA')
                messages = '\n'.join(captured.output)
                self.assertNotIn('private-provider-body-secret', messages)
                cycles = re.findall(r'cycle=([0-9a-f]{32}) stage=cycle_started', messages)
                self.assertEqual(len(set(cycles)), 2)
                category = 'processing_error' if error is RuntimeError else 'timeout'
                for cycle in cycles:
                    self.assertIn(f'cycle={cycle} stage=universe_loaded uploaded_symbols=2', messages)
                    self.assertIn(f'cycle={cycle} symbol=AAA stage=scan_started', messages)
                    self.assertRegex(messages, f'cycle={cycle} symbol=AAA stage=scan_failed duration_ms=[0-9.]+ error_type={category}')
                    self.assertRegex(messages, f'cycle={cycle} symbol=BBB stage=scan_completed duration_ms=[0-9.]+')
                    self.assertIn(f'cycle={cycle} stage=publication_started results=2 failures=1', messages)
                    for stage in ('discovery', 'publication', 'cycle'):
                        self.assertRegex(messages, f'cycle={cycle} stage={stage}_completed duration_ms=[0-9.]+')

    def test_discovery_timeout_retains_membership_and_cycle_finishes(self):
        settings = DiscoverySettings(True, 300, 10)
        DiscoveryService(self.store.engine, FakeDiscoveryProvider(), settings,
                         load_settings()).build_universe(('AAA', 'BBB'), at=MORNING)
        adapter = AlpacaDiscoveryProvider('fake', 'fake')
        self.addCleanup(adapter.client._session.close)
        worker = ScannerWorker(self.store, discovery_provider=adapter, discovery_settings=settings)
        def request(session, method, url, **kwargs):
            self.assertEqual(kwargs['timeout'], (5, 20))
            if '/screener/' in url:
                raise ReadTimeout('private-discovery-secret')
            return candle_response(kwargs['params']['symbols'])
        at = MORNING + timedelta(minutes=5)
        with patch('scanner.worker.now', return_value=at), \
             patch('backend.store.now', return_value=at), \
             patch('requests.sessions.Session.request', autospec=True, side_effect=request), \
             self.assertLogs(level='INFO') as captured:
            self.assertEqual(worker.run_once(), 'scanned')
        with self.store.session() as session:
            for source in ('MOST_ACTIVE', 'TOP_GAINER', 'TOP_LOSER'):
                self.assertEqual(session.get(DiscoverySourceStatus, source).status, 'FAILED')
        universe = {row['symbol'] for row in self.store.read()['universe']}
        self.assertEqual(universe, {'AAA', 'BBB', 'AMD', 'NVDA', 'TSLA'})
        messages = '\n'.join(captured.output)
        self.assertNotIn('private-discovery-secret', messages)
        self.assertEqual(messages.count('stage=discovery_source_failed'), 3)
        self.assertIn('error_type=timeout', messages)
        self.assertIn('stage=cycle_completed', messages)

    def test_publication_failure_logs_stage_without_exception_body(self):
        worker = ScannerWorker(self.store, discovery_settings=DiscoverySettings(False))
        with patch('scanner.worker.scan_watchlist', return_value=[]), \
             patch.object(self.store, 'publish', side_effect=RuntimeError('private-db-secret')), \
             self.assertLogs('scanner.worker', level='INFO') as captured:
            self.assertEqual(worker.run_once(), 'failed')
        messages = '\n'.join(captured.output)
        self.assertIn('stage=publication_failed error_type=processing_error', messages)
        self.assertNotIn('stage=publication_completed', messages)
        self.assertNotIn('private-db-secret', messages)
        self.assertEqual(self.store.state()['status'], 'idle')
