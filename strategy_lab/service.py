from datetime import date, datetime, time, timedelta, timezone
import math
import re
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import (StrategyReplayCandle, StrategyReplayObservation,
                                     StrategyReplaySession)
from ripster_scanner.candle_model import CandleSeries, MarketSource, frame_of
from ripster_scanner.candles import resample_candles
from ripster_scanner.config import forming_thresholds
from ripster_scanner.forming import detect_forming
from ripster_scanner.indicators import add_emas, add_vwap
from ripster_scanner.market_context import analyze_trend
from ripster_scanner.entry_context import analyze_entry_context
from ripster_scanner.strategy import strategy_version_id
from .config import load_settings
from .domain import AssetType, BoundedMarketView, Instrument, ReplayDataUnavailable
from .market_calendar import USEquityMarketCalendar

DECISIONS = {'NOT_YET', 'INTERESTING', 'WOULD_CONSIDER_ENTRY'}
SYMBOL = re.compile(r'^[A-Z][A-Z0-9.-]{0,19}$')


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value):
    return _aware(value).isoformat() if value else None


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


class StrategyLabService:
    def __init__(self, engine, provider, *, equity_calendar=None):
        self.engine = engine
        self.provider = provider
        self.equity_calendar = equity_calendar or USEquityMarketCalendar()
        self.settings = load_settings()

    def capabilities(self):
        return {'asset_types': {
            'EQUITY': {'historical_replay': self.provider.supports(AssetType.EQUITY)},
            'FUTURE': {'historical_replay': self.provider.supports(AssetType.FUTURE),
                       'instrument': 'MES',
                       'limitation': None if self.provider.supports(AssetType.FUTURE) else
                       'Configured Alpaca/IEX provider has no historical futures capability.'}},
            'defaults': {'timezone': self.settings.timezone, 'start': self.settings.start,
                         'end': self.settings.end,
                         'warmup_calendar_days': self.settings.warmup_calendar_days}}

    @staticmethod
    def _local_boundary(market_date, clock, zone):
        parsed = time.fromisoformat(clock)
        if parsed.second or parsed.microsecond or parsed.tzinfo:
            raise ValueError('Replay clocks must use HH:MM')
        return datetime.combine(market_date, parsed, zone)

    def create(self, instrument, asset_type, market_date, start=None, end=None,
               blind_mode=True):
        symbol = instrument.strip().upper()
        if not SYMBOL.fullmatch(symbol):
            raise ValueError('Invalid instrument symbol')
        kind = AssetType(asset_type)
        if kind == AssetType.FUTURE and symbol != 'MES':
            raise ValueError('Strategy Lab V1 accepts MES as the futures research instrument')
        if not self.provider.supports(kind):
            # Invoke the provider only to obtain its specific capability explanation.
            raise ReplayDataUnavailable(
                'MES futures history is unavailable from the configured Alpaca/IEX provider. '
                'A provider with historical one-minute futures bars, contract identity/roll metadata, '
                'and futures-session semantics is required.')
        day = date.fromisoformat(market_date)
        if kind == AssetType.EQUITY:
            self.equity_calendar.validate_for_replay(day)
        zone = ZoneInfo(self.settings.timezone)
        default_start = self.settings.equity_start if kind == AssetType.EQUITY else self.settings.start
        visible_start = self._local_boundary(day, start or default_start, zone)
        visible_end = self._local_boundary(day, end or self.settings.end, zone)
        if visible_start >= visible_end:
            raise ValueError('Replay start must precede end')
        fetch_start = visible_start - timedelta(days=self.settings.warmup_calendar_days)
        fetch_end = visible_end + timedelta(minutes=3 * self.settings.outcome_bars)
        data = self.provider.fetch_range(Instrument(symbol, kind), fetch_start, fetch_end)
        if data.frame.empty:
            raise ReplayDataUnavailable(
                'The US equity market was expected to be open, but the configured provider '
                'returned no usable historical data.',
                details={'error': 'NO_DATA', 'message':
                    'The US equity market was expected to be open, but the configured provider '
                    'returned no usable historical data.', 'selected_date': day.isoformat(),
                    'market': 'US_EQUITY' if kind == AssetType.EQUITY else kind.value,
                    'session_status': 'OPEN'})
        required = {'open', 'high', 'low', 'close', 'volume'}
        if not required.issubset(data.frame.columns) or data.frame.index.tz is None:
            raise ReplayDataUnavailable('Provider returned an invalid normalized candle set')
        now = datetime.now(timezone.utc)
        strategy = strategy_version_id(forming_thresholds()) if kind == AssetType.EQUITY else None
        config = {'source_timeframe': '1m', 'timestamp_semantics': 'candle_start',
            'visible_timezone': str(zone), 'market_timezone': data.source.timezone,
            'aggregation': {'3m': 'day-aligned 00,03,06...', '10m': 'day-aligned 00,10,20...'},
            'warmup_calendar_days': self.settings.warmup_calendar_days,
            'vwap_reset': f'midnight {data.source.timezone}',
            'forming_evaluation': kind == AssetType.EQUITY}
        with Session(self.engine) as session, session.begin():
            replay = StrategyReplaySession(instrument=symbol, asset_type=kind.value,
                market_date=day.isoformat(), timezone=str(zone),
                visible_start=visible_start.astimezone(timezone.utc),
                visible_end=visible_end.astimezone(timezone.utc),
                current_replay_time=visible_start.astimezone(timezone.utc),
                strategy_version=strategy, provider=data.source.provider, feed=data.source.feed,
                session_configuration=config, status='CREATED', blind_mode=bool(blind_mode),
                outcome_revealed=False, created_at=now, updated_at=now)
            session.add(replay)
            session.flush()
            for at, row in data.frame.sort_index().iterrows():
                session.add(StrategyReplayCandle(replay_id=replay.id,
                    candle_at=at.to_pydatetime().astimezone(timezone.utc),
                    open=float(row.open), high=float(row.high), low=float(row.low),
                    close=float(row.close), volume=float(row.volume),
                    trade_count=_finite(row.get('trade_count'))))
            replay_id = replay.id
        return self.get(replay_id)

    def _row(self, session, replay_id):
        row = session.get(StrategyReplaySession, replay_id)
        if row is None:
            raise KeyError('Replay not found')
        return row

    def _source_frame(self, session, replay):
        rows = session.scalars(select(StrategyReplayCandle).where(
            StrategyReplayCandle.replay_id == replay.id).order_by(
            StrategyReplayCandle.candle_at)).all()
        market_zone = replay.session_configuration['market_timezone']
        index = pd.DatetimeIndex([_aware(row.candle_at) for row in rows]).tz_convert(market_zone)
        return pd.DataFrame([{name: getattr(row, name) for name in
            ('open', 'high', 'low', 'close', 'volume', 'trade_count')} for row in rows], index=index)

    def _calculated(self, session, replay, at=None):
        at = _aware(at or replay.current_replay_time)
        source = MarketSource(replay.provider, replay.feed,
            'Replay snapshot; bounded one-minute candles', replay.session_configuration['market_timezone'])
        return self._calculated_from_frame(self._source_frame(session, replay), source, at)

    @staticmethod
    def _calculated_from_frame(source_frame, source, at):
        bounded = BoundedMarketView(source_frame, at).frame
        result = {}
        for label, timeframe in (('3m', '3min'), ('10m', '10min')):
            aggregated = frame_of(resample_candles(CandleSeries(bounded, source), timeframe))
            calculated = frame_of(add_vwap(add_emas(CandleSeries(aggregated, source)))) if not aggregated.empty else aggregated
            result[label] = calculated
        return result

    @staticmethod
    def _candles(frame, visible_start, visible_end, current, display_timezone):
        start = _aware(visible_start)
        end = _aware(visible_end)
        local = frame.index.tz_convert(display_timezone)
        start_local = start.astimezone(ZoneInfo(display_timezone))
        end_local = end.astimezone(ZoneInfo(display_timezone))
        earlier_dates = sorted({at.date() for at in local
                                if at.date() < start_local.date()})
        previous_date = earlier_dates[-1] if earlier_dates else None
        return [{'timestamp': at.isoformat(), **{name: _finite(row.get(name)) for name in
            ('open', 'high', 'low', 'close', 'volume', 'ema_5', 'ema_12', 'ema_34', 'ema_50', 'vwap')}}
            for at, row in frame.iterrows()
            if ((previous_date is not None and
                 at.tz_convert(display_timezone).date() == previous_date and
                 start_local.timetz().replace(tzinfo=None) <=
                 at.tz_convert(display_timezone).time().replace(tzinfo=None) <
                 end_local.timetz().replace(tzinfo=None)) or
                (at.to_pydatetime().astimezone(timezone.utc) >= start and
                 at.to_pydatetime().astimezone(timezone.utc) < current))]

    def _dto(self, session, replay):
        current = _aware(replay.current_replay_time)
        calculated = self._calculated(session, replay, current)
        ten = calculated['10m']
        three = calculated['3m']
        context = analyze_trend(ten)['trend'] if not ten.empty else 'NO DATA'
        state, reason = 'NONE', None
        if replay.asset_type == AssetType.EQUITY.value and not three.empty:
            forming = detect_forming(context, three, forming_thresholds())
            state, reason = forming.state.value, forming.reason
        observations = session.scalars(select(StrategyReplayObservation).where(
            StrategyReplayObservation.replay_id == replay.id).order_by(
            StrategyReplayObservation.replay_time, StrategyReplayObservation.id)).all()
        visible_start = _aware(replay.visible_start)
        markers = self._forming_markers(session, replay, current) if replay.asset_type == 'EQUITY' else []
        return {'id': replay.id, 'instrument': replay.instrument, 'asset_type': replay.asset_type,
            'market_date': replay.market_date, 'timezone': replay.timezone,
            'visible_start': _iso(replay.visible_start), 'visible_end': _iso(replay.visible_end),
            'current_replay_time': _iso(replay.current_replay_time), 'status': replay.status,
            'blind_mode': replay.blind_mode, 'outcome_revealed': replay.outcome_revealed,
            'provider': replay.provider, 'feed': replay.feed,
            'strategy_version': replay.strategy_version,
            'session_configuration': replay.session_configuration,
            'context_10m': context, 'state_3m': state, 'detector_reason': reason,
            'forming_markers': markers,
            'candles_3m': self._candles(three, visible_start, replay.visible_end, current,
                                        replay.timezone),
            'candles_10m': self._candles(ten, visible_start, replay.visible_end, current,
                                         replay.timezone),
            'observations': [self._observation(row) for row in observations]}

    def _forming_markers(self, session, replay, current):
        start = _aware(replay.visible_start)
        source_frame = self._source_frame(session, replay)
        source = MarketSource(replay.provider, replay.feed,
            'Replay snapshot; bounded one-minute candles', replay.session_configuration['market_timezone'])
        cursor, previous, markers = start + timedelta(minutes=3), 'NONE', []
        while cursor <= current:
            calculated = self._calculated_from_frame(source_frame, source, cursor)
            if calculated['3m'].empty or calculated['10m'].empty:
                cursor += timedelta(minutes=3)
                continue
            context = analyze_trend(calculated['10m'])['trend']
            state = detect_forming(context, calculated['3m'], forming_thresholds()).state.value
            if state != 'NONE' and state != previous:
                markers.append({'timestamp': (cursor - timedelta(minutes=3)).isoformat(),
                                'state': state})
            previous = state
            cursor += timedelta(minutes=3)
        return markers

    def get(self, replay_id):
        with Session(self.engine) as session:
            return self._dto(session, self._row(session, replay_id))

    def list(self, limit=50):
        with Session(self.engine) as session:
            rows = session.scalars(select(StrategyReplaySession).order_by(
                StrategyReplaySession.updated_at.desc()).limit(limit)).all()
            return [{'id': row.id, 'instrument': row.instrument, 'asset_type': row.asset_type,
                'market_date': row.market_date, 'current_replay_time': _iso(row.current_replay_time),
                'status': row.status, 'blind_mode': row.blind_mode} for row in rows]

    def move(self, replay_id, direction=None, seek=None):
        with Session(self.engine) as session, session.begin():
            replay = self._row(session, replay_id)
            start, end, current = map(_aware, (replay.visible_start, replay.visible_end,
                                               replay.current_replay_time))
            if seek is not None:
                target = datetime.fromisoformat(seek)
                if target.tzinfo is None:
                    raise ValueError('Seek time must include timezone')
                target = target.astimezone(timezone.utc)
                elapsed = (target - start).total_seconds()
                if target < start or target > end or elapsed % 180:
                    raise ValueError('Seek must be a 3-minute boundary inside the replay range')
            else:
                target = current + timedelta(minutes=3 * direction)
                target = min(end, max(start, target))
            replay.current_replay_time = target
            replay.status = 'IN_PROGRESS' if target < end else 'COMPLETED'
            replay.updated_at = datetime.now(timezone.utc)
        return self.get(replay_id)

    def baseline_evaluation(self, replay_id, replay_time):
        """Lean replay-clock step for historical baseline collection.

        It uses the same BoundedMarketView, aggregation, indicators, context,
        and frozen detector as the visual replay without building markers/UI DTOs.
        """
        target = datetime.fromisoformat(replay_time) if isinstance(replay_time, str) else replay_time
        if target.tzinfo is None:
            raise ValueError('Baseline replay time must include timezone')
        target = target.astimezone(timezone.utc)
        with Session(self.engine) as session, session.begin():
            replay = self._row(session, replay_id)
            start, end = map(_aware, (replay.visible_start, replay.visible_end))
            if target < start or target > end or (target - start).total_seconds() % 180:
                raise ValueError('Baseline time must be a 3-minute boundary inside replay range')
            replay.current_replay_time = target
            replay.status = 'IN_PROGRESS' if target < end else 'COMPLETED'
            replay.updated_at = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            replay = self._row(session, replay_id)
            calculated = self._calculated(session, replay, target)
            ten, three = calculated['10m'], calculated['3m']
            context = analyze_trend(ten)['trend'] if not ten.empty else 'NO DATA'
            forming = detect_forming(context, three, forming_thresholds()) if not three.empty else None
            latest = three.iloc[-1] if not three.empty else None
            return {'id': replay.id, 'provider': replay.provider, 'feed': replay.feed,
                'context_10m': context,
                'state_3m': forming.state.value if forming else 'NONE',
                'latest_3m': ({'timestamp': three.index[-1].isoformat(),
                    **{name: _finite(latest.get(name)) for name in
                       ('close', 'ema_5', 'ema_12', 'ema_34', 'ema_50', 'vwap')}}
                    if latest is not None else None)}

    def complete(self, replay_id):
        with Session(self.engine) as session, session.begin():
            replay = self._row(session, replay_id)
            replay.status = 'COMPLETED'
            replay.current_replay_time = replay.visible_end
            replay.updated_at = datetime.now(timezone.utc)
        return self.get(replay_id)

    def reveal(self, replay_id):
        with Session(self.engine) as session, session.begin():
            replay = self._row(session, replay_id)
            replay.outcome_revealed = True
            replay.blind_mode = False
            replay.updated_at = datetime.now(timezone.utc)
        return self.outcomes(replay_id)

    @staticmethod
    def _observation(row):
        return {'id': row.id, 'replay_id': row.replay_id, 'instrument': row.instrument,
            'market_date': row.market_date, 'replay_time': _iso(row.replay_time),
            'decision': row.decision, 'free_text_reason': row.free_text_reason,
            'created_at': _iso(row.created_at)}

    def observe(self, replay_id, decision, reason):
        if decision not in DECISIONS:
            raise ValueError('Invalid research decision')
        text = reason.strip()
        if not 1 <= len(text) <= 4000:
            raise ValueError('Why is required and limited to 4000 characters')
        with Session(self.engine) as session, session.begin():
            replay = self._row(session, replay_id)
            calculated = self._calculated(session, replay)
            price = _finite(calculated['3m'].iloc[-1].close) if not calculated['3m'].empty else None
            row = StrategyReplayObservation(replay_id=replay.id, instrument=replay.instrument,
                market_date=replay.market_date, replay_time=replay.current_replay_time,
                decision=decision, free_text_reason=text,
                strategy_version=replay.strategy_version, observed_price=price,
                created_at=datetime.now(timezone.utc))
            session.add(row)
            session.flush()
            result = self._observation(row)
        return result

    def observations(self, replay_id):
        with Session(self.engine) as session:
            self._row(session, replay_id)
            rows = session.scalars(select(StrategyReplayObservation).where(
                StrategyReplayObservation.replay_id == replay_id).order_by(
                StrategyReplayObservation.replay_time, StrategyReplayObservation.id)).all()
            return [self._observation(row) for row in rows]

    def outcomes(self, replay_id):
        with Session(self.engine) as session:
            replay = self._row(session, replay_id)
            if not replay.outcome_revealed:
                raise PermissionError('Outcome remains hidden until explicit reveal')
            full = self._source_frame(session, replay)
            source = MarketSource(replay.provider, replay.feed, 'Replay outcome snapshot',
                                  replay.session_configuration['market_timezone'])
            three = frame_of(resample_candles(CandleSeries(full, source), '3min'))
            rows = session.scalars(select(StrategyReplayObservation).where(
                StrategyReplayObservation.replay_id == replay_id).order_by(
                StrategyReplayObservation.replay_time, StrategyReplayObservation.id)).all()
            output = []
            for observation in rows:
                at = _aware(observation.replay_time)
                future = three[[index.to_pydatetime().astimezone(timezone.utc) >= at
                                for index in three.index]].head(10)
                anchor = observation.observed_price
                measurements = {'return_after_3_bars': None, 'return_after_5_bars': None,
                                'return_after_10_bars': None, 'maximum_up_move': None,
                                'maximum_down_move': None, 'available_future_bars': len(future)}
                if anchor and anchor > 0:
                    for count in (3, 5, 10):
                        if len(future) >= count:
                            measurements[f'return_after_{count}_bars'] = (
                                float(future.iloc[count - 1].close) - anchor) / anchor
                    if len(future):
                        measurements['maximum_up_move'] = (float(future.high.max()) - anchor) / anchor
                        measurements['maximum_down_move'] = (float(future.low.min()) - anchor) / anchor
                output.append({'observation': self._observation(observation),
                               'post_observation_market_movement': measurements})
            return {'replay_id': replay.id, 'label': 'POST-OBSERVATION MARKET MOVEMENT',
                    'items': output}

    def objective_movement(self, replay_id, replay_time, setup_state, price):
        """Calculate objective episode movement from the frozen replay snapshot."""
        from research.repository import calculate_outcome
        at = _aware(replay_time)
        with Session(self.engine) as session:
            replay = self._row(session, replay_id)
            full = self._source_frame(session, replay)
            source = MarketSource(replay.provider, replay.feed,
                                  'Replay baseline snapshot',
                                  replay.session_configuration['market_timezone'])
            three = frame_of(resample_candles(CandleSeries(full, source), '3min'))
            future = three[[index.to_pydatetime().astimezone(timezone.utc) >= at
                            for index in three.index]].head(10)
            candles = [SimpleNamespace(candle_at=index.to_pydatetime(),
                close=float(row.close), high=float(row.high), low=float(row.low))
                for index, row in future.iterrows()]
            observation = SimpleNamespace(price=price, setup_state=setup_state,
                                          three_min_candle_at=at)
            return calculate_outcome(observation, candles)
