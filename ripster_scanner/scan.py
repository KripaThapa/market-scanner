"""Process watchlist symbols independently using the existing context rules."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math

import pandas as pd

from .candles import resample_candles
from .candle_model import ALPACA_IEX_SOURCE, CandleSeries, MarketSource, frame_of
from .config import Config, FormingThresholds
from .forming import FormingResult, detect_forming
from .entry_context import analyze_entry_context
from .indicators import add_emas, add_vwap
from .market_context import analyze_trend


def fetch_one_minute_bars(symbol, client, lookback_days):
    """Compatibility path for callers passing an Alpaca client directly."""
    from .market_data import fetch_one_minute_bars as fetch_alpaca_bars
    return fetch_alpaca_bars(symbol, client, lookback_days)


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    analysis_10m: dict | None = None
    analysis_3m: dict | None = None
    forming: FormingResult = FormingResult()
    candles_10m: list[dict] | None = None
    candles_3m: list[dict] | None = None
    forming_candle_at: str | None = None
    source: MarketSource | None = None
    evaluated_at: datetime | None = None

    @property
    def has_data(self) -> bool:
        return self.analysis_10m is not None and self.analysis_3m is not None


def chart_candles(frame: pd.DataFrame, limit: int) -> list[dict]:
    """Serialize the already calculated candles, preserving their market timestamps."""
    fields = ('open', 'high', 'low', 'close', 'volume', 'ema_5', 'ema_12',
              'ema_34', 'ema_50', 'vwap')
    return [{'timestamp': timestamp.isoformat(), **{
        field: float(row[field]) if math.isfinite(float(row[field])) else None
        for field in fields}} for timestamp, row in frame_of(frame).tail(limit).iterrows()]


def analyze_symbol(symbol: str, one_min: pd.DataFrame,
                   thresholds: FormingThresholds = FormingThresholds(),
                   evaluated_at: datetime | None = None) -> ScanResult:
    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    if not isinstance(one_min, CandleSeries):
        one_min = CandleSeries(one_min, ALPACA_IEX_SOURCE, symbol=symbol)
    if one_min.empty:
        return ScanResult(symbol, source=one_min.source, evaluated_at=evaluated_at)
    three_min = resample_candles(one_min, "3min")
    ten_min = resample_candles(one_min, "10min")
    if three_min.empty or ten_min.empty:
        return ScanResult(symbol, source=one_min.source, evaluated_at=evaluated_at)
    three_min = add_vwap(add_emas(three_min))
    ten_min = add_vwap(add_emas(ten_min))
    ten = analyze_trend(ten_min)
    forming = detect_forming(ten['trend'], three_min, thresholds)
    return ScanResult(symbol, ten, analyze_entry_context(three_min), forming,
                      chart_candles(ten_min, 120), chart_candles(three_min, 240),
                      frame_of(three_min).index[-1].isoformat() if forming.state != 'NONE' else None,
                      one_min.source, evaluated_at)


def scan_watchlist(config: Config, provider) -> list[ScanResult]:
    results = []
    for symbol in config.symbols:
        # The fallback only preserves the old programmatic client API; runtime
        # workers and the CLI use MarketDataProvider.fetch.
        one_min = (provider.fetch(symbol, config.lookback_days)
                   if callable(getattr(type(provider), 'fetch', None)) else
                   CandleSeries(fetch_one_minute_bars(symbol, provider, config.lookback_days),
                                ALPACA_IEX_SOURCE, symbol=symbol))
        results.append(analyze_symbol(symbol, one_min, config.forming))
    return results
