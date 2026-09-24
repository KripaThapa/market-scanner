"""Alert-time evidence and explicit display DTOs; no strategy or delivery logic."""

from datetime import datetime, timezone
import logging
import math

from sqlalchemy import select

from .database.models import Alert, AlertState
from discovery.candle_state import candle_state
from ripster_scanner.strategy import strategy_version_id
from scanner.progress import error_category

log = logging.getLogger(__name__)


def utc(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError('Alert evidence requires timezone-aware timestamps')
    return parsed.astimezone(timezone.utc)


def number(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def capture_snapshot(result, sector, published_at):
    """Copy only the scanner's current evidence, never re-query candle history.

    A future-dated frame invalidates that frame's summary. Missing evidence stays
    null; the snapshot records the distinction from an observed numeric zero.
    """
    known_at = min(utc(result.evaluated_at or published_at), utc(published_at))
    frames = {}
    for frame in ('3m', '10m'):
        candles = getattr(result, f'candles_{frame}') or []
        latest = candles[-1] if candles else {}
        valid = bool(latest and utc(latest['timestamp']) <= known_at)
        frames[frame] = {
            'candle_at': utc(latest['timestamp']).isoformat() if valid else None,
            'context': (getattr(result, f'analysis_{frame}') or {}).get('trend') if valid else None,
            **{field: number(latest.get(field)) if valid else None for field in
               ('close', 'ema_5', 'ema_12', 'ema_34', 'ema_50', 'vwap', 'volume')},
        }
    decision = utc(frames['3m']['candle_at']) if frames['3m']['candle_at'] else None
    if result.forming.state != 'NONE' and (
            not result.forming_candle_at or utc(result.forming_candle_at) != decision):
        decision = None
    source = result.source
    return decision, {
        'schema_version': 1,
        'evaluated_at': known_at.isoformat(),
        'scanner_evaluated_at': utc(result.evaluated_at).isoformat() if result.evaluated_at else None,
        'setup_state': result.forming.state.value,
        'sector': sector or 'UNKNOWN',
        'reason': result.forming.reason,
        'frames': frames,
        'price': frames['3m']['close'],
        'candle_state': candle_state(decision, '3m', known_at) if decision else None,
        'provider': source.provider if source else None,
        'feed': source.feed if source else None,
        'source_timeframe': '1m' if source else None,
        'session_policy': source.session_policy if source else None,
        'market_timezone': source.timezone if source else None,
    }


def _stored_utc(value):
    # SQLite's test adapter strips offsets; production stores timestamptz.
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def collect_alerts(session, results, errors, sectors, timestamp, thresholds):
    """Called inside publication's AppState row lock, after normal scan writes.

    Each symbol's event and transition cursor are atomic. A failed alert write
    rolls back its savepoint, leaving the cursor retryable and publication alive.
    """
    version = strategy_version_id(thresholds)
    session.flush()
    for result in results:
        if result.symbol in errors or not result.has_data:
            continue
        try:
            decision, snapshot = capture_snapshot(result, sectors.get(result.symbol), timestamp)
            if (snapshot['candle_state'] != 'COMPLETED'
                    or not snapshot['frames']['10m']['candle_at']
                    or result.forming.state not in {'NONE', 'FORMING_LONG', 'FORMING_SHORT'}):
                continue
            known_at = utc(snapshot['evaluated_at'])
            snapshot['decision_eligible'] = True
            with session.begin_nested():
                state = session.get(AlertState, (result.symbol, version))
                if state is not None:
                    last_candle = _stored_utc(state.last_candle_at)
                    last_evaluated = _stored_utc(state.last_evaluated_at)
                    if (decision < last_candle or known_at < last_evaluated or
                            (decision == last_candle and known_at == last_evaluated)):
                        continue
                else:
                    state = AlertState(symbol=result.symbol, strategy_version=version,
                        setup_state='NONE', transition_number=0)
                    session.add(state)
                current = result.forming.state.value
                if current != 'NONE' and current != state.setup_state:
                    state.transition_number += 1
                    session.add(Alert(symbol=result.symbol, alert_type=current,
                        strategy_version=version, transition_number=state.transition_number,
                        created_at=timestamp, decision_candle_at=decision,
                        reason=result.forming.reason, snapshot=snapshot))
                state.setup_state = current
                state.last_candle_at = decision
                state.last_evaluated_at = known_at
        except Exception as exc:
            # Never format provider/database exceptions or snapshot contents.
            log.warning('Alert persistence failed for symbol=%s error_type=%s; retrying on next eligible observation',
                        result.symbol, error_category(exc))


def alert_row(alert):
    snapshot = alert.snapshot or {}
    return {'id': alert.id, 'symbol': alert.symbol,
            'timestamp': _stored_utc(alert.created_at).isoformat(),
            'alert_type': alert.alert_type, 'reason': alert.reason,
            'price': snapshot.get('price'),
            'context_10m': snapshot.get('frames', {}).get('10m', {}).get('context'),
            'decision_candle_at': _stored_utc(alert.decision_candle_at).isoformat()
                if alert.decision_candle_at else None}


def chart_alerts(session, symbol, candles):
    """Use exact visible candle instants; never snap events to adjacent bars."""
    instants = {utc(candle['timestamp']) for candle in candles}
    if not instants:
        return []
    rows = session.scalars(select(Alert).where(
        Alert.symbol == symbol, Alert.transition_number.is_not(None),
        Alert.decision_candle_at >= min(instants),
        Alert.decision_candle_at <= max(instants)).order_by(
            Alert.decision_candle_at, Alert.id).limit(1000))
    return [public_marker(alert_row(row)) for row in rows
            if _stored_utc(row.decision_candle_at) in instants]


def public_alert(row):
    """Never forward stored detector explanations or provenance to a browser."""
    result = {key: row.get(key) for key in
              ('id', 'symbol', 'timestamp', 'alert_type', 'price', 'context_10m')}
    result['reason'] = ('Experimental forming state detected.'
                        if row.get('alert_type') in {'FORMING_LONG', 'FORMING_SHORT'} else None)
    return result


def public_marker(row):
    return {key: row.get(key) for key in ('id', 'timestamp', 'alert_type', 'decision_candle_at')}
