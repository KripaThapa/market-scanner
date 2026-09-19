"""Deterministic experimental forming rules and persistence lifecycle."""
import unittest

import pandas as pd
from sqlalchemy import select

from backend.database.models import FormingSetup
from db_support import test_store
from ripster_scanner.forming import FormingResult, SetupState, detect_forming
from ripster_scanner.scan import ScanResult


def bars(*, bullish=True, pullback=True, slow_valid=True):
    high = 101 if bullish and pullback else 100.1
    low = 99 if not bullish and pullback else 99.9
    rows = [dict(high=high, low=low, close=100, ema_5=100.2,
                 ema_12=99.8, ema_34=98 if bullish else 102,
                 ema_50=97 if bullish else 103) for _ in range(6)]
    rows.append(dict(high=100.2, low=99.8, close=100, ema_5=100.2,
                     ema_12=99.8, ema_34=(102 if bullish else 98) if not slow_valid else (98 if bullish else 102),
                     ema_50=(103 if bullish else 97) if not slow_valid else (97 if bullish else 103)))
    return pd.DataFrame(rows)


class FormingTests(unittest.TestCase):
    def test_bullish_and_bearish_forming(self):
        self.assertEqual(detect_forming('BULLISH', bars()).state, SetupState.FORMING_LONG)
        self.assertEqual(detect_forming('BEARISH', bars(bullish=False)).state, SetupState.FORMING_SHORT)

    def test_no_pullback_wrong_context_and_slow_invalidation(self):
        self.assertEqual(detect_forming('BULLISH', bars(pullback=False)).state, SetupState.NONE)
        self.assertEqual(detect_forming('MIXED', bars()).state, SetupState.NONE)
        self.assertEqual(detect_forming('BULLISH', bars(slow_valid=False)).state, SetupState.NONE)

    def test_missing_data_does_not_form(self):
        self.assertEqual(detect_forming('BULLISH', pd.DataFrame()).state, SetupState.NONE)
        missing = bars()
        missing.loc[6, 'ema_5'] = float('nan')
        self.assertEqual(detect_forming('BULLISH', missing).state, SetupState.NONE)

    def test_record_updates_then_deactivates_without_duplicate(self):
        store = test_store(self)
        snapshot = store.snapshot(('NVDA',))
        store.activate(snapshot)
        ten = {'trend': 'BULLISH', 'close': 100, 'vwap_position': 'ABOVE'}
        three = {'trend': 'MIXED', 'close': 100, 'ema_5': 100.2, 'ema_12': 99.8,
                 'ema_34': 98, 'ema_50': 97, 'vwap_position': 'ABOVE'}
        forming = FormingResult(SetupState.FORMING_LONG, 'test reason', 0)
        result = ScanResult('NVDA', ten, three, forming)
        store.publish(snapshot, [result])
        first = store.read()['setups'][0]
        store.publish(snapshot, [result])
        with store.session() as session:
            self.assertEqual(len(session.scalars(select(FormingSetup)).all()), 1)
        self.assertEqual(store.read()['setups'][0]['first_detected_at'], first['first_detected_at'])
        store.publish(snapshot, [ScanResult('NVDA', ten, three)])
        self.assertEqual(store.read()['setups'], [])
        with store.session() as session:
            history = session.scalars(select(FormingSetup)).all()
            self.assertEqual(len(history), 1)
            self.assertFalse(history[0].active)

    def test_legacy_active_record_is_rebased_with_exact_candle_time(self):
        store = test_store(self)
        snapshot = store.snapshot(('NVDA',))
        store.activate(snapshot)
        ten = {'trend': 'BULLISH', 'close': 100}
        three = {'trend': 'MIXED', 'close': 100}
        forming = FormingResult(SetupState.FORMING_LONG, 'test reason', 0)
        store.publish(snapshot, [ScanResult('NVDA', ten, three, forming)])
        candle_time = '2026-09-17T15:57:00-04:00'
        store.publish(snapshot, [ScanResult('NVDA', ten, three, forming,
                                            forming_candle_at=candle_time)])
        with store.session() as session:
            rows = session.scalars(select(FormingSetup).order_by(FormingSetup.id)).all()
            self.assertEqual(len(rows), 2)
            self.assertFalse(rows[0].active)
            self.assertTrue(rows[1].active)
            self.assertEqual(rows[1].first_candle_at, candle_time)


if __name__ == '__main__':
    unittest.main()
