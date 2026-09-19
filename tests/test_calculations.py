import unittest

import pandas as pd

from ripster_scanner.candles import resample_candles
from ripster_scanner.indicators import add_emas


class CandleTests(unittest.TestCase):
    def test_ohlcv_boundaries_and_partial_candle(self):
        index = pd.date_range("2026-09-10 09:30", periods=11, freq="min",
                              tz="America/New_York")
        frame = pd.DataFrame({
            "open": range(10, 21), "high": range(12, 23),
            "low": range(9, 20), "close": range(11, 22),
            "volume": [10] * 11, "trade_count": [2] * 11,
        }, index=index)
        for timeframe, size in [("3min", 3), ("10min", 10)]:
            with self.subTest(timeframe=timeframe):
                result = resample_candles(frame, timeframe)
                self.assertEqual(result.index[0], index[0])
                self.assertEqual(result.index[1], index[size])
                self.assertEqual(result.iloc[0].to_dict(), {
                    "open": 10, "high": 11 + size, "low": 9,
                    "close": 10 + size, "volume": 10 * size,
                    "trade_count": 2 * size,
                })
                self.assertEqual(result.iloc[-1]["close"], 21)
                self.assertEqual(result.volume.sum(), 110)

    def test_empty_overnight_bins_are_removed(self):
        index = pd.to_datetime(["2026-09-10 15:59", "2026-09-11 09:30"]).tz_localize(
            "America/New_York")
        frame = pd.DataFrame({column: [1, 2] for column in
                              ["open", "high", "low", "close", "volume", "trade_count"]},
                             index=index)
        result = resample_candles(frame, "10min")
        self.assertEqual(len(result), 2)
        self.assertEqual(list(result.index.hour), [15, 9])
        self.assertEqual(list(result.index.minute), [50, 30])


class EmaTests(unittest.TestCase):
    def test_recursive_ema_for_all_spans_without_mutating_input(self):
        frame = pd.DataFrame({"close": [10.0, 13.0, 7.0, 15.0]})
        original = frame.copy(deep=True)
        result = add_emas(frame)
        for span in (5, 12, 34, 50):
            alpha = 2 / (span + 1)
            expected = 10.0
            self.assertEqual(result[f"ema_{span}"].iloc[0], expected)
            for row, close in enumerate(frame.close.iloc[1:], start=1):
                expected = alpha * close + (1 - alpha) * expected
                self.assertAlmostEqual(result[f"ema_{span}"].iloc[row], expected)
        pd.testing.assert_frame_equal(frame, original)

    def test_constant_prices(self):
        result = add_emas(pd.DataFrame({"close": [42.0] * 60}))
        for span in (5, 12, 34, 50):
            self.assertTrue((result[f"ema_{span}"] == 42).all())


if __name__ == "__main__":
    unittest.main()
