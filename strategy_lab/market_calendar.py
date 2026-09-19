"""Exchange-session validation and private calendar metadata for replay creation."""

import calendar as month_calendar
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from .domain import MarketClosed, ReplayDateUnavailable


class USEquityMarketCalendar:
    market = 'US_EQUITY'
    timezone = ZoneInfo('America/New_York')

    def __init__(self, calendar=None):
        self.calendar = calendar or xcals.get_calendar('XNYS')

    @staticmethod
    def _date(value):
        return value.date() if hasattr(value, 'date') else value

    def is_session(self, day: date):
        return self.calendar.is_session(day.isoformat())

    def validate(self, day: date):
        if self.is_session(day):
            return
        previous_day = self._date(self.calendar.date_to_session(day.isoformat(), direction='previous'))
        next_day = self._date(self.calendar.date_to_session(day.isoformat(), direction='next'))
        reason = 'WEEKEND' if day.weekday() >= 5 else 'MARKET_HOLIDAY'
        display = day.strftime('%B %-d, %Y')
        raise MarketClosed(
            f'US equity market was closed on {display}. Choose another trading day.',
            selected_date=day, reason=reason,
            previous_trading_day=previous_day, next_trading_day=next_day)

    def validate_for_replay(self, day, now=None):
        self.validate(day)
        now = now or datetime.now(timezone.utc)
        if day > now.astimezone(self.timezone).date():
            raise ReplayDateUnavailable('Future dates are not available for historical replay.',
                                        selected_date=day, reason='FUTURE_DATE')
        close = self.calendar.session_close(day.isoformat()).to_pydatetime()
        if now.astimezone(timezone.utc) < close.astimezone(timezone.utc):
            raise ReplayDateUnavailable(
                'This trading session has not completed yet. Choose an earlier trading day.',
                selected_date=day, reason='SESSION_NOT_COMPLETED')

    def latest_completed(self, now=None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('Current time must be timezone-aware')
        today = now.astimezone(self.timezone).date()
        if self.is_session(today):
            close = self.calendar.session_close(today.isoformat()).to_pydatetime()
            if now.astimezone(timezone.utc) >= close.astimezone(timezone.utc):
                return today
        return self._date(self.calendar.date_to_session(today.isoformat(), direction='previous'))

    def month(self, year, month, *, now=None):
        if not 1 <= month <= 12 or not 1990 <= year <= 2100:
            raise ValueError('Calendar year/month is outside the supported range')
        now = now or datetime.now(timezone.utc)
        today = now.astimezone(self.timezone).date()
        last_day = month_calendar.monthrange(year, month)[1]
        days = []
        for number in range(1, last_day + 1):
            day = date(year, month, number)
            if day > today:
                status, reason = 'UNAVAILABLE', 'FUTURE_DATE'
            elif self.is_session(day):
                close = self.calendar.session_close(day.isoformat()).to_pydatetime()
                if now.astimezone(timezone.utc) >= close.astimezone(timezone.utc):
                    status, reason = 'OPEN', None
                else:
                    status, reason = 'UNAVAILABLE', 'SESSION_NOT_COMPLETED'
            else:
                status = 'CLOSED'
                reason = 'WEEKEND' if day.weekday() >= 5 else 'MARKET_HOLIDAY'
            days.append({'date': day.isoformat(), 'status': status, 'reason': reason})
        first, last = date(year, month, 1), date(year, month, last_day)
        return {'market': self.market, 'year': year, 'month': month,
            'default_date': self.latest_completed(now).isoformat(), 'days': days,
            'previous_trading_day': self.adjacent(first, 'previous').isoformat(),
            'next_trading_day': self.adjacent(last, 'next').isoformat()}

    def adjacent(self, day, direction):
        if direction not in ('previous', 'next'):
            raise ValueError('Direction must be previous or next')
        if self.is_session(day):
            value = (self.calendar.previous_session(day.isoformat()) if direction == 'previous'
                     else self.calendar.next_session(day.isoformat()))
        else:
            value = self.calendar.date_to_session(day.isoformat(), direction=direction)
        return self._date(value)
