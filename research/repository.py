"""Historical read models, versioned rules, and deterministic outcome calculations."""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, exists
from sqlalchemy.orm import Session

from backend.database.models import (ResearchCandle, ResearchObservation,
    ResearchOutcome, RuleProposal, StrategyVersion, ResearchObservationSource,
    SectorSnapshot)
from backend.store import iso
from research.collector import ensure_version
from ripster_scanner.config import forming_thresholds
from ripster_scanner.strategy import STRATEGY_NAME, rule_definitions, strategy_version_id


def _utc(value):
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def observation_dict(row, outcome=None):
    fields = ('id', 'symbol', 'trading_date', 'strategy_version', 'watchlist_source',
              'watchlist_filename', 'sector', 'discovery_sources', 'candle_state',
              'decision_eligible', 'sector_snapshot_id', 'price', 'context_10m', 'context_3m',
              'setup_state', 'detector_reason', 'inside_research_window', 'provider',
              'feed', 'session_policy', 'market_timezone', 'research_timezone',
              'data_status', 'source_timeframe', 'vwap_3m', 'vwap_10m', 'vwap_position_3m',
              'vwap_position_10m', 'volume_3m', 'volume_10m')
    data = {field: getattr(row, field) for field in fields}
    data.update({'observed_at': iso(row.observed_at), 'created_at': iso(row.created_at),
                 'three_min_candle_at': iso(row.three_min_candle_at),
                 'ten_min_candle_at': iso(row.ten_min_candle_at),
                 **{f'ema_{span}_{tf}': getattr(row, f'ema_{span}_{tf}')
                    for tf in ('3m', '10m') for span in (5, 12, 34, 50)}})
    data['outcome'] = outcome_dict(outcome) if outcome else None
    return data


def outcome_dict(row):
    if row is None:
        return None
    fields = ('available_future_candles', 'future_3_candle_return',
              'future_5_candle_return', 'future_10_candle_return',
              'maximum_favorable_excursion', 'maximum_adverse_excursion',
              'time_to_mfe_minutes', 'time_to_mae_minutes')
    return {**{name: getattr(row, name) for name in fields},
            'evaluated_at': iso(row.evaluated_at)}


def _latest_candles(session, symbol, timeframe, *, before, through, provider, feed,
                    session_policy,
                    after=None, limit=240, newest=True):
    query = select(ResearchCandle).where(
        ResearchCandle.symbol == symbol, ResearchCandle.timeframe == timeframe,
        ResearchCandle.provider == provider, ResearchCandle.feed == feed,
        ResearchCandle.session_policy == session_policy,
        ResearchCandle.captured_at <= before, ResearchCandle.candle_at <= through)
    if after is not None:
        query = query.where(ResearchCandle.candle_at > after)
    rows = session.scalars(query.order_by(
                                         ResearchCandle.candle_at.desc() if newest else ResearchCandle.candle_at.asc(),
                                         ResearchCandle.captured_at.desc(),
                                         ResearchCandle.id.desc())).all()
    chosen = {}
    for row in rows:
        at = _utc(row.candle_at)
        if at not in chosen:
            chosen[at] = row
        if len(chosen) >= limit:
            break
    return [chosen[at] for at in sorted(chosen)]


def candle_dict(row):
    return {'timestamp': iso(row.candle_at), 'captured_at': iso(row.captured_at),
            'provider': row.provider, 'feed': row.feed, 'timeframe': row.timeframe,
            'source_timeframe': row.source_timeframe,
            **{name: getattr(row, name) for name in
               ('open', 'high', 'low', 'close', 'volume', 'ema_5', 'ema_12',
                'ema_34', 'ema_50', 'vwap')}}


def calculate_outcome(observation, future):
    """Raw returns and context-oriented excursions over next 10 available 3m bars."""
    data = {'available_future_candles': len(future),
            'future_3_candle_return': None, 'future_5_candle_return': None,
            'future_10_candle_return': None,
            'maximum_favorable_excursion': None, 'maximum_adverse_excursion': None,
            'time_to_mfe_minutes': None, 'time_to_mae_minutes': None}
    price = observation.price
    if price is None or price <= 0:
        return data
    for n in (3, 5, 10):
        if len(future) >= n and future[n - 1].close is not None:
            data[f'future_{n}_candle_return'] = (future[n - 1].close - price) / price
    if len(future) < 10 or observation.setup_state not in ('FORMING_LONG', 'FORMING_SHORT'):
        return data
    direction = 1 if observation.setup_state == 'FORMING_LONG' else -1
    excursions = []
    for candle in future[:10]:
        if candle.high is None or candle.low is None:
            return data
        favorable = ((candle.high - price) / price if direction == 1
                     else (price - candle.low) / price)
        adverse = ((candle.low - price) / price if direction == 1
                   else (price - candle.high) / price)
        excursions.append((favorable, adverse, candle))
    best = max(excursions, key=lambda item: item[0])
    worst = min(excursions, key=lambda item: item[1])
    data['maximum_favorable_excursion'] = max(0.0, best[0])
    data['maximum_adverse_excursion'] = min(0.0, worst[1])
    anchor = _utc(observation.three_min_candle_at)
    if best[0] > 0:
        data['time_to_mfe_minutes'] = (_utc(best[2].candle_at) - anchor).total_seconds() / 60
    if worst[1] < 0:
        data['time_to_mae_minutes'] = (_utc(worst[2].candle_at) - anchor).total_seconds() / 60
    return data


class ResearchRepository:
    def __init__(self, engine):
        self.engine = engine

    def list_observations(self, *, trading_date=None, symbol=None, strategy_version=None,
                          setup_state=None, forming=None, discovery_source=None,
                          sector=None, candle_state=None, decision_eligible=None, limit=200):
        with Session(self.engine) as session:
            query = select(ResearchObservation)
            if trading_date:
                query = query.where(ResearchObservation.trading_date == trading_date)
            if symbol:
                query = query.where(ResearchObservation.symbol == symbol.upper())
            if strategy_version:
                query = query.where(ResearchObservation.strategy_version == strategy_version)
            if setup_state:
                query = query.where(ResearchObservation.setup_state == setup_state)
            if sector:
                query = query.where(ResearchObservation.sector == sector)
            if candle_state:
                query = query.where(ResearchObservation.candle_state == candle_state)
            if decision_eligible is not None:
                query = query.where(ResearchObservation.decision_eligible.is_(decision_eligible))
            if discovery_source:
                query = query.where(exists(select(ResearchObservationSource.id).where(
                    ResearchObservationSource.observation_id == ResearchObservation.id,
                    ResearchObservationSource.source_type == discovery_source)))
            if forming is not None:
                query = query.where(ResearchObservation.setup_state.in_(
                    ('FORMING_LONG', 'FORMING_SHORT')) if forming else
                    ResearchObservation.setup_state == 'NONE')
            rows = session.scalars(query.order_by(ResearchObservation.observed_at.desc(),
                                                  ResearchObservation.id.desc()).limit(limit)).all()
            outcomes = {item.observation_id: item for item in session.scalars(
                select(ResearchOutcome).where(ResearchOutcome.observation_id.in_(
                    [row.id for row in rows])))} if rows else {}
            return [observation_dict(row, outcomes.get(row.id)) for row in rows]

    def observation_detail(self, observation_id):
        with Session(self.engine) as session:
            row = session.get(ResearchObservation, observation_id)
            if row is None:
                return None
            outcome = session.scalar(select(ResearchOutcome).where(
                ResearchOutcome.observation_id == row.id))
            data = observation_dict(row, outcome)
            sector_snapshot = session.get(SectorSnapshot, row.sector_snapshot_id) if row.sector_snapshot_id else None
            data['sector_snapshot'] = ({name: getattr(sector_snapshot, name) for name in
                ('sector', 'symbol_count', 'bullish_count', 'bearish_count', 'mixed_count',
                 'forming_long_count', 'forming_short_count')} if sector_snapshot else None)
            version = session.get(StrategyVersion, row.strategy_version)
            data['rules_at_observation'] = version.rules_snapshot if version else None
            known_at = _utc(row.observed_at)
            for timeframe, anchor, limit in (('3m', row.three_min_candle_at, 240),
                                              ('10m', row.ten_min_candle_at, 120)):
                candles = (_latest_candles(session, row.symbol, timeframe,
                    before=known_at, through=_utc(anchor), provider=row.provider,
                    feed=row.feed, session_policy=row.session_policy,
                    limit=limit) if anchor else [])
                data[f'candles_{timeframe}'] = [candle_dict(item) for item in candles]
            return data

    def analyze_date(self, trading_date: date, *, evaluated_at=None):
        evaluated_at = evaluated_at or datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            rows = session.scalars(select(ResearchObservation).where(
                ResearchObservation.trading_date == trading_date.isoformat(),
                ResearchObservation.inside_research_window.is_(True))).all()
            for observation in rows:
                future = []
                if observation.three_min_candle_at:
                    anchor = _utc(observation.three_min_candle_at)
                    ny_date = anchor.astimezone(ZoneInfo('America/New_York')).date()
                    session_end = datetime.combine(ny_date, time(16, 0),
                                                   ZoneInfo('America/New_York')).astimezone(timezone.utc)
                    future = _latest_candles(session, observation.symbol, '3m',
                        before=evaluated_at, through=session_end, after=anchor,
                        provider=observation.provider, feed=observation.feed,
                        session_policy=observation.session_policy,
                        limit=10, newest=False)
                values = calculate_outcome(observation, future)
                outcome = session.scalar(select(ResearchOutcome).where(
                    ResearchOutcome.observation_id == observation.id))
                if outcome is None:
                    outcome = ResearchOutcome(observation_id=observation.id)
                    session.add(outcome)
                outcome.evaluated_at = evaluated_at
                for key, value in values.items():
                    setattr(outcome, key, value)
            return len(rows)

    def rules(self, thresholds=None):
        thresholds = thresholds or forming_thresholds()
        with Session(self.engine) as session:
            proposals = session.scalars(select(RuleProposal).order_by(
                RuleProposal.created_at.desc(), RuleProposal.id.desc())).all()
            return {'strategy_version': strategy_version_id(thresholds),
                    'strategy_name': STRATEGY_NAME,
                    'rules': rule_definitions(thresholds),
                    'proposals': [self._proposal_dict(item) for item in proposals],
                    'lifecycle': ['PROPOSED', 'EXPERIMENTAL', 'ACTIVE', 'REJECTED', 'RETIRED']}

    @staticmethod
    def _proposal_dict(item):
        return {name: getattr(item, name) for name in
                ('id', 'strategy_version', 'rule_version', 'status', 'name',
                 'description', 'rationale', 'timeframe', 'condition',
                 'threshold_config', 'notes')} | {
                     'created_at': iso(item.created_at), 'updated_at': iso(item.updated_at)}

    def add_proposal(self, values, thresholds=None):
        thresholds = thresholds or forming_thresholds()
        timestamp = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            version = ensure_version(session, thresholds, timestamp)
            session.flush()
            proposal = RuleProposal(strategy_version=version, rule_version=1,
                status='PROPOSED', created_at=timestamp, updated_at=timestamp, **values)
            session.add(proposal)
            session.flush()
            return self._proposal_dict(proposal)
