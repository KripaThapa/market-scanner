"""Opening timestamps and execution-time candle completion."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def candle_state(candle_start: datetime | str | None, timeframe: str,
                 evaluated_at: datetime, market_timezone: str = 'America/New_York'):
    if candle_start is None:
        return None
    start = datetime.fromisoformat(candle_start) if isinstance(candle_start, str) else candle_start
    if start.tzinfo is None or evaluated_at.tzinfo is None:
        raise ValueError('Candle and evaluation timestamps must be timezone-aware')
    minutes = {'3m': 3, '10m': 10}[timeframe]
    # Convert both instants through the market timezone; timedelta comparison
    # uses UTC to remain correct around DST transitions.
    market = ZoneInfo(market_timezone)
    start_utc = start.astimezone(market).astimezone(timezone.utc)
    evaluated_utc = evaluated_at.astimezone(market).astimezone(timezone.utc)
    return 'COMPLETED' if evaluated_utc >= start_utc + timedelta(minutes=minutes) else 'PARTIAL'
