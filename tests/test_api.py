"""API persistence and uploads against migrated, isolated SQLAlchemy databases."""

from io import BytesIO
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select

from backend.api import create_app
from backend.internal_api import create_internal_app
from backend.database.models import Alert, FormingSetup, ScanResultModel, WatchlistSymbol, WatchlistUpload
from backend.store import Store, now
from backend.uploads import MAX_UPLOAD
from backend.watchlist_worker import WatchlistProcessor
from ripster_scanner.config import Config
from ripster_scanner.scan import ScanResult
from ripster_scanner.forming import FormingResult, SetupState
from ripster_scanner.watchlist_image import OCRToken
from db_support import test_store


def image_bytes(format='PNG'):
    stream = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(stream, format=format)
    return stream.getvalue()


def result(symbol='NVDA', trend='BULLISH', price=125):
    return ScanResult(symbol, {'trend': trend, 'vwap_position': 'ABOVE', 'close': price,
                              'ema_5': 120, 'ema_12': 119, 'ema_34': 118, 'ema_50': 117, 'vwap': 121},
                      {'trend': 'MIXED'})


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = test_store(self)
        self.app = create_app(self.temp.name, store=self.store)
        self.client = TestClient(self.app, base_url='http://localhost')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.internal_client = TestClient(create_internal_app(store=self.store, data_dir=self.temp.name), base_url='http://localhost')

    def seed(self):
        snapshot = self.store.snapshot(('NVDA', 'AMD', 'EMPTY'))
        self.store.activate(snapshot)
        self.store.publish(snapshot, [result(), result('AMD', 'BEARISH'), ScanResult('EMPTY')],
                           {'NVDA': 'Technology', 'AMD': 'Technology'})
        return snapshot

    def mock_import(self, tokens=None):
        patches = {
            'extract_image_tokens': tokens if tokens is not None else [OCRToken('NVDA', 99), OCRToken('MFTA', 99)],
            'load_config': Config('secret-api-key', 'secret-api-secret', ()),
            'asset_directory_uses_paper': True,
            'fetch_active_symbols': {'NVDA'},
        }
        mocks = {}
        for name, value in patches.items():
            patcher = patch(f'backend.service.{name}', return_value=value)
            mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        return mocks

    def upload(self, filename='watchlist.png', data=None, mime='image/png', **kwargs):
        return self.internal_client.post('/internal/watchlist/upload', files={
            'file': (filename, image_bytes() if data is None else data, mime)}, **kwargs)

    def test_empty_read_endpoints(self):
        for url in ['/api/dashboard', '/api/discovery', '/api/setups/forming', '/api/alerts', '/api/sectors']:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('api_key', response.text)
        dashboard = self.client.get('/api/dashboard').json()
        self.assertEqual(dashboard['counts']['total'], 0)
        self.assertEqual(dashboard['setups'], [])
        self.assertEqual(dashboard['alerts'], [])
        self.assertEqual(self.client.get('/api/symbols/NVDA').status_code, 404)
        self.assertEqual(self.client.get('/api/watchlist').status_code, 404)
        self.assertEqual(self.client.post('/api/watchlist/upload').status_code, 404)

    def test_rules_api_uses_config_and_proposals_never_edit_live_rules(self):
        self.assertEqual(self.client.get('/api/rules').status_code, 404)
        self.assertEqual(self.client.get('/api/internal/strategy-lab/rules').status_code, 404)
        catalog = self.internal_client.get('/api/internal/strategy-lab/rules').json()
        self.assertEqual(catalog['strategy'], 'experimental-forming-v1/b067b3150de3')
        self.assertEqual({rule['status'] for rule in catalog['active_rules']}, {'ACTIVE'})
        self.assertEqual({rule['name'] for rule in catalog['active_rules']}, {
            'Fast EMA direction', 'Slow EMA direction', 'Price versus clouds and VWAP',
            'Directional context', 'Prior move lookback', 'Minimum retrace',
            'Fast cloud proximity', 'Slow cloud structure'})
        proposed = {rule['name']: rule for rule in catalog['proposed_rules']}
        self.assertEqual(set(proposed), {
            'VIX Regime', 'MTF Daily 20/21 Cloud', 'MTF Daily 50/55 Cloud',
            'EMA 5/12 Curl', 'EMA 34/50 Curl', 'First Pullback', 'Watchlist Levels'})
        self.assertEqual({rule['filtering'] for rule in proposed.values()}, {'OFF'})
        self.assertEqual(proposed['VIX Regime']['machine_definition'], 'TBD')
        self.assertEqual(proposed['MTF Daily 20/21 Cloud']['parameters'],
                         {'emas': [20, 21], 'source': 'hl2'})
        self.assertEqual(proposed['MTF Daily 50/55 Cloud']['parameters'],
                         {'emas': [50, 55], 'source': 'hl2'})
        self.assertIn('not currently used by FORMING',
                      proposed['Watchlist Levels']['limitation'])
        before = self.internal_client.get('/internal/rules').json()
        self.assertEqual(before['research_window'], {'start': '08:00', 'end': '10:00',
                                                      'timezone': 'America/Chicago'})
        proximity = next(rule for rule in before['rules'] if rule['name'] == 'Fast cloud proximity')
        self.assertEqual(proximity['value'], 0.004)
        self.assertEqual(proximity['status'], 'EXPERIMENTAL')
        payload = {'name': '5/12 slope confirmation',
                   'description': 'Inspect slope before continuation.',
                   'rationale': 'Might separate stronger pullbacks.',
                   'timeframe': '3m', 'condition': 'Both EMA slopes positive',
                   'threshold_config': 'TBD', 'notes': 'Research only'}
        created = self.internal_client.post('/internal/rules/proposals', json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['status'], 'PROPOSED')
        self.assertEqual(created.json()['rule_version'], 1)
        self.assertEqual(created.json()['strategy_version'], before['strategy_version'])
        after = self.internal_client.get('/internal/rules').json()
        self.assertEqual(after['rules'], before['rules'])
        self.assertEqual(after['proposals'][0]['name'], payload['name'])
        self.assertEqual(self.internal_client.put(f"/internal/rules/proposals/{created.json()['id']}",
                                         json={'status': 'ACTIVE'}).status_code, 404)
        self.assertEqual(self.internal_client.get('/internal/rules').json()['proposals'][0]['status'], 'PROPOSED')

    def test_research_api_filters_and_detail(self):
        self.seed()
        self.assertEqual(self.client.get('/api/research/observations').status_code, 404)
        all_rows = self.internal_client.get('/internal/research/observations').json()['items']
        self.assertEqual(len(all_rows), 3)
        self.assertEqual(len(self.internal_client.get('/internal/research/observations?forming=false').json()['items']), 3)
        self.assertEqual(len(self.internal_client.get('/internal/research/observations?symbol=nvda').json()['items']), 1)
        date = all_rows[0]['trading_date']
        self.assertEqual(len(self.internal_client.get(f'/internal/research/observations?date={date}').json()['items']), 3)
        self.assertEqual(self.internal_client.get('/internal/research/observations?date=bad').status_code, 422)
        detail = self.internal_client.get(f"/internal/research/observations/{all_rows[0]['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['candles_3m'], [])
        self.assertEqual(self.internal_client.get('/internal/research/observations/999999').status_code, 404)

    def test_health_and_database_outage_are_secret_safe(self):
        self.assertEqual(self.client.get('/health').json()['database'], 'connected')
        with patch.object(self.store, 'ping', side_effect=RuntimeError('secret password')):
            response = self.client.get('/health')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['database'], 'unavailable')
        self.assertNotIn('secret', response.text)

    def test_public_boundary_validates_and_sanitizes(self):
        self.seed()
        body = self.client.get('/api/dashboard').json()
        payload = str(body)
        for forbidden in ('UPLOADED_WATCHLIST', 'sources', 'strategy_version',
                          'threshold', 'api_key', 'secret', 'last_error', 'latest_upload'):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(self.client.get('/api/rules').status_code, 404)
        self.assertEqual(self.client.get('/api/research/observations').status_code, 404)
        self.assertEqual(self.client.get('/internal/rules').status_code, 404)
        self.assertEqual(self.client.post('/api/watchlist/upload').status_code, 404)
        self.assertEqual(self.client.get('/api/symbols/invalid!').status_code, 422)
        self.assertEqual(self.client.get('/api/symbols/NVDA/chart?timeframe=1m').status_code, 422)
        self.assertEqual(self.client.get('/api/sectors/' + 'X' * 81).status_code, 422)
        headers = self.client.get('/api/dashboard').headers
        self.assertEqual(headers['x-content-type-options'], 'nosniff')
        self.assertEqual(headers['x-frame-options'], 'DENY')
        with patch.object(self.store, 'read', side_effect=RuntimeError('secret-api-key /private/path')):
            failure = self.client.get('/api/dashboard')
        self.assertEqual(failure.status_code, 500)
        self.assertNotIn('secret-api-key', failure.text)
        self.assertNotIn('/private/path', failure.text)

    def test_rate_limit_and_cors_configuration(self):
        with patch.dict('os.environ', {'PUBLIC_RATE_LIMIT_PER_MINUTE': '2',
                                       'CORS_ALLOWED_ORIGINS': 'https://scanner.example'}):
            client = TestClient(create_app(store=self.store), base_url='http://localhost')
            self.assertEqual(client.get('/api/dashboard').status_code, 200)
            self.assertEqual(client.get('/api/dashboard').status_code, 200)
            limited = client.get('/api/dashboard')
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.headers['retry-after'], '60')
            allowed = client.get('/health', headers={'Origin': 'https://scanner.example'})
            self.assertEqual(allowed.headers.get('access-control-allow-origin'), 'https://scanner.example')
            rejected = client.get('/health', headers={'Origin': 'https://evil.example'})
            self.assertNotIn('access-control-allow-origin', rejected.headers)
        with patch.dict('os.environ', {'CORS_ALLOWED_ORIGINS': '*'}):
            with self.assertRaises(ValueError):
                create_app(store=self.store)
        with patch.dict('os.environ', {'TRUSTED_HOSTS': '*'}):
            with self.assertRaises(ValueError):
                create_app(store=self.store)

    def test_persisted_counts_no_data_and_sector_drilldown(self):
        self.seed()
        dashboard = self.client.get('/api/dashboard').json()
        self.assertEqual({key: dashboard['counts'][key] for key in
            ('total', 'bullish', 'bearish', 'mixed', 'no_data', 'developing', 'pending')},
            {'total': 3, 'bullish': 1, 'bearish': 1, 'mixed': 0,
             'no_data': 1, 'developing': 0, 'pending': 0})
        sectors = self.client.get('/api/sectors').json()['items']
        self.assertEqual(sectors[0]['symbols'], ['NVDA', 'AMD'])
        self.assertNotIn('average_volatility', sectors[0])
        self.assertNotIn('relative_strength', sectors[0])
        self.assertEqual(self.client.get('/api/symbols/nvda').json()['latest_price'], 125)
        self.assertEqual(len(Store(self.store.engine).read()['watchlist']), 3)
        with self.store.session() as session:
            saved = session.scalar(select(ScanResultModel).where(ScanResultModel.symbol == 'NVDA'))
            self.assertEqual((saved.ema_5, saved.ema_12, saved.ema_34, saved.ema_50), (120, 119, 118, 117))

    def test_symbol_detail_and_chart_use_persisted_scan_candles(self):
        snapshot = self.store.snapshot(('NVDA',))
        self.store.activate(snapshot)
        candle = {'timestamp': '2026-09-17T10:00:00-04:00', 'open': 123.0,
                  'high': 126.0, 'low': 122.0, 'close': 125.0, 'volume': 1000.0,
                  'ema_5': 120.0, 'ema_12': 119.0, 'ema_34': 118.0,
                  'ema_50': 117.0, 'vwap': 121.0}
        observed = replace(result(), forming=FormingResult(
            SetupState.FORMING_LONG, 'test pullback', 0),
            candles_10m=[candle], candles_3m=[candle],
            forming_candle_at=candle['timestamp'])
        self.store.publish(snapshot, [observed])
        detail = self.client.get('/api/symbols/nvda')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['setup_state'], 'FORMING_LONG')
        self.assertNotIn('first_candle_at', detail.json())
        public_candle = {key: candle[key] for key in ('timestamp', 'open', 'high', 'low', 'close', 'volume')}
        self.assertEqual(detail.json()['candles_10m'], [public_candle])
        self.assertEqual(detail.json()['candles_3m'], [public_candle])
        chart = self.client.get('/api/symbols/NVDA/chart?timeframe=3m')
        self.assertEqual(chart.status_code, 200)
        self.assertEqual(chart.json()['candles'], [public_candle])
        self.assertEqual(chart.json()['scanned_at'], detail.json()['scanned_at'])

    def test_symbol_chart_invalid_symbol_and_missing_candles(self):
        self.seed()
        self.assertEqual(self.client.get('/api/symbols/UNKNOWN').status_code, 404)
        self.assertEqual(self.client.get('/api/symbols/UNKNOWN/chart?timeframe=3m').status_code, 404)
        self.assertEqual(self.client.get('/api/symbols/NVDA/chart?timeframe=1m').status_code, 422)
        empty = self.client.get('/api/symbols/EMPTY').json()
        self.assertEqual(empty['context_10m'], 'NO DATA')
        self.assertEqual(empty['candles_10m'], [])
        self.assertEqual(self.client.get('/api/symbols/EMPTY/chart?timeframe=10m').json()['candles'], [])

    def test_stored_setups_and_alerts_are_returned_without_generating_any(self):
        snapshot = self.seed()
        with self.store.session() as session:
            session.add(FormingSetup(snapshot_id=snapshot, symbol='NVDA', context_10m='BULLISH',
                setup_state='external state', reason='fixture only', distance_status='unknown', detected_at=now(), active=True))
            session.add(Alert(symbol='NVDA', alert_type='fixture', reason='stored only', created_at=now()))
        self.assertNotIn('reason', self.client.get('/api/setups/forming').json()['items'][0])
        self.assertEqual(self.client.get('/api/alerts').json()['items'][0]['alert_type'], 'fixture')
        self.assertEqual(self.client.get('/api/dashboard').json()['counts']['developing'], 1)

    def test_upload_persists_and_queues_only_valid_symbols(self):
        self.mock_import()
        response = self.upload(filename='../../escape.png')
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body['candidate_count'], 2)
        self.assertEqual(body['validated_symbols'], ['NVDA'])
        self.assertEqual(body['rejected'], ['MFTA'])
        self.assertFalse(body['scan_started'])
        self.assertFalse(body['scan_completed'])
        self.assertEqual(body['status'], 'queued')
        saved = list(Path(self.temp.name).glob('uploads/*/*.png'))
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(saved[0].stem), 32)
        self.assertNotEqual(saved[0].name, 'escape.png')
        with Image.open(saved[0]) as image:
            image.verify()
        watchlist = self.store.read()['watchlist']
        self.assertEqual(watchlist[0]['symbol'], 'NVDA')
        self.assertEqual(watchlist[0]['context_10m'], 'PENDING')
        self.assertNotIn('secret-api', response.text)
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchlistSymbol)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(ScanResultModel)), 0)

    def test_strategy_lab_watchlist_review_then_activation_preserves_each_upload(self):
        mocks = self.mock_import(tokens=[OCRToken('NVDA', 99), OCRToken('AMD', 98)])
        mocks['fetch_active_symbols'].return_value = {'NVDA', 'AMD'}
        staged = self.internal_client.post('/api/internal/strategy-lab/watchlist/upload', files={
            'file': ('daily.png', image_bytes(), 'image/png')})
        self.assertEqual(staged.status_code, 202, staged.text)
        report = staged.json()
        self.assertEqual(report, {'snapshot_id': report['snapshot_id'], 'status': 'processing'})
        self.assertEqual(self.internal_client.get(
            f"/api/internal/strategy-lab/watchlist/uploads/{report['snapshot_id']}"
        ).json()['status'], 'processing')
        self.assertTrue(WatchlistProcessor(self.store).process_once())
        report = self.internal_client.get(
            f"/api/internal/strategy-lab/watchlist/uploads/{report['snapshot_id']}"
        ).json()
        self.assertEqual(report['status'], 'ready_for_review')
        self.assertEqual(report['validated_symbols'], ['NVDA', 'AMD'])
        self.assertIsNone(self.store.today_active_uploaded_snapshot())

        activated = self.internal_client.post('/api/internal/strategy-lab/watchlist/activate',
            json={'snapshot_id': report['snapshot_id']})
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(activated.json()['active']['symbols'], ['NVDA', 'AMD'])
        self.assertIn('next normal cycle', activated.json()['message'])
        first_upload_id = report['snapshot_id']

        replacement = self.internal_client.post('/api/internal/strategy-lab/watchlist/upload', files={
            'file': ('later.png', image_bytes(), 'image/png')})
        self.assertEqual(replacement.status_code, 202)
        second = replacement.json()
        self.assertTrue(WatchlistProcessor(self.store).process_once())
        self.assertEqual(self.store.today_active_uploaded_snapshot()['id'], first_upload_id)
        self.assertEqual(self.internal_client.post('/api/internal/strategy-lab/watchlist/activate',
            json={'snapshot_id': second['snapshot_id']}).status_code, 200)
        with self.store.session() as session:
            first = session.get(WatchlistSymbol, 1)
            self.assertEqual(first.watchlist_upload_id, first_upload_id)
            self.assertEqual(first.symbol, 'NVDA')
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchlistSymbol)), 4)

        active = self.internal_client.get('/api/internal/strategy-lab/watchlist/today').json()['active']
        self.assertEqual(active['symbols'], ['NVDA', 'AMD'])
        # Current OCR/import response exposes validated symbols, not note associations.
        self.assertEqual(report['validated_symbols'], ['NVDA', 'AMD'])

    def test_staged_upload_is_durable_and_processor_recovery_is_idempotent(self):
        mocks = self.mock_import(tokens=[OCRToken('NVDA', 99)])
        staged = self.internal_client.post('/api/internal/strategy-lab/watchlist/upload', files={
            'file': ('daily.png', image_bytes(), 'image/png')})
        self.assertEqual(staged.status_code, 202)
        snapshot_id = staged.json()['snapshot_id']
        mocks['extract_image_tokens'].assert_not_called()
        first = self.store.claim_processing_upload()
        self.assertEqual(first['id'], snapshot_id)
        self.assertIsNone(self.store.claim_processing_upload())
        # A restart can recover an expired claim, while a completed upload cannot.
        with self.store.session() as session:
            upload = session.get(WatchlistUpload, snapshot_id)
            upload.processing_claimed_at = upload.processing_claimed_at - timedelta(minutes=11)
        self.assertTrue(WatchlistProcessor(self.store).process_once())
        ready = self.internal_client.get(
            f'/api/internal/strategy-lab/watchlist/uploads/{snapshot_id}')
        self.assertEqual(ready.json()['status'], 'ready_for_review')
        self.assertFalse(WatchlistProcessor(self.store).process_once())

    def test_staged_upload_failure_is_persisted_and_sanitized(self):
        self.mock_import()
        snapshot = self.internal_client.post('/api/internal/strategy-lab/watchlist/upload', files={
            'file': ('daily.png', image_bytes(), 'image/png')}).json()
        with patch('backend.service.fetch_active_symbols', side_effect=RuntimeError('secret-provider-detail')):
            self.assertTrue(WatchlistProcessor(self.store).process_once())
        response = self.internal_client.get(
            f"/api/internal/strategy-lab/watchlist/uploads/{snapshot['snapshot_id']}")
        self.assertEqual(response.json()['status'], 'failed')
        self.assertIn('Watchlist processing failed', response.json()['error'])
        self.assertNotIn('secret-provider-detail', response.text)

    def test_daily_watchlist_remains_private(self):
        self.assertEqual(self.client.get('/api/internal/strategy-lab/watchlist/today').status_code, 404)
        self.assertEqual(self.client.get('/api/internal/strategy-lab/watchlist/uploads/1').status_code, 404)
        self.assertEqual(self.client.post('/api/internal/strategy-lab/watchlist/upload').status_code, 404)
        self.assertEqual(self.client.post('/api/internal/strategy-lab/watchlist/activate',
            json={'snapshot_id': 1}).status_code, 404)
        self.assertEqual(self.client.get('/api/watchlist').status_code, 404)

    @unittest.skipUnless(shutil.which('tesseract'), 'Tesseract integration runs in the Docker image')
    def test_real_ocr_upload_then_worker_scan(self):
        from scanner.worker import ScannerWorker
        from test_watchlist import bars
        picture = Image.new('RGB', (700, 400), 'white')
        ImageDraw.Draw(picture).text((40, 30), 'NVDA\nAMD\nTSLA', fill='black',
                                    font=ImageFont.load_default(size=64), spacing=20)
        stream = BytesIO()
        picture.save(stream, format='PNG')
        with patch('backend.service.load_config', return_value=Config('fake', 'fake', ())), \
             patch('backend.service.fetch_active_symbols', return_value={'NVDA', 'AMD', 'TSLA'}), \
             patch('backend.service.asset_directory_uses_paper', return_value=True):
            response = self.upload(data=stream.getvalue())
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()['validated_symbols'], ['NVDA', 'AMD', 'TSLA'])
        self.assertTrue(all(r['context_10m'] == 'PENDING' for r in self.store.read()['watchlist']))
        with patch('scanner.worker.load_config', side_effect=lambda *, symbols: Config('fake', 'fake', symbols)), \
             patch('scanner.worker.StockHistoricalDataClient'), \
             patch('ripster_scanner.provider.fetch_one_minute_bars', return_value=bars()):
            self.assertEqual(ScannerWorker(self.store).run_once(), 'scanned')
        self.assertTrue(all(r['context_10m'] == 'BULLISH' for r in self.store.read()['watchlist']))

    def test_rejected_import_retains_previous_scan_and_rejections(self):
        self.seed()
        self.mock_import(tokens=[OCRToken('MFTA', 99)])
        response = self.upload()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail']['report']['validated_count'], 0)
        self.assertEqual(self.client.get('/api/dashboard').json()['counts']['total'], 3)
        self.assertEqual(self.store.latest_upload()['rejected'][0]['candidate'], 'MFTA')

    def test_validation_failure_retains_previous_watchlist_and_is_secret_safe(self):
        self.seed()
        mocks = self.mock_import()
        mocks['fetch_active_symbols'].side_effect = RuntimeError('secret-api-key in a provider error')
        response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('secret-api-key', response.text)
        self.assertEqual(len(self.store.read()['watchlist']), 3)
        self.assertEqual(self.store.latest_upload()['status'], 'failed')

    def test_ocr_failure_records_latest_filename(self):
        mocks = self.mock_import()
        mocks['extract_image_tokens'].side_effect = ValueError('private backend path')
        response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('private backend path', response.text)
        self.assertEqual(self.store.latest_upload()['filename'], 'watchlist.png')
        self.assertEqual(self.store.latest_upload()['status'], 'failed')

    def test_watchlist_import_logs_stage_timings_without_payloads(self):
        self.mock_import(tokens=[OCRToken('NVDA', 99)])
        with self.assertLogs('backend.service', level='INFO') as captured:
            response = self.upload()
        self.assertEqual(response.status_code, 202)
        output = '\n'.join(captured.output)
        for stage in ('started', 'snapshot_created', 'ocr_started', 'ocr_completed',
                      'provider_directory_started', 'provider_directory_completed',
                      'candidate_validation_completed', 'database_update_completed',
                      'completed'):
            self.assertIn(f'stage={stage}', output)
        self.assertIn('token_count=1', output)
        self.assertIn('validated_count=1', output)
        self.assertNotIn('secret-api', output)

    def test_unsupported_spoofed_and_oversized_uploads(self):
        for filename, data, mime, status in [
            ('evil.svg', b'<svg/>', 'image/svg+xml', 415),
            ('fake.png', b'not an image', 'image/png', 415),
            ('wrong.jpg', image_bytes(), 'image/jpeg', 415),
            ('wrong.png', image_bytes(), 'application/octet-stream', 415),
            ('large.png', b'x' * (MAX_UPLOAD + 1), 'image/png', 413),
            ('larger.png', b'x' * (MAX_UPLOAD + 100000), 'image/png', 413),
        ]:
            with self.subTest(filename=filename):
                self.assertEqual(self.upload(filename, data, mime).status_code, status)
        self.assertEqual(list(Path(self.temp.name).glob('uploads/*/*')), [])

    def test_pixel_limit_and_jpeg(self):
        self.mock_import()
        with patch('backend.uploads.MAX_PIXELS', 100):
            self.assertEqual(self.upload().status_code, 415)
        self.assertEqual(self.upload('watchlist.JPEG', image_bytes('JPEG'), 'image/jpeg').status_code, 202)

    def test_duplicate_and_cross_origin_requests_are_rejected(self):
        with self.store.claim_lock('upload') as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.upload(headers={'Origin': 'https://untrusted.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/dashboard', headers={'Host': 'untrusted.example'}).status_code, 400)
        self.assertEqual(self.client.post('/api/alerts', json={}).status_code, 405)
        self.assertEqual(self.internal_client.post('/internal/watchlist/upload').status_code, 422)

    def test_nan_price_serializes_as_null(self):
        snapshot = self.store.snapshot(('NVDA',))
        self.store.activate(snapshot)
        self.store.publish(snapshot, [result(price=float('nan'))])
        self.assertIsNone(self.client.get('/api/symbols/NVDA').json()['latest_price'])

    def test_partial_publication_rolls_back_all_rows(self):
        snapshot = self.seed()
        before = self.store.read()
        with self.assertRaises(ValueError):
            self.store.publish(snapshot, [result('NEW'), result('BAD', price='invalid')])
        after = self.store.read()
        self.assertEqual(before['watchlist'], after['watchlist'])
        self.assertEqual(before['sectors'], after['sectors'])

    def test_old_scan_cannot_replace_new_active_watchlist(self):
        old = self.seed()
        new = self.store.snapshot(('NEW',))
        self.store.activate(new)
        self.assertFalse(self.store.publish(old, [result()]))
        self.assertEqual(self.store.read()['watchlist'][0]['symbol'], 'NEW')
        self.assertEqual(self.store.read()['watchlist'][0]['context_10m'], 'PENDING')


if __name__ == '__main__':
    unittest.main()
