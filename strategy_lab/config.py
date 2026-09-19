from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ReplaySettings:
    timezone: str = 'America/Chicago'
    start: str = '08:00'
    equity_start: str = '08:30'
    end: str = '10:00'
    warmup_calendar_days: int = 7
    outcome_bars: int = 10


def load_settings():
    days = int(os.getenv('REPLAY_WARMUP_CALENDAR_DAYS', '7'))
    if not 1 <= days <= 30:
        raise ValueError('REPLAY_WARMUP_CALENDAR_DAYS must be in 1..30')
    return ReplaySettings(
        timezone=os.getenv('REPLAY_TIMEZONE', 'America/Chicago'),
        start=os.getenv('REPLAY_START', '08:00'),
        equity_start=os.getenv('REPLAY_EQUITY_START', '08:30'),
        end=os.getenv('REPLAY_END', '10:00'),
        warmup_calendar_days=days)
