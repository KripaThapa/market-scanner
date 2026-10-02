"""Capture the existing provider fetch before strategy processing; no extra HTTP."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from ripster_scanner.candle_model import MarketSource, frame_of
from ripster_scanner.watchlist_levels import price_value


@dataclass(frozen=True)
class PriceObservation:
    price: Decimal
    bar_at: datetime
    observed_at: datetime
    source: MarketSource | None = None


class PriceObservingProvider:
    def __init__(self, provider):
        self.provider = provider
        self.source = provider.source
        self.observations = {}

    def fetch(self, symbol, lookback_days):
        bars = self.provider.fetch(symbol, lookback_days)
        observed_at = datetime.now(timezone.utc)
        try:
            frame = frame_of(bars)
            if not frame.empty:
                stamp = frame.index[-1].to_pydatetime()
                price = price_value(frame.iloc[-1]['close'])
                if price is not None and stamp.tzinfo and stamp <= observed_at:
                    self.observations[symbol] = PriceObservation(
                        price, stamp, observed_at, getattr(bars, 'source', self.source))
        except (AttributeError, KeyError, TypeError, ValueError):
            # A missing price observation must not change the strategy data path.
            pass
        return bars
