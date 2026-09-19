"""Scanner calculations work with in-memory provider-neutral candle frames."""
import unittest
from unittest.mock import patch
import pandas as pd

from ripster_scanner.candle_model import ALPACA_IEX_SOURCE, CandleSeries, MarketSource
from ripster_scanner.config import Config
from ripster_scanner.provider import AlpacaIEXProvider
from ripster_scanner.scan import scan_watchlist
from test_watchlist import bars


class FakeProvider:
    source = MarketSource('Fake', 'MEMORY', 'test regular hours', 'America/New_York')

    def fetch(self, symbol, lookback_days):
        return CandleSeries(bars(1 if symbol == 'UP' else -1), self.source, symbol=symbol)


class ProviderTests(unittest.TestCase):
    def test_alpaca_adapter_returns_normalized_candles_and_source(self):
        with patch('ripster_scanner.provider.fetch_one_minute_bars', return_value=bars()) as fetch:
            series = AlpacaIEXProvider('unused', 'unused', client=object()).fetch('UP', 3)
        self.assertIsInstance(series, CandleSeries)
        self.assertEqual(series.source, ALPACA_IEX_SOURCE)
        self.assertEqual(series.symbol, 'UP')
        self.assertIn('close', series.frame.columns)
        fetch.assert_called_once()

    def test_scanner_and_indicators_use_fake_provider_without_alpaca_requests(self):
        results = scan_watchlist(Config('unused', 'unused', ('UP', 'DOWN')), FakeProvider())
        self.assertEqual([item.analysis_10m['trend'] for item in results],
                         ['BULLISH', 'BEARISH'])
        self.assertTrue(all(item.source.feed == 'MEMORY' for item in results))
        self.assertEqual(results[0].candles_3m[-1]['close'],
                         results[0].analysis_3m['close'])

    def test_alpaca_source_retains_0800_to_0830_central_extended_hours(self):
        from ripster_scanner.market_data import fetch_one_minute_bars
        index = pd.to_datetime(['2026-09-18T13:00:00Z', '2026-09-18T13:29:00Z',
                                '2026-09-18T13:30:00Z'])
        class Bars:
            df = pd.DataFrame({'symbol': ['SPY'] * 3, 'timestamp': index,
                'open': [1] * 3, 'high': [2] * 3, 'low': [.5] * 3,
                'close': [1.5] * 3, 'volume': [100] * 3, 'trade_count': [1] * 3})
        class Client:
            def get_stock_bars(self, request): return Bars()
        result = fetch_one_minute_bars('SPY', Client(), 1)
        central = result.index.tz_convert('America/Chicago')
        self.assertEqual([value.strftime('%H:%M') for value in central],
                         ['08:00', '08:29', '08:30'])


if __name__ == '__main__':
    unittest.main()
