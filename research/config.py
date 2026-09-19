"""Timezone-aware research window and nightly schedule configuration."""

from dataclasses import dataclass
from datetime import datetime, time, timezone
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _clock(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('Research schedule times must use HH:MM') from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ValueError('Research schedule times must use HH:MM')
    return parsed


@dataclass(frozen=True)
class ResearchSettings:
    start: time
    end: time
    timezone: ZoneInfo
    nightly_time: time
    nightly_timezone: ZoneInfo
    baseline_catchup_days: int

    def local_date(self, observed_at: datetime):
        return observed_at.astimezone(self.timezone).date()

    def inside_window(self, observed_at: datetime) -> bool:
        local = observed_at.astimezone(self.timezone)
        return self.start <= local.timetz().replace(tzinfo=None) < self.end


def load_settings() -> ResearchSettings:
    try:
        settings = ResearchSettings(
            _clock(os.getenv('TRADING_WINDOW_START', '08:00')),
            _clock(os.getenv('TRADING_WINDOW_END', '10:00')),
            ZoneInfo(os.getenv('TRADING_TIMEZONE', 'America/Chicago')),
            _clock(os.getenv('NIGHTLY_ANALYSIS_TIME', '18:00')),
            ZoneInfo(os.getenv('NIGHTLY_ANALYSIS_TIMEZONE', 'America/Chicago')),
            int(os.getenv('BASELINE_MAX_CATCHUP_TRADING_DAYS', '5')),
        )
    except ZoneInfoNotFoundError as exc:
        raise ValueError('Invalid research timezone') from exc
    if settings.start >= settings.end:
        raise ValueError('TRADING_WINDOW_START must precede TRADING_WINDOW_END')
    if not 1 <= settings.baseline_catchup_days <= 60:
        raise ValueError('BASELINE_MAX_CATCHUP_TRADING_DAYS must be in 1..60')
    return settings
