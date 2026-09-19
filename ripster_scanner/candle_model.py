"""Provider-neutral candle frames and explicit source provenance."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MarketSource:
    provider: str
    feed: str
    session_policy: str
    timezone: str


ALPACA_IEX_SOURCE = MarketSource(
    provider='Alpaca', feed='IEX',
    session_policy='Provider equity extended hours; NY calendar-day VWAP; partial candles included',
    timezone='America/New_York')


@dataclass(frozen=True)
class CandleSeries:
    """Internal OHLCV model; provider adapters normalize before constructing it."""
    frame: pd.DataFrame
    source: MarketSource
    timeframe: str = '1min'
    symbol: str | None = None

    @property
    def empty(self):
        return self.frame.empty


def frame_of(value):
    return value.frame if isinstance(value, CandleSeries) else value


def same_source(value, frame, timeframe=None):
    return CandleSeries(frame, value.source, timeframe or value.timeframe, value.symbol) if isinstance(
        value, CandleSeries) else frame
