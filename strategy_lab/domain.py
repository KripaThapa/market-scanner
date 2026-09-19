from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import pandas as pd

from ripster_scanner.candle_model import MarketSource


class AssetType(StrEnum):
    EQUITY = 'EQUITY'
    FUTURE = 'FUTURE'


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_type: AssetType
    provider_identifier: str | None = None


class ReplayDataUnavailable(ValueError):
    code = 'NO_DATA'

    def __init__(self, message, *, details=None):
        super().__init__(message)
        self.details = details or {'error': self.code, 'message': message}


class MarketClosed(ValueError):
    code = 'MARKET_CLOSED'

    def __init__(self, message, *, selected_date, reason,
                 previous_trading_day, next_trading_day):
        super().__init__(message)
        self.details = {
            'error': self.code,
            'message': message,
            'selected_date': selected_date.isoformat(),
            'market': 'US_EQUITY',
            'session_status': 'CLOSED',
            'reason': reason,
            'previous_trading_day': previous_trading_day.isoformat(),
            'next_trading_day': next_trading_day.isoformat(),
        }


class ReplayDateUnavailable(ValueError):
    code = 'DATE_UNAVAILABLE'

    def __init__(self, message, *, selected_date, reason):
        super().__init__(message)
        self.details = {'error': self.code, 'message': message,
            'selected_date': selected_date.isoformat(), 'market': 'US_EQUITY',
            'session_status': 'UNAVAILABLE', 'reason': reason}


@dataclass(frozen=True)
class HistoricalCandleSet:
    instrument: Instrument
    frame: pd.DataFrame
    source: MarketSource


class BoundedMarketView:
    """The only calculation-facing view; 1m timestamps are candle starts."""

    def __init__(self, source_frame: pd.DataFrame, as_of: datetime):
        if as_of.tzinfo is None:
            raise ValueError('Replay time must be timezone-aware')
        if source_frame.index.tz is None:
            raise ValueError('Historical candle timestamps must be timezone-aware')
        # A minute opening at 08:05 is known only once it completes at 08:06.
        self.__frame = source_frame.loc[source_frame.index < as_of].copy()
        self.as_of = as_of

    @property
    def frame(self):
        return self.__frame.copy()
