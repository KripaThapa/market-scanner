"""Physical table extraction regressions; no strategy/alert semantics changes."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.database.models import WatchlistSymbol, WatchlistLevelMonitor
from backend.internal_api import create_internal_app
from db_support import test_store
from ripster_scanner.watchlist import extract_watchlist_rows, validate_watchlist_rows
from ripster_scanner.watchlist_image import OCRToken, extract_image_tokens
from ripster_scanner.watchlist_table import column_boundaries, extract_cells, image_column_boundaries


def token(text, x, y, width=60, confidence=99):
    return OCRToken(text, confidence, x, y, width, 20)


def table():
    result = [token(name,x,30) for name,x in [('Symbol',50),('News',170),
              ('Support',315),('Resistance',480),('MTF',640),('Game',730)]]
    result += [token('Pivot',330,55),token('Pivot',490,55),token('Plan',800,30)]
    for symbol,y,support,resistance in [('CBRS',120,'173','177/175'),('MSFT',260,'518/520','522')]:
        result += [token(symbol,50,y),token('News 999',170,y,120),
                   token(support,315,y,100),token(resistance,480,y,100),
                   token('X',640,y,25),token('Long over 175',730,y,200),
                   token('holds; No go under 173',730,y+40,320)]
    return result


class TableTests(unittest.TestCase):
    def fields(self, tokens=None):
        return {r.symbol:r for r in extract_watchlist_rows(tokens or table())}

    def test_split_headers_and_left_to_right_cells(self):
        fields = self.fields()['CBRS'].structured_fields
        self.assertEqual(fields['news'], 'News 999')
        self.assertEqual(fields['support_pivots'], ['173.00000000'])
        self.assertEqual(fields['resistance_pivots'], ['177.00000000','175.00000000'])
        self.assertEqual(fields['game_plan'], 'Long over 175 holds; No go under 173')
        self.assertTrue(fields['mtf'])

    def test_multiple_support_and_single_resistance(self):
        fields = self.fields()['MSFT'].structured_fields
        self.assertEqual(fields['support_pivots'], ['518.00000000','520.00000000'])
        self.assertEqual(fields['resistance_pivots'], ['522.00000000'])

    def test_wrapped_text_and_raw_notes_do_not_overlap_next_row(self):
        rows = self.fields()
        self.assertIn('holds; No go under 173', rows['CBRS'].original_note)
        self.assertNotIn('518/520', rows['CBRS'].original_note)
        self.assertNotIn('999', rows['CBRS'].structured_fields['support_pivots'])
        self.assertNotIn('173', rows['MSFT'].structured_fields['resistance_pivots'])

    def test_safe_header_variation_requires_pivot_corroboration(self):
        tokens = [replace(t,text='Resistanee') if t.text=='Resistance' else t for t in table()]
        self.assertTrue(column_boundaries(tokens,120))
        self.assertIsNone(column_boundaries([t for t in tokens if t.text!='Pivot'],120))
        tokens = [replace(t,text='Unrelated') if t.text=='Resistanee' else t for t in tokens]
        self.assertIsNone(column_boundaries(tokens,120))

    def test_scaled_geometry(self):
        for scale in (.5, 2):
            tokens = [replace(t,left=int(t.left*scale),top=int(t.top*scale),
                      width=int(t.width*scale),height=int(t.height*scale)) for t in table()]
            self.assertEqual(self.fields(tokens)['MSFT'].structured_fields['support_pivots'],
                             ['518.00000000','520.00000000'])

    def test_blank_news_is_distinct_from_unavailable(self):
        fields = self.fields([t for t in table() if t.text!='News 999'])['CBRS'].structured_fields
        self.assertEqual(fields['news'], '')
        fields = self.fields([t for t in table() if t.top>=120])['CBRS'].structured_fields
        self.assertIsNone(fields['news'])
        self.assertFalse(fields['columns_detected'])

    def test_uncertain_optional_cell_is_isolated(self):
        for name,key in [('News 999','news'),('173','support_pivots'),('X','mtf')]:
            tokens = [replace(t,confidence=40) if t.text==name else t for t in table()]
            row = self.fields(tokens)['CBRS']; fields=row.structured_fields
            self.assertIn(fields[key], (None, []))
            self.assertEqual(fields['resistance_pivots'], ['177.00000000','175.00000000'])
            self.assertIn('Long over 175', fields['game_plan'])
            self.assertTrue(fields['review_warnings'])
            self.assertIn(name,row.original_note)

    def test_uncertain_plan_does_not_erase_other_cells(self):
        fields=self.fields([replace(t,confidence=40) if t.text=='Long over 175' else t
                            for t in table()])['CBRS'].structured_fields
        self.assertIsNone(fields['game_plan'])
        self.assertFalse(fields['game_plan_reliable'])
        self.assertEqual(fields['support_pivots'], ['173.00000000'])

    def test_section_labels_are_not_rows_or_symbols(self):
        tokens=table()+[token('NEWS',50,210),token('TECHNICAL',0,210,150),
                        token('TOP FOCUS',0,210,150),token('UPGRADE/DOWNGRADE',0,210,200)]
        self.assertEqual(tuple(self.fields(tokens)), ('CBRS','MSFT'))
        self.assertEqual(validate_watchlist_rows(extract_watchlist_rows(tokens),
                         {'CBRS','MSFT','NEWS'}).validated, ('CBRS','MSFT'))

    def test_merged_cells_never_supply_partial_game_plan(self):
        fields=extract_cells([token('Long over 175',730,120,200)],
                             [50,170,315,480,640,730], set())
        self.assertIsNone(fields['game_plan'])
        self.assertTrue(fields['review_warnings'])

    def test_missing_ocr_is_not_a_confirmed_blank_cell(self):
        columns=[50,170,315,480,640,730]
        fields=extract_cells([],columns,blank_cells={'news'})
        self.assertEqual(fields['news'],'')
        self.assertIsNone(fields['game_plan'])
        self.assertIsNone(fields['support_cell'])
        self.assertTrue(fields['review_warnings'])

    def test_actual_october_header_confidence_regression(self):
        cache=json.loads(Path('tests/fixtures/watchlist-2026-10-06-ocr.json').read_text())
        sparse=[OCRToken(**t) for t in cache['sparse']]
        header=[OCRToken(**t) for t in cache['header']]
        image=Path('tests/fixtures/daily-watchlist-2026-10-06.png')
        resistance=next(t for t in header if t.text=='Resistance')
        self.assertLess(resistance.confidence,80)
        self.assertIsNone(image_column_boundaries(sparse,375,image))
        detected=image_column_boundaries(header,375,image)
        self.assertEqual(detected['starts'], [0,209,1051.5,1304.5,1567.5,1632.5])
        self.assertFalse(detected['mtf_verified'])
        tokens=[t for t in sparse if not 202<=t.center_y<327]+header
        with patch('ripster_scanner.watchlist_table.extract_pivot_tokens',return_value=[]):
            rows=extract_watchlist_rows(tokens,image_path=image)
        self.assertTrue(all(r.structured_fields['columns_detected'] for r in rows))
        amd=next(r for r in rows if r.symbol=='AMD')
        self.assertIn('Citi maintains Buy',amd.structured_fields['news'])
        self.assertNotIn('GPU financing', next(r for r in rows if r.symbol=='RKLB').original_note)

    @unittest.skipUnless(shutil.which('tesseract'),'Real OCR requires project Docker test image')
    def test_actual_october_end_to_end(self):
        image=Path('tests/fixtures/daily-watchlist-2026-10-06.png')
        rows={r.symbol:r for r in extract_watchlist_rows(extract_image_tokens(image),image_path=image)}
        self.assertEqual(rows['MSFT'].structured_fields['support_pivots'],['529.00000000','528.00000000'])
        self.assertEqual(rows['MSFT'].structured_fields['resistance_pivots'],['531.00000000'])
        self.assertEqual(rows['AMD'].structured_fields['resistance_pivots'],['646.50000000','647.00000000'])
        self.assertIn('Citi maintains Buy',rows['AMD'].structured_fields['news'])
        self.assertIsNone(rows['SPY'].structured_fields['game_plan'])
        self.assertEqual(rows['SPY'].structured_fields['support_pivots'],[])

    def test_structured_rows_persist_and_private_review_returns_fields_without_activation(self):
        store=test_store(self)
        snapshot=store.snapshot((),source='image')
        imported=validate_watchlist_rows(extract_watchlist_rows(table()),{'CBRS','MSFT'})
        store.update_import(snapshot,imported)
        with store.session() as session:
            symbol=session.scalar(select(WatchlistSymbol).where(WatchlistSymbol.symbol=='CBRS'))
            self.assertEqual(symbol.structured_rows[0]['news'],'News 999')
            self.assertEqual(symbol.structured_rows[0]['support_pivots'],['173.00000000'])
            self.assertEqual(session.scalars(select(WatchlistLevelMonitor)).all(),[])
        with TestClient(create_internal_app(store=store),base_url='http://localhost') as client:
            response=client.get(f'/api/internal/strategy-lab/watchlist/uploads/{snapshot}')
            self.assertEqual(response.status_code,200)
            row=response.json()['validated_rows'][0]
            self.assertEqual(row['structured_rows'][0]['game_plan'],'Long over 175 holds; No go under 173')
            self.assertIn('999',row['original_note'])
