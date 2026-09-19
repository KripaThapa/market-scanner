"""Market-data provider protocol and the current Alpaca/IEX adapter."""

from typing import Protocol

from .candle_model import ALPACA_IEX_SOURCE, CandleSeries


def fetch_one_minute_bars(symbol, client, lookback_days):
    # Keep the Alpaca SDK outside the provider-neutral scanner import path.
    from .market_data import fetch_one_minute_bars as fetch_alpaca_bars
    return fetch_alpaca_bars(symbol, client, lookback_days)


class MarketDataProvider(Protocol):
    def fetch(self, symbol: str, lookback_days: int) -> CandleSeries: ...


class AlpacaIEXProvider:
    source = ALPACA_IEX_SOURCE

    def __init__(self, api_key: str, secret_key: str, *, client=None):
        if client is None:
            from alpaca.data.historical import StockHistoricalDataClient
            client = StockHistoricalDataClient(api_key, secret_key)
        self.client = client

    def fetch(self, symbol: str, lookback_days: int) -> CandleSeries:
        return CandleSeries(fetch_one_minute_bars(symbol, self.client, lookback_days),
                            self.source, symbol=symbol)


def build_provider(config, *, client=None) -> MarketDataProvider:
    if config.market_data_provider == 'alpaca_iex':
        return AlpacaIEXProvider(config.api_key, config.secret_key, client=client)
    raise ValueError(f'Unsupported MARKET_DATA_PROVIDER: {config.market_data_provider}')
