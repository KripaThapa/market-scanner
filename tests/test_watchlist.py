import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from ripster_scanner.config import Config, load_watchlist
from ripster_scanner.display import print_watchlist_summary
from ripster_scanner.market_data import fetch_one_minute_bars
from ripster_scanner.scan import ScanResult, analyze_symbol, scan_watchlist


def bars(direction=1):
    index = pd.date_range("2026-09-10 09:30", periods=120, freq="min",
                          tz="America/New_York")
    prices = [200 + direction * i for i in range(len(index))]
    return pd.DataFrame({"open": prices, "high": prices, "low": prices,
                         "close": prices, "volume": 100, "trade_count": 5}, index=index)


class WatchlistTests(unittest.TestCase):
    def test_loading_normalizes_and_deduplicates_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.json"
            path.write_text(json.dumps([" nvda ", "AMD", "NvDa", "BRK.B"]))
            self.assertEqual(load_watchlist(path), ("NVDA", "AMD", "BRK.B"))

    def test_invalid_or_missing_watchlists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.json"
            with self.assertRaisesRegex(ValueError, "Cannot load watchlist"):
                load_watchlist(path)
            for content in ['{', '{}', '[]', 'null', '"NVDA"', '[12]', '[""]',
                            '["  "]', '["NV DA"]', '["NVDA", null]']:
                with self.subTest(content=content):
                    path.write_text(content)
                    with self.assertRaises(ValueError):
                        load_watchlist(path)


class ScanTests(unittest.TestCase):
    @patch("ripster_scanner.scan.fetch_one_minute_bars")
    def test_multiple_symbols_are_processed_independently(self, fetch):
        fetch.side_effect = [bars(1), bars(-1), bars(0)]
        client = Mock()
        results = scan_watchlist(Config("fake", "fake", ("UP", "DOWN", "FLAT")), client)
        self.assertEqual([result.symbol for result in results], ["UP", "DOWN", "FLAT"])
        for field in ("analysis_10m", "analysis_3m"):
            self.assertEqual([getattr(result, field)["trend"] for result in results],
                             ["BULLISH", "BEARISH", "MIXED"])
            for result in results:
                self.assertTrue({"ema_5", "ema_12", "ema_34", "ema_50", "vwap"}
                                <= getattr(result, field).keys())
        self.assertEqual([call.args for call in fetch.call_args_list],
                         [(symbol, client, 3) for symbol in ("UP", "DOWN", "FLAT")])
        latest = results[0].candles_10m[-1]
        self.assertEqual(latest['close'], results[0].analysis_10m['close'])
        self.assertAlmostEqual(latest['ema_5'], results[0].analysis_10m['ema_5'])
        self.assertAlmostEqual(latest['vwap'], results[0].analysis_10m['vwap'])
        self.assertTrue(results[0].candles_3m[-1]['timestamp'].endswith('-04:00'))
        self.assertLessEqual(len(results[0].candles_10m), 120)
        self.assertLessEqual(len(results[0].candles_3m), 240)

    @patch("ripster_scanner.scan.fetch_one_minute_bars")
    def test_no_data_between_valid_symbols_does_not_stop_scan(self, fetch):
        fetch.side_effect = [bars(1), pd.DataFrame(), bars(-1)]
        results = scan_watchlist(Config("fake", "fake", ("UP", "MISSING", "DOWN")), Mock())
        self.assertEqual([result.has_data for result in results], [True, False, True])
        self.assertEqual(results[-1].analysis_10m["trend"], "BEARISH")

    def test_no_usable_candles(self):
        frame = bars()
        frame[["open", "high", "low", "close"]] = float("nan")
        self.assertFalse(analyze_symbol("EMPTY", frame).has_data)

    def test_empty_and_missing_symbol_api_results(self):
        client = Mock()
        for frame in [pd.DataFrame(), pd.DataFrame({"symbol": ["OTHER"],
                                                   "timestamp": ["unused"]})]:
            with self.subTest(frame=frame):
                client.get_stock_bars.return_value.df = frame
                self.assertTrue(fetch_one_minute_bars("MISSING", client, 3).empty)

    def test_summary_groups_by_ten_minutes_and_uses_ten_minute_vwap(self):
        results = [
            ScanResult("UP", {"trend": "BULLISH", "vwap_position": "ABOVE"},
                       {"trend": "BEARISH", "vwap_position": "BELOW"}),
            ScanResult("DOWN", {"trend": "BEARISH", "vwap_position": "BELOW"},
                       {"trend": "BULLISH"}),
            ScanResult("FLAT", {"trend": "MIXED", "vwap_position": "BELOW"},
                       {"trend": "BULLISH"}),
            ScanResult("MISSING"),
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_watchlist_summary(results)
        text = output.getvalue()
        self.assertIn("RIPSTER WATCHLIST SCAN", text)
        self.assertEqual(next(line for line in text.splitlines() if line.startswith("UP ")).split(),
                         ["UP", "BULLISH", "BEARISH", "ABOVE"])
        self.assertIn("Potential Long Context:\n* UP", text)
        self.assertIn("Potential Short Context:\n* DOWN", text)
        self.assertIn("Mixed / Ignore:\n* FLAT", text)
        self.assertIn("NO DATA", text)
        self.assertNotIn("* MISSING", text)

    @patch("ripster_scanner.scan.fetch_one_minute_bars", return_value=pd.DataFrame())
    def test_all_symbols_empty(self, fetch):
        results = scan_watchlist(Config("fake", "fake", ("ONE", "TWO")), Mock())
        self.assertEqual(len(results), 2)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_watchlist_summary(results)
        self.assertEqual(output.getvalue().count("* None"), 3)


if __name__ == "__main__":
    unittest.main()
