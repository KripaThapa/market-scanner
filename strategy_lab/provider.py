"""Historical replay capability, separate from the live lookback provider."""

from datetime import datetime
from typing import Protocol

import pandas as pd

from ripster_scanner.candle_model import MarketSource
from .domain import AssetType, HistoricalCandleSet, Instrument, ReplayDataUnavailable


class HistoricalMarketDataProvider(Protocol):
    def supports(self, asset_type: AssetType) -> bool: ...
    def fetch_range(self, instrument: Instrument, start: datetime,
                    end: datetime) -> HistoricalCandleSet: ...


class AlpacaHistoricalReplayProvider:
    """Alpaca/IEX extended-hours equities; Alpaca has no futures client."""
    source = MarketSource('Alpaca', 'IEX',
        'Equity extended hours retained; one-minute opening timestamps; VWAP resets midnight America/New_York',
        'America/New_York')

    def __init__(self, api_key, secret_key, *, client=None):
        if client is None:
            from alpaca.data.historical import StockHistoricalDataClient
            client = StockHistoricalDataClient(api_key, secret_key)
        self.client = client

    def supports(self, asset_type):
        return asset_type == AssetType.EQUITY

    def fetch_range(self, instrument, start, end):
        if not self.supports(instrument.asset_type):
            raise ReplayDataUnavailable(
                'MES futures history is unavailable from the configured Alpaca/IEX provider. '
                'A provider with historical one-minute futures bars, contract identity/roll metadata, '
                'and futures-session semantics is required.')
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        request = StockBarsRequest(symbol_or_symbols=[instrument.symbol], timeframe=TimeFrame.Minute,
                                   start=start, end=end, feed=DataFeed.IEX)
        bars = self.client.get_stock_bars(request).df.reset_index()
        if bars.empty:
            frame = pd.DataFrame(columns=('open', 'high', 'low', 'close', 'volume', 'trade_count'))
            frame.index = pd.DatetimeIndex([], tz='America/New_York', name='timestamp')
        else:
            frame = bars[bars['symbol'] == instrument.symbol].copy()
            frame['timestamp'] = pd.to_datetime(frame['timestamp']).dt.tz_convert('America/New_York')
            frame = frame.set_index('timestamp')
        return HistoricalCandleSet(instrument, frame, self.source)
