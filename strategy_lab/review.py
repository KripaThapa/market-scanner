"""Read-only chart review. Persisted events only; never runs a detector or backfill."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.database.models import (Alert, BaselineEpisode, BaselineEvaluation,
    BaselineRun, BaselineSymbolDay, ResearchCandle, ResearchObservation, ResearchOutcome,
    StrategyReplaySession, WatchlistSymbol, WatchlistUpload)
from backend.store import finite, iso
from research.repository import _utc
from ripster_scanner.watchlist_levels import price_value
from ripster_scanner.candle_model import MarketSource

ZONE = ZoneInfo('America/New_York')
VERSION = 'experimental-forming-v1/b067b3150de3'
FORMING = {'FORMING_LONG', 'FORMING_SHORT'}
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'ema_5', 'ema_12', 'ema_34', 'ema_50', 'vwap')


def bounds(day):
    parsed = date.fromisoformat(day)
    if parsed > datetime.now(ZONE).date():
        raise ValueError('Choose today or a historical date')
    start = datetime.combine(parsed, time(), ZONE)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def empty_outcome():
    return {'returns': {'9': None, '15': None, '30': None}, 'best_move': None,
            'adverse_move': None, 'window': None}


def mapped_outcome(values, future, event_at):
    """Map stored returns only when bar-close horizons equal elapsed minutes.

    Excursions keep their existing directional, next-ten-available-bars meaning.
    Missing/gapped horizons are never relabeled as elapsed-minute returns.
    """
    result = empty_outcome()
    if not values:
        return result
    for count, minutes in ((3, 9), (5, 15), (10, 30)):
        if (len(future) >= count and all(
                _utc(row['at']) == event_at + timedelta(minutes=3 * i)
                for i, row in enumerate(future[:count]))):
            result['returns'][str(minutes)] = finite(values.get(f'return_{count}'))
    if len(future) >= 10 and _utc(future[0]['at']) >= event_at:
        result.update(best_move=finite(values.get('best')), adverse_move=finite(values.get('adverse')),
                      window={'start': iso(future[0]['at']),
                              'end': iso(_utc(future[9]['at']) + timedelta(minutes=3)),
                              'label': 'Next 10 recorded 3-minute bars · relative to alert direction'})
    return result


class ChartReviewRepository:
    def __init__(self, engine):
        self.engine = engine

    def _watchlist(self, session, day):
        start, end = bounds(day)
        upload = session.scalar(select(WatchlistUpload).where(
            WatchlistUpload.source == 'image', WatchlistUpload.validated_count > 0,
            WatchlistUpload.processing_status.in_(('ready_for_review', 'queued', 'scanned')),
            or_(WatchlistUpload.trading_date == day, and_(WatchlistUpload.trading_date.is_(None),
                WatchlistUpload.uploaded_at >= start, WatchlistUpload.uploaded_at < end)),
        ).order_by(WatchlistUpload.processed_at.desc(), WatchlistUpload.id.desc()).limit(1))
        rows = list(session.scalars(select(WatchlistSymbol).where(
            WatchlistSymbol.watchlist_upload_id == upload.id,
            WatchlistSymbol.validation_status == 'validated').order_by(WatchlistSymbol.symbol))) if upload else []
        return upload, rows

    def watchlist(self, day):
        with Session(self.engine) as session:
            upload, rows = self._watchlist(session, day)
            return {'date': day, 'symbols': [row.symbol for row in rows],
                    'legacy_date': bool(upload and upload.trading_date is None)}

    def chart(self, day, symbol):
        start, end = bounds(day)
        with Session(self.engine) as session:
            upload, rows = self._watchlist(session, day)
            source = next((row for row in rows if row.symbol == symbol), None)
            if source is None:
                raise KeyError('Symbol is not in this date’s uploaded watchlist')
            levels = []
            for item in source.level_instructions or []:
                price = price_value(item.get('trigger_level'))
                if item.get('direction') in {'LONG', 'SHORT'} and price is not None:
                    value = {'direction': item['direction'], 'price': float(price)}
                    if value not in levels:
                        levels.append(value)
            # Query all date events once. No repeated-observation-to-alert inference.
            alerts = list(session.scalars(select(Alert).where(Alert.symbol == symbol,
                Alert.created_at >= start, Alert.created_at < end).order_by(Alert.created_at, Alert.id)))
            forming = [row for row in alerts if row.alert_type in FORMING and
                       row.strategy_version == VERSION and row.transition_number is not None and row.snapshot]
            baseline = None
            if not forming:
                baseline = session.scalar(select(BaselineSymbolDay).join(BaselineRun,
                    BaselineRun.id == BaselineSymbolDay.baseline_run_id).where(
                    BaselineSymbolDay.symbol == symbol, BaselineSymbolDay.market_date == day,
                    BaselineSymbolDay.strategy_version == VERSION,
                    BaselineSymbolDay.status == 'COMPLETED', BaselineRun.run_type == 'LIVE_RECORDED_UNIVERSE'
                ).order_by(BaselineSymbolDay.updated_at.desc(), BaselineSymbolDay.id.desc()).limit(1))
            events = []
            for row in forming:
                snap = row.snapshot
                at = datetime.fromisoformat(snap['evaluated_at']) if snap.get('evaluated_at') else _utc(row.created_at)
                candle_at = _utc(row.decision_candle_at) if row.decision_candle_at else None
                if not candle_at or not start <= at < end or candle_at > at:
                    continue
                frames = snap.get('frames', {})
                close, vwap = snap.get('price'), frames.get('3m', {}).get('vwap')
                events.append({'id': f'alert-{row.id}', 'type': row.alert_type, 'timestamp': iso(at),
                    'candle_at': iso(candle_at), 'price': finite(close),
                    'context_10m': frames.get('10m', {}).get('context'),
                    'vwap_position': ('ABOVE' if close > vwap else 'BELOW' if close < vwap else 'AT')
                        if close is not None and vwap is not None else None,
                    'origin': 'Recorded scanner alert', 'outcome': empty_outcome()})
            if baseline:
                episodes = list(session.scalars(select(BaselineEpisode).where(
                    BaselineEpisode.symbol_day_id == baseline.id).order_by(BaselineEpisode.first_forming_at)))
                evaluations = { _utc(row.evaluated_at): row for row in session.scalars(select(BaselineEvaluation).where(
                    BaselineEvaluation.symbol_day_id == baseline.id))}
                for row in episodes:
                    at = _utc(row.first_forming_at)
                    if not start <= at < end or row.setup_state not in FORMING:
                        continue
                    evaluation = evaluations.get(at)
                    # Baseline evaluates completed 3m candles at their closing boundary.
                    candle_at = at - timedelta(minutes=3)
                    price, vwap = row.observation_price, evaluation.vwap if evaluation else None
                    events.append({'id': f'episode-{row.id}', 'type': row.setup_state, 'timestamp': iso(at),
                        'candle_at': iso(candle_at), 'price': finite(price), 'context_10m': row.context_10m,
                        'vwap_position': ('ABOVE' if price > vwap else 'BELOW' if price < vwap else 'AT')
                            if price is not None and vwap is not None else None,
                        'origin': 'Historical baseline episode', 'outcome': empty_outcome()})
            # Level evidence itself proves structured instructions existed at crossing,
            # even if a later same-day replacement removed that level from the upload.
            for row in alerts:
                snap = row.snapshot or {}
                if (not row.level_key or row.alert_type not in {'WATCHLIST_LEVEL_LONG', 'WATCHLIST_LEVEL_SHORT'}
                        or snap.get('trading_date') != day or price_value(snap.get('trigger_level')) is None):
                    continue
                at = datetime.fromisoformat(snap['crossing_timestamp'])
                if not start <= at < end:
                    continue
                events.append({'id': f'level-{row.id}', 'type': row.alert_type, 'timestamp': iso(at),
                    'candle_at': None, 'price': finite(snap.get('price')),
                    'trigger_level': float(price_value(snap['trigger_level'])),
                    'origin': 'Recorded level crossing', 'outcome': empty_outcome()})

            candles, _ = self._research_candles(session, symbol, start, end, forming)
            baseline_frames = None
            if baseline:
                baseline_frames = self._baseline_candles(session, baseline, start, end)
                # A baseline must use its own frozen source, never an unrelated feed.
                candles = baseline_frames
            # Outcome queries are batched, never one SQL request per marker.
            if forming:
                self._live_outcomes(session, events, forming, symbol, start, end)
            elif baseline:
                # Use frozen replay bars for exact baseline horizon checks, not a different feed.
                frames = baseline_frames or self._baseline_candles(session, baseline, start, end)
                future_bars = [{'at': datetime.fromisoformat(row['timestamp'])} for row in frames['3m']]
                by_id = {f'episode-{row.id}': row for row in episodes}
                for item in events:
                    row = by_id.get(item['id'])
                    if row is not None and row.evaluated_at:
                        at = datetime.fromisoformat(item['timestamp'])
                        future = [bar for bar in future_bars if bar['at'] >= at][:min(10, row.available_future_bars or 0)]
                        item['outcome'] = mapped_outcome({'return_3': row.return_after_3_bars,
                            'return_5': row.return_after_5_bars, 'return_10': row.return_after_10_bars,
                            'best': row.maximum_favorable_excursion, 'adverse': row.maximum_adverse_excursion}, future, at)
            # Never snap a marker across a missing bar or infer it from chart prices.
            timestamps = {datetime.fromisoformat(row['timestamp']) for row in candles['3m']}
            for item in events:
                at = datetime.fromisoformat(item['timestamp'])
                anchor = (datetime.fromisoformat(item['candle_at']) if item['candle_at'] else
                          at.replace(minute=at.minute - at.minute % 3, second=0, microsecond=0))
                item['chart_time'] = iso(anchor) if anchor in timestamps else None
            events.sort(key=lambda item: (item['timestamp'], item['id']))
            return {'date': day, 'symbol': symbol, 'timezone': str(ZONE), 'levels': levels,
                    'candles_10m': candles['10m'], 'candles_3m': candles['3m'], 'events': events,
                    'event_basis': 'Recorded scanner alerts' if forming else
                        'Historical baseline episodes' if baseline else 'No persisted FORMING events',
                    'chart_note': 'Retrospective stored candles; later revisions may differ from alert-time evidence.',
                    'legacy_date': upload.trading_date is None}

    @staticmethod
    def _research_candles(session, symbol, start, end, alerts):
        # One consistent provider/feed/session; no mixed-feed candle reconstruction.
        key = None
        if alerts:
            snap = alerts[0].snapshot
            key = (snap.get('provider'), snap.get('feed'), snap.get('session_policy'))
        query = select(ResearchCandle).where(ResearchCandle.symbol == symbol,
            ResearchCandle.candle_at >= start, ResearchCandle.candle_at < end,
            ResearchCandle.timeframe.in_(('3m', '10m')))
        if key is None:
            latest = session.scalar(query.order_by(ResearchCandle.captured_at.desc(), ResearchCandle.id.desc()).limit(1))
            key = (latest.provider, latest.feed, latest.session_policy) if latest else None
        if key is None:
            return {'3m': [], '10m': []}, None
        query = query.where(ResearchCandle.provider == key[0], ResearchCandle.feed == key[1],
                            ResearchCandle.session_policy == key[2])
        ranked = query.with_only_columns(ResearchCandle.id, func.row_number().over(
            partition_by=(ResearchCandle.timeframe, ResearchCandle.candle_at),
            order_by=(ResearchCandle.captured_at.desc(), ResearchCandle.id.desc())).label('rank')).subquery()
        rows = session.scalars(select(ResearchCandle).join(ranked, ranked.c.id == ResearchCandle.id)
            .where(ranked.c.rank == 1).order_by(ResearchCandle.candle_at)).all()
        result = {'3m': [], '10m': []}
        for row in rows:
            if any(finite(getattr(row, field)) is None for field in ('open', 'high', 'low', 'close')):
                continue
            result[row.timeframe].append({'timestamp': iso(row.candle_at),
                                         **{field: finite(getattr(row, field)) for field in FIELDS}})
        return result, key

    @staticmethod
    def _baseline_candles(session, baseline, start, end):
        from strategy_lab.service import StrategyLabService
        replay = session.get(StrategyReplaySession, baseline.replay_id) if baseline.replay_id else None
        if replay is None or 'market_timezone' not in replay.session_configuration:
            return {'3m': [], '10m': []}
        # Existing causal aggregation/indicators only; no detector or provider call.
        lab = StrategyLabService(session.bind, None)
        source_frame = lab._source_frame(session, replay)
        if source_frame.empty:
            return {'3m': [], '10m': []}
        source = MarketSource(replay.provider, replay.feed, 'Stored replay snapshot',
                              replay.session_configuration['market_timezone'])
        frames = lab._calculated_from_frame(source_frame, source, end)
        complete_through = min(end, source_frame.index.max().to_pydatetime() + timedelta(minutes=1))
        return {tf: [{'timestamp': at.isoformat(), **{field: finite(row.get(field)) for field in FIELDS}}
                    for at, row in frame.iterrows() if start <= at.to_pydatetime() < end
                    and at.to_pydatetime() + timedelta(minutes=int(tf[:-1])) <= complete_through]
                for tf, frame in frames.items()}

    @staticmethod
    def _live_outcomes(session, events, alerts, symbol, start, end):
        observations = session.execute(select(ResearchObservation, ResearchOutcome).join(
            ResearchOutcome, ResearchOutcome.observation_id == ResearchObservation.id).where(
            ResearchObservation.symbol == symbol, ResearchObservation.observed_at >= start,
            ResearchObservation.observed_at < end, ResearchObservation.strategy_version == VERSION)).all()
        # One batched candle read supports each outcome's original captured-at cutoff.
        candles = list(session.scalars(select(ResearchCandle).where(ResearchCandle.symbol == symbol,
            ResearchCandle.timeframe == '3m', ResearchCandle.candle_at >= start,
            ResearchCandle.candle_at <= datetime.combine(start.astimezone(ZONE).date(), time(16), ZONE)).order_by(ResearchCandle.candle_at,
                ResearchCandle.captured_at.desc(), ResearchCandle.id.desc()))) if observations else []
        event_by_id = {item['id']: item for item in events}
        for alert in alerts:
            item = event_by_id.get(f'alert-{alert.id}')
            if item is None:
                continue
            snap = alert.snapshot
            match = next(((obs, outcome) for obs, outcome in observations
                if _utc(obs.observed_at) == _utc(alert.created_at)
                and obs.three_min_candle_at and _utc(obs.three_min_candle_at) == _utc(alert.decision_candle_at)
                and obs.setup_state == alert.alert_type and obs.price == item['price']
                and (obs.provider, obs.feed, obs.session_policy) ==
                    (snap.get('provider'), snap.get('feed'), snap.get('session_policy'))), None)
            if match is None:
                continue
            obs, outcome = match
            selected = {}
            for row in candles:
                at = _utc(row.candle_at)
                if (at <= _utc(alert.decision_candle_at) or _utc(row.captured_at) > _utc(outcome.evaluated_at)
                        or (row.provider, row.feed, row.session_policy) != (obs.provider, obs.feed, obs.session_policy)):
                    continue
                selected.setdefault(at, row)
            future = list(selected.values())[:10]
            # Partial bars cannot be advertised as completed elapsed horizons.
            usable = []
            for row in future:
                if _utc(row.captured_at) < _utc(row.candle_at) + timedelta(minutes=3):
                    break
                usable.append({'at': _utc(row.candle_at)})
            item['outcome'] = mapped_outcome({'return_3': outcome.future_3_candle_return,
                'return_5': outcome.future_5_candle_return, 'return_10': outcome.future_10_candle_return,
                'best': outcome.maximum_favorable_excursion, 'adverse': outcome.maximum_adverse_excursion},
                usable, datetime.fromisoformat(item['timestamp']))
