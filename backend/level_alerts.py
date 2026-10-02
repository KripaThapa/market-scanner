"""Watchlist-level events independent of all scanner/FORMING conditions."""

import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .alerts import _stored_utc, utc
from .database.models import Alert, WatchlistLevelMonitor, WatchlistSymbol
from ripster_scanner.watchlist_levels import parse_levels, price_value

log = logging.getLogger(__name__)
TRADING_TIMEZONE = ZoneInfo('America/New_York')


def trading_date(at):
    return utc(at).astimezone(TRADING_TIMEZONE).date().isoformat()


def level_key(date, symbol, direction, price):
    return f'{date}|{symbol}|{direction}|{price_value(price):f}'


def activate_levels(session, upload, *, date, at):
    """Called atomically with active-watchlist replacement, not once per alert."""
    existing = {row.key: row for row in session.scalars(select(WatchlistLevelMonitor).where(
        (WatchlistLevelMonitor.watchlist_date == date) | WatchlistLevelMonitor.active.is_(True)))}
    wanted = set()
    for source in session.scalars(select(WatchlistSymbol).where(
            WatchlistSymbol.watchlist_upload_id == upload.id,
            WatchlistSymbol.validation_status == 'validated').order_by(WatchlistSymbol.id)):
        instructions = source.level_instructions
        if instructions is None:
            # Existing rows may have a note but no structured extraction yet.
            instructions = [{'direction': item.direction, 'trigger_level': str(item.price),
                             'original_note': source.original_note} for item in parse_levels(source.original_note)]
        for item in instructions:
            price = price_value(item.get('trigger_level'))
            direction = item.get('direction')
            if price is None or direction not in {'LONG', 'SHORT'}:
                continue
            key = level_key(date, source.symbol, direction, price)
            if key in wanted:
                continue  # Same literal level on multiple rows: first source row wins.
            wanted.add(key)
            monitor = existing.get(key)
            if monitor is None:
                monitor = WatchlistLevelMonitor(key=key, watchlist_date=date,
                    symbol=source.symbol, direction=direction, trigger_level=price)
                session.add(monitor)
            elif not monitor.active:
                # No inferred crossing across an interval without an active monitor.
                monitor.previous_price = None
                monitor.previous_bar_at = None
                monitor.previous_observed_at = None
            monitor.active = True
            monitor.activated_at = at
            monitor.original_note = item.get('original_note')
            monitor.source_watchlist_id = upload.id
            monitor.source_row_id = source.id
            monitor.source_bbox = item.get('source_bbox')
    for key, monitor in existing.items():
        if key not in wanted:
            monitor.active = False


def collect_level_alerts(session, snapshot_id, observations, timestamp):
    """Publication lock + per-level savepoint makes event/cursor updates atomic.

    First observation seeds a baseline, even if already beyond the level. Failed
    or missing observations cannot advance it. Equality is never a crossing.
    """
    timestamp = utc(timestamp)
    session.flush()
    keys = list(session.scalars(select(WatchlistLevelMonitor.key).where(
        WatchlistLevelMonitor.active.is_(True),
        WatchlistLevelMonitor.source_watchlist_id == snapshot_id,
        WatchlistLevelMonitor.watchlist_date == trading_date(timestamp))))
    for key in keys:
        try:
            with session.begin_nested():
                monitor = session.get(WatchlistLevelMonitor, key)
                observation = observations.get(monitor.symbol)
                if observation is None or session.scalar(select(Alert.id).where(Alert.level_key == key)):
                    continue
                price = price_value(observation.price)
                at, bar = utc(observation.observed_at), utc(observation.bar_at)
                if (price is None or at > timestamp or bar > at
                        or at < _stored_utc(monitor.activated_at)
                        or trading_date(at) != monitor.watchlist_date
                        or trading_date(bar) != monitor.watchlist_date):
                    continue
                if monitor.previous_observed_at and (
                        at <= _stored_utc(monitor.previous_observed_at)
                        or bar < _stored_utc(monitor.previous_bar_at)):
                    continue
                previous = monitor.previous_price
                crossed = previous is not None and (
                    previous <= monitor.trigger_level < price if monitor.direction == 'LONG'
                    else previous >= monitor.trigger_level > price)
                if crossed:
                    source = observation.source
                    evidence = {
                        'schema_version': 1, 'trading_date': monitor.watchlist_date,
                        'watchlist_date': monitor.watchlist_date,
                        'symbol': monitor.symbol, 'direction': monitor.direction,
                        'trigger_level': str(monitor.trigger_level), 'price': float(price),
                        'observed_price': str(price), 'crossing_timestamp': at.isoformat(),
                        'bar_at': bar.isoformat(), 'previous_price': str(previous),
                        'previous_observed_at': _stored_utc(monitor.previous_observed_at).isoformat(),
                        'previous_bar_at': _stored_utc(monitor.previous_bar_at).isoformat(),
                        'original_note': monitor.original_note,
                        'source_watchlist_id': monitor.source_watchlist_id,
                        'source_row_id': monitor.source_row_id, 'source_bbox': monitor.source_bbox,
                        'provider': source.provider if source else None,
                        'feed': source.feed if source else None,
                        'source_timeframe': '1m', 'price_field': 'latest_available_bar_close',
                        'day_timezone': str(TRADING_TIMEZONE),
                    }
                    session.add(Alert(symbol=monitor.symbol,
                        alert_type=f'WATCHLIST_LEVEL_{monitor.direction}', level_key=key,
                        reason=monitor.original_note, snapshot=evidence, created_at=timestamp))
                monitor.previous_price = price
                monitor.previous_observed_at = at
                monitor.previous_bar_at = bar
        except Exception:
            log.warning('Level alert persistence failed; continuing remaining monitors')
