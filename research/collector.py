"""Capture what the scanner knew at publication time, without future candles."""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.database.models import (ResearchCandle, ResearchObservation,
    ResearchObservationSource, StrategyVersion)
from backend.store import finite
from ripster_scanner.candle_model import ALPACA_IEX_SOURCE, MarketSource
from ripster_scanner.strategy import STRATEGY_NAME, rule_definitions, strategy_version_id


def utc_timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Candle timestamps must include a timezone offset')
    return parsed.astimezone(timezone.utc)


def ensure_version(session, thresholds, timestamp):
    version = strategy_version_id(thresholds)
    existing = session.get(StrategyVersion, version)
    if existing is None:
        session.add(StrategyVersion(id=version, name=STRATEGY_NAME,
            status='EXPERIMENTAL', config_snapshot=asdict(thresholds),
            rules_snapshot=rule_definitions(thresholds), created_at=timestamp))
    elif existing.rules_snapshot is None:
        # Upgrade legacy V1 rows that predate persisted rule definitions.
        existing.rules_snapshot = rule_definitions(thresholds)
    return version


def _capture_candles(session, symbol, timeframe, candles, timestamp, source):
    if not candles:
        return []
    eligible = [(utc_timestamp(row['timestamp']), row) for row in candles]
    eligible = [(at, row) for at, row in eligible if at <= timestamp]
    if not eligible:
        return []
    first, last = min(at for at, _ in eligible), max(at for at, _ in eligible)
    existing = {((row.candle_at.astimezone(timezone.utc) if row.candle_at.tzinfo
                  else row.candle_at.replace(tzinfo=timezone.utc)), row.content_hash)
                for row in session.scalars(select(ResearchCandle).where(
                    ResearchCandle.symbol == symbol, ResearchCandle.timeframe == timeframe,
                    ResearchCandle.provider == source.provider, ResearchCandle.feed == source.feed,
                    ResearchCandle.candle_at >= first, ResearchCandle.candle_at <= last))}
    for at, row in eligible:
        values = {key: finite(row.get(key)) for key in
                  ('open', 'high', 'low', 'close', 'volume', 'ema_5', 'ema_12',
                   'ema_34', 'ema_50', 'vwap')}
        digest = hashlib.sha256(json.dumps({'values': values,
            'session_policy': source.session_policy, 'timezone': source.timezone}, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()
        if (at, digest) in existing:
            continue
        session.add(ResearchCandle(symbol=symbol, timeframe=timeframe, candle_at=at,
            source_timeframe='1m',
            captured_at=timestamp, provider=source.provider, feed=source.feed,
            session_policy=source.session_policy, source_timezone=source.timezone,
            content_hash=digest, **values))
        existing.add((at, digest))
    return eligible


def collect_publication(session, snapshot, results, sector_map, errors, timestamp,
                        settings, thresholds, *, universe=None, sector_snapshot_ids=None):
    from discovery.candle_state import candle_state
    version = ensure_version(session, thresholds, timestamp)
    local_date = settings.local_date(timestamp).isoformat()
    inside = settings.inside_window(timestamp)
    universe = universe or {}
    sector_snapshot_ids = sector_snapshot_ids or {}
    for result in results:
        source = result.source or ALPACA_IEX_SOURCE
        known_at = min(result.evaluated_at or timestamp, timestamp)
        three = _capture_candles(session, result.symbol, '3m', result.candles_3m,
                                 known_at, source)
        ten = _capture_candles(session, result.symbol, '10m', result.candles_10m,
                               known_at, source)
        three_at = three[-1][0] if three else None
        ten_at = ten[-1][0] if ten else None
        # ScanResult summaries refer to the last candle. A mocked or malformed
        # future candle must never be serialized as historical evidence.
        valid = bool(three and ten and result.candles_3m and result.candles_10m
                     and utc_timestamp(result.candles_3m[-1]['timestamp']) <= known_at
                     and utc_timestamp(result.candles_10m[-1]['timestamp']) <= known_at
                     and result.symbol not in errors)
        three_summary = (result.analysis_3m or {}) if valid else {}
        ten_summary = (result.analysis_10m or {}) if valid else {}
        latest_three = three[-1][1] if valid else {}
        latest_ten = ten[-1][1] if valid else {}
        sector = sector_map.get(result.symbol, 'UNKNOWN')
        current_sources = universe.get(result.symbol, {}).get('sources')
        execution_candle_state = candle_state(three_at, '3m', result.evaluated_at or timestamp,
                                               source.timezone)
        feature_digest = hashlib.sha256(json.dumps({
            'three': three_summary, 'ten': ten_summary,
            'three_candle': latest_three, 'ten_candle': latest_ten,
            'state': result.forming.state.value if valid else 'NONE',
            'reason': result.forming.reason if valid else None,
            'error': result.symbol in errors, 'sources': current_sources,
            'sector': sector, 'candle_state': execution_candle_state,
            'decision_eligible': bool(valid)}, sort_keys=True, default=str).encode()).hexdigest()[:16]
        key = f'{snapshot.id}:{result.symbol}:{version}:{local_date}:{int(inside)}:'
        key += f'{three_at.isoformat() if three_at else "no-candle"}:{feature_digest}'
        if session.scalar(select(ResearchObservation.id).where(
                ResearchObservation.dedupe_key == key)) is not None:
            continue
        stale = (valid and three_at.astimezone(ZoneInfo(source.timezone)).date()
                 != timestamp.astimezone(ZoneInfo(source.timezone)).date())
        data_status = ('STALE' if stale else 'OK' if valid else
                       'FUTURE_DATA_REJECTED' if result.candles_3m and
                       utc_timestamp(result.candles_3m[-1]['timestamp']) > known_at else
                       'ERROR' if result.symbol in errors else 'NO_DATA')
        observation = ResearchObservation(
            dedupe_key=key, snapshot_id=snapshot.id, symbol=result.symbol,
            observed_at=timestamp, created_at=timestamp, trading_date=local_date,
            strategy_version=version,
            watchlist_source=snapshot.source, watchlist_filename=snapshot.original_filename,
            sector=sector,
            price=finite(three_summary.get('close')),
            context_10m=ten_summary.get('trend', 'NO DATA'),
            context_3m=three_summary.get('trend', 'NO DATA'),
            setup_state=result.forming.state.value if valid else 'NONE',
            detector_reason=result.forming.reason if valid else None,
            three_min_candle_at=three_at, ten_min_candle_at=ten_at,
            **{f'ema_{span}_3m': finite(three_summary.get(f'ema_{span}'))
               for span in (5, 12, 34, 50)},
            **{f'ema_{span}_10m': finite(ten_summary.get(f'ema_{span}'))
               for span in (5, 12, 34, 50)},
            vwap_3m=finite(three_summary.get('vwap')),
            vwap_10m=finite(ten_summary.get('vwap')),
            vwap_position_3m=three_summary.get('vwap_position'),
            vwap_position_10m=ten_summary.get('vwap_position'),
            volume_3m=finite(latest_three.get('volume')),
            volume_10m=finite(latest_ten.get('volume')),
            inside_research_window=inside, provider=source.provider, feed=source.feed,
            source_timeframe='1m',
            session_policy=source.session_policy, market_timezone=source.timezone,
            research_timezone=str(settings.timezone), data_status=data_status,
            discovery_sources=current_sources,
            candle_state=execution_candle_state,
            decision_eligible=bool(valid),
            sector_snapshot_id=sector_snapshot_ids.get(sector))
        session.add(observation)
        session.flush()
        for source_type in observation.discovery_sources or []:
            session.add(ResearchObservationSource(observation_id=observation.id,
                                                  source_type=source_type))
