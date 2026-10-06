"""Lookout V1 semantics, structured table extraction and date-bound read-only API."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
import shutil
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.api import create_app
from backend.database.models import Alert, WatchlistLevelMonitor, WatchlistSymbol
from db_support import test_store
from ripster_scanner.watchlist import ExtractedWatchlistRow, extract_watchlist_rows, validate_watchlist_rows
from ripster_scanner.watchlist_image import OCRToken
from ripster_scanner.watchlist_levels import lookout_instructions, parse_pivots
from scanner.price_observation import PriceObservation

AT = datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc)
PLAN = 'Tenet Swing | 1 HR MTF Setup, No go under 173, Long over 175 holds'


class ExtractionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('tesseract'), 'Real colored-table OCR runs in the isolated Docker test image')
    def test_actual_screenshot_ocr_recovers_colored_support_and_resistance_cells(self):
        from pathlib import Path
        from ripster_scanner.watchlist_image import extract_image_tokens
        image = Path('tests/fixtures/daily-watchlist-2026-09-21.png')
        rows = {r.symbol:r for r in extract_watchlist_rows(extract_image_tokens(image),image_path=image)}
        self.assertEqual(rows['MRVL'].structured_fields['support_pivots'], ['249.00000000'])
        self.assertEqual(rows['MRVL'].structured_fields['resistance_pivots'], ['252.40000000'])
        self.assertEqual(rows['NFLX'].structured_fields['resistance_pivots'], ['72.00000000','72.20000000'])
        self.assertIn('Long over 72', rows['NFLX'].structured_fields['game_plan'])
        for symbol in ('SPY','QQQ'):
            self.assertEqual(rows[symbol].structured_fields['support_pivots'], [])
            self.assertEqual(rows[symbol].structured_fields['resistance_pivots'], [])

    def test_real_fixture_geometry_blank_symbol_header_and_colored_pivots(self):
        import json
        from pathlib import Path
        from dataclasses import replace
        cache = json.loads(Path('tests/fixtures/watchlist-column-ocr.json').read_text())
        sparse = [OCRToken(**t) for t in cache['sparse']]
        header = [OCRToken(**t) for t in cache['header']]
        # Header pass replaces only the original header band.
        tokens = [t for t in sparse if not 205 <= t.center_y < 331] + header
        pivots = [OCRToken(**t) for t in cache['pivots']]
        image = Path('tests/fixtures/daily-watchlist-2026-09-21.png')
        with patch('ripster_scanner.watchlist_table.extract_pivot_tokens', return_value=pivots):
            rows = {r.symbol:r for r in extract_watchlist_rows(tokens,image_path=image)}
        self.assertEqual(rows['MRVL'].structured_fields['resistance_pivots'], ['252.40000000'])
        self.assertEqual(rows['TSLA'].structured_fields['support_pivots'], ['369.00000000','366.00000000'])
        self.assertEqual(rows['NFLX'].structured_fields['resistance_pivots'], ['72.00000000','72.20000000'])
        plan = rows['COIN'].structured_fields['game_plan']
        self.assertEqual(plan, '200 Psych Setup breakout, Bullish bias to long over 200, Short under 198')
        self.assertEqual([x['semantic'] for x in lookout_instructions(rows['COIN'].structured_fields)],
                         ['SUPPORT','RESISTANCE','LONG','SHORT'])
        self.assertIsNone(rows['TSLA'].structured_fields['mtf'])  # Uncertain heading stays unknown.
        with patch('ripster_scanner.watchlist_table.extract_pivot_tokens', return_value=pivots):
            shifted = extract_watchlist_rows([replace(t,left=t.left+10) for t in tokens],image_path=image)
        self.assertTrue(shifted)  # Optional geometry uncertainty never loses valid symbol extraction.

    def test_multiple_canonical_pivots_and_malformed_cells(self):
        for text, expected in [('518/520', [518, 520]), ('177/175', [177, 175]),
                               ('477/475', [477, 475]), ('726.2/725', [726.2, 725]),
                               ('81.6/81.40', [81.6, 81.4]), ('186.14/188', [186.14, 188]),
                               ('81.40/81.400', [81.4])]:
            self.assertEqual([float(x) for x in parse_pivots(text)], expected)
        for text in ('support 518', '518/garbage', '518-520', '0', 'NaN', '1.123456789'):
            self.assertEqual(parse_pivots(text), ())

    def test_literal_direction_warning_and_no_vague_inference(self):
        fields = {'columns_detected': True, 'support_pivots': ['173'],
                  'resistance_pivots': ['177', '175'], 'game_plan': PLAN}
        items = lookout_instructions(fields)
        self.assertEqual([(x['semantic'], float(x['trigger_level'])) for x in items],
                         [('SUPPORT', 173), ('RESISTANCE', 177), ('RESISTANCE', 175), ('LONG', 175), ('NO_GO', 173)])
        self.assertNotIn('SHORT', [x['semantic'] for x in items])
        for plan in ('Long above 500; Short below 10.95', 'Long over 500; Short under 10.95'):
            self.assertEqual([x['semantic'] for x in lookout_instructions({'columns_detected':True,'game_plan':plan})], ['LONG','SHORT'])
        for plan in ('Bullish bias with Software', 'bearish bias; 5/12 curl; 34/50 curl; PMH PML MTF gap & go',
                     'Long over PMH; Short the POPs vs 42'):
            self.assertEqual(lookout_instructions({'columns_detected':True, 'game_plan':plan}), [])

    def table(self, *, bad_support=False):
        def token(text, x, y, width=60, confidence=99):
            return OCRToken(text, confidence, x, y, width, 20)
        tokens = [token(text, x, 30) for text,x in [('Symbol',50),('News',170),('Support',315),
                  ('Resistance',480),('MTF',640),('Game',730)]]
        for symbol, y, support, resistance, plan in [('CBRS',120,'173','177/175',PLAN),
                    ('MSFT',220,'518/520','522','Bullish bias with Software')]:
            tokens.extend([token(symbol,50,y), token('News text',170,y,width=100),
                token(support,315,y,width=100,confidence=40 if bad_support and symbol=='CBRS' else 99),
                token(resistance,480,y,width=100), token('Yes',640,y,width=40),
                token(plan,730,y,width=700)])
        return tokens

    def test_header_geometry_separates_source_columns(self):
        imported = validate_watchlist_rows(extract_watchlist_rows(self.table()), {'CBRS','MSFT'})
        self.assertEqual(imported.validated, ('CBRS','MSFT'))
        cbrs, msft = imported.rows
        self.assertEqual(cbrs.structured_fields['support_pivots'], ['173.00000000'])
        self.assertEqual(cbrs.structured_fields['resistance_pivots'], ['177.00000000','175.00000000'])
        self.assertEqual(cbrs.structured_fields['game_plan'], PLAN)
        self.assertTrue(cbrs.structured_fields['mtf'])
        self.assertEqual(msft.structured_fields['support_pivots'], ['518.00000000','520.00000000'])
        self.assertEqual(msft.structured_fields['resistance_pivots'], ['522.00000000'])
        self.assertIn('News text', msft.original_note)

    def test_low_confidence_optional_cell_does_not_reject_stock_or_other_levels(self):
        imported = validate_watchlist_rows(extract_watchlist_rows(self.table(bad_support=True)), {'CBRS','MSFT'})
        self.assertEqual(len(imported.validated), 2)
        fields = imported.rows[0].structured_fields
        self.assertEqual(fields['support_pivots'], [])
        self.assertTrue(fields['review_warnings'])
        self.assertIn('LONG', [x['semantic'] for x in lookout_instructions(fields)])
        fields['game_plan_reliable'] = False
        self.assertNotIn('LONG', [x['semantic'] for x in lookout_instructions(fields)])

    def test_missing_headers_retains_note_without_invented_pivot_columns(self):
        rows = extract_watchlist_rows(self.table()[6:])
        self.assertFalse(rows[0].structured_fields['columns_detected'])
        self.assertEqual(rows[0].structured_fields['support_pivots'], [])
        self.assertIn(PLAN, rows[0].original_note)


class LookoutTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.minute = 0
        self.upload({'columns_detected':True, 'support_pivots':['173'],
            'resistance_pivots':['177','175'], 'game_plan':PLAN})

    def upload(self, fields, at=AT):
        row = ExtractedWatchlistRow('CBRS', PLAN, 99, (0,0,100,20), structured_fields=fields)
        with patch('backend.store.now', return_value=at):
            self.snapshot = self.store.snapshot((), source='image')
            self.store.update_import(self.snapshot, validate_watchlist_rows((row,), {'CBRS'}))
            self.store.activate(self.snapshot)

    def observe(self, price, at=None):
        self.minute += 1
        at = at or AT + timedelta(minutes=self.minute)
        with patch('backend.store.now', return_value=at):
            self.store.publish(self.snapshot, [], price_observations={'CBRS':PriceObservation(Decimal(str(price)), at, at)})

    def events(self, day='2026-10-05', category='ALL'):
        return self.store.lookout_alerts(day, category)['items']

    def test_generic_first_touch_and_cross_multiple_semantics_dedup(self):
        self.observe(173)  # Exact first touch allowed for support.
        self.observe(175)  # Resistance exact touch, LONG equality is not crossing.
        self.assertEqual([x['level_type'] for x in self.events()], ['RESISTANCE','SUPPORT'])
        self.observe(176)
        self.observe(178)
        self.observe(172)
        self.assertEqual({x['level_type'] for x in self.events()}, {'LONG','NO_GO','SUPPORT','RESISTANCE'})
        self.assertEqual(len(self.events()), 5)
        self.observe(178)
        self.observe(172)
        self.assertEqual(len(self.events()), 5)
        self.assertEqual(self.events(category='LONG')[0]['game_plan'], PLAN)
        self.assertTrue(all(x['direction']=='LEVEL' for x in self.events(category='LEVEL')))
        self.assertEqual(self.events(category='SHORT'), [])

    def test_generic_cross_both_directions_and_first_beyond_is_not_alert(self):
        self.upload({'columns_detected':True,'support_pivots':['100'], 'resistance_pivots':['105']})
        self.observe(110)
        self.observe(111)
        self.assertEqual(self.events(), [])
        self.observe(99)
        self.assertEqual(len(self.events()), 2)
        self.observe(111)
        self.assertEqual(len(self.events()), 2)

    def test_generic_upward_cross_without_exact_touch(self):
        self.upload({'columns_detected':True,'support_pivots':['100']})
        self.observe(99)
        self.observe(101)
        self.assertEqual(self.events()[0]['level_type'], 'SUPPORT')
        self.observe(111)
        self.assertEqual(len(self.events()), 1)

    def test_long_short_and_no_go_strict_equality(self):
        self.upload({'columns_detected':True,'game_plan':'Long above 175; Short below 175; No go under 173'})
        self.observe(175)
        self.assertEqual(self.events(), [])
        self.observe(176)
        self.observe(175)
        self.assertEqual(len(self.events()), 1)
        self.observe(174)
        self.observe(173)
        self.assertEqual(len(self.events()), 2)
        self.observe(172)
        self.assertEqual([x['level_type'] for x in self.events()], ['NO_GO','SHORT','LONG'])
        self.assertEqual(len(self.events(category='SHORT')), 1)
        self.assertEqual(len(self.events(category='LEVEL')), 1)

    def test_refresh_restart_remove_readd_never_rearms_triggered_levels(self):
        fields = {'columns_detected':True,'support_pivots':['173','173.00'],'game_plan':PLAN}
        self.upload(fields)
        self.observe(173)
        before = self.events()
        from backend.store import Store
        self.store = Store(self.store.engine)
        self.upload({'columns_detected':True}, AT+timedelta(minutes=2))
        self.upload(fields, AT+timedelta(minutes=3))
        self.observe(173, AT+timedelta(minutes=4))
        self.assertEqual(self.events(), before)
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchlistLevelMonitor).where(
                WatchlistLevelMonitor.semantic=='SUPPORT')), 1)

    def test_previous_day_no_carry_and_exact_date_filter(self):
        self.observe(173)
        self.observe(180, AT+timedelta(days=1))
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.events('2026-10-06'), [])
        self.upload({'columns_detected':True,'support_pivots':['173']}, AT+timedelta(days=1,minutes=1))
        self.observe(173, AT+timedelta(days=1,minutes=2))
        self.assertEqual(len(self.events('2026-10-06')), 1)
        self.assertEqual(len(self.events()), 1)

    def test_api_filters_original_plan_privacy_readonly_and_forming_exclusion(self):
        self.observe(173)
        self.observe(180)
        self.observe(172)
        with self.store.session() as session:
            session.add(Alert(symbol='CBRS', alert_type='FORMING_LONG', created_at=AT, reason='private detector detail'))
            before = session.scalar(select(func.count()).select_from(Alert))
        with TestClient(create_app(store=self.store), base_url='http://localhost') as client:
            for category in ('ALL','LONG','SHORT','LEVEL'):
                response = client.get('/api/alerts', params={'trading_date':'2026-10-05','category':category})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['items'], self.events(category=category))
                for secret in ('source_watchlist_id','source_bbox','original_note','watchlist_details','provider','private detector'):
                    self.assertNotIn(secret, response.text)
            self.assertTrue(all(row['alert_type']!='FORMING_LONG' for row in client.get('/api/alerts?trading_date=2026-10-05').json()['items']))
            self.assertEqual(client.get('/api/alerts?trading_date=2026-10-04').json()['items'], [])
            for query in ('trading_date=garbage','trading_date=2026-02-30','category=BUY','limit=201','before_id=0'):
                self.assertEqual(client.get('/api/alerts?'+query).status_code,422)
            first = client.get('/api/alerts?trading_date=2026-10-05&limit=2').json()
            second = client.get('/api/alerts',params={'trading_date':'2026-10-05','before_id':first['next_before_id']}).json()
            self.assertFalse({x['id'] for x in first['items']} & {x['id'] for x in second['items']})
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Alert)), before)
            symbol = session.scalar(select(WatchlistSymbol).where(WatchlistSymbol.watchlist_upload_id==self.snapshot))
            self.assertEqual(symbol.structured_rows[0]['game_plan'], PLAN)

    def test_legacy_date_evidence_query_without_backfill(self):
        with self.store.session() as session:
            session.add(Alert(symbol='CBRS',alert_type='WATCHLIST_LEVEL_LONG',created_at=AT,
                level_key='legacy-key',snapshot={'trading_date':'2026-10-05','direction':'LONG',
                'price':175.12,'trigger_level':'175','original_note':'private raw row'}))
        row = self.events()[0]
        self.assertEqual(row['trading_date'],'2026-10-05')
        self.assertIsNone(row['game_plan'])
        with self.store.session() as session:
            self.assertIsNone(session.scalar(select(Alert)).trading_date)
