"""Restartable historical baseline for the frozen Experimental Forming V1 strategy."""

import argparse
from datetime import date, datetime, time, timedelta, timezone
import logging
import os
import statistics
import time as clock
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database.config import make_engine
from backend.database.models import (BaselineDay, BaselineEpisode, BaselineEvaluation,
    BaselineRun, BaselineSymbolDay)
from ripster_scanner.config import forming_thresholds, load_config
from ripster_scanner.strategy import strategy_version_id
from strategy_lab.catalog import HistoricalUniverseRepository
from strategy_lab.market_calendar import USEquityMarketCalendar
from strategy_lab.provider import AlpacaHistoricalReplayProvider
from strategy_lab.service import StrategyLabService

log = logging.getLogger(__name__)
CT = ZoneInfo('America/Chicago')
FORMING = {'FORMING_LONG', 'FORMING_SHORT'}


def completed_sessions(calendar, *, start=None, end=None, last_trading_days=None, now=None):
    if bool(last_trading_days) == bool(start or end):
        raise ValueError('Use either --last-trading-days or both --start and --end')
    latest = calendar.latest_completed(now)
    if last_trading_days:
        if not 1 <= last_trading_days <= 250:
            raise ValueError('--last-trading-days must be in 1..250')
        days = [latest]
        while len(days) < last_trading_days:
            days.append(calendar.adjacent(days[-1], 'previous'))
        return sorted(days)
    if start is None or end is None or start > end:
        raise ValueError('--start and --end must form a valid inclusive range')
    sessions = [value.date() for value in calendar.calendar.sessions_in_range(
        start.isoformat(), min(end, latest).isoformat())]
    return sessions


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _percent(value):
    return None if value is None else round(value * 100, 2)


def _metric(episodes, field, direction):
    eligible = [getattr(row, field) for row in episodes if getattr(row, field) is not None]
    numerator = sum(value > 0 if direction == 'LONG' else value < 0 for value in eligible)
    return {'percentage': round(numerator / len(eligible) * 100, 1) if eligible else None,
            'numerator': numerator, 'denominator': len(eligible),
            'insufficient': len(episodes) - len(eligible),
            'median_percent': _percent(statistics.median(eligible)) if eligible else None}


class HistoricalBaseline:
    def __init__(self, engine, replay_provider=None, *, replay_service=None,
                 provider_retries=None, retry_delay_seconds=None, progress=None):
        self.engine = engine
        self.catalog = HistoricalUniverseRepository(engine)
        self.lab = replay_service or StrategyLabService(engine, replay_provider)
        self.calendar = USEquityMarketCalendar()
        self.strategy_version = strategy_version_id(forming_thresholds())
        self.provider_retries = provider_retries or int(os.getenv('BASELINE_PROVIDER_RETRIES', '3'))
        self.retry_delay = (retry_delay_seconds if retry_delay_seconds is not None else
                            float(os.getenv('BASELINE_RETRY_DELAY_SECONDS', '2')))
        self.progress = progress or (lambda message: log.info(message))

    def _run(self, days):
        start, end = days[0].isoformat(), days[-1].isoformat()
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            run = session.scalar(select(BaselineRun).where(BaselineRun.start_date == start,
                BaselineRun.end_date == end,
                BaselineRun.strategy_version == self.strategy_version))
            if run is None:
                run = BaselineRun(start_date=start, end_date=end,
                    strategy_version=self.strategy_version, status='IN_PROGRESS',
                    trading_days_total=len(days), trading_days_completed=0,
                    symbol_failures=0, created_at=now, updated_at=now)
                session.add(run)
                session.flush()
            elif run.status != 'COMPLETED':
                run.status = 'IN_PROGRESS'
                run.updated_at = now
            run_id = run.id
        return run_id

    def execute(self, days):
        if not days:
            raise ValueError('No completed XNYS trading sessions selected')
        run_id = self._run(days)
        self.progress(f'Historical Strategy Baseline\nStrategy: {self.strategy_version}\n'
                      f'Period: {days[0]} through {days[-1]}')
        for index, day in enumerate(days, 1):
            self._day(run_id, day, index, len(days))
        self._refresh_run(run_id)
        return self.report(run_id)

    def _day(self, run_id, day, day_number, total_days):
        day_text = day.isoformat()
        candidates = self.catalog.candidates_for_date(day_text)
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            row = session.scalar(select(BaselineDay).where(
                BaselineDay.run_id == run_id, BaselineDay.market_date == day_text))
            if row is None:
                row = BaselineDay(run_id=run_id, market_date=day_text,
                    status='PENDING', symbols_total=len(candidates), symbols_completed=0,
                    symbols_failed=0, updated_at=now)
                session.add(row)
            row.symbols_total = len(candidates)
            if not candidates:
                row.status = 'NO_UNIVERSE'
                row.coverage_limitation = 'No historical scanner universe was recorded for this date.'
            row.updated_at = now
        self.progress(f'Trading days: {day_number} / {total_days}\nCurrent date: {day_text}')
        if not candidates:
            self._refresh_run(run_id)
            return
        for number, candidate in enumerate(candidates, 1):
            try:
                self._symbol(day, candidate)
            except Exception as exc:
                self._fail_symbol(day_text, candidate, exc)
                log.warning('Baseline %s %s failed: %s', day_text, candidate['symbol'], exc)
            counts = self._day_counts(day_text)
            self.progress(f'Symbols: {number} / {len(candidates)} · '
                          f'FORMING episodes: LONG {counts["long"]} SHORT {counts["short"]} · '
                          f'Failures: {counts["failed"]}')
        with Session(self.engine) as session, session.begin():
            row = session.scalar(select(BaselineDay).where(
                BaselineDay.run_id == run_id, BaselineDay.market_date == day_text))
            counts = self._day_counts(day_text, session=session)
            row.symbols_completed, row.symbols_failed = counts['completed'], counts['failed']
            row.status = 'COMPLETED_WITH_FAILURES' if counts['failed'] else 'COMPLETED'
            row.updated_at = datetime.now(timezone.utc)
        self._refresh_run(run_id)

    def _create_replay(self, symbol, day):
        error = None
        for attempt in range(1, self.provider_retries + 1):
            try:
                return self.lab.create(symbol, 'EQUITY', day.isoformat(), '08:30', '10:00')
            except Exception as exc:
                error = exc
                if attempt < self.provider_retries:
                    log.warning('Provider attempt %s/%s failed for %s %s; backing off',
                                attempt, self.provider_retries, symbol, day)
                    clock.sleep(self.retry_delay * attempt)
        raise error

    def _symbol(self, day, candidate):
        day_text, symbol = day.isoformat(), candidate['symbol']
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            item = session.scalar(select(BaselineSymbolDay).where(
                BaselineSymbolDay.market_date == day_text,
                BaselineSymbolDay.symbol == symbol,
                BaselineSymbolDay.strategy_version == self.strategy_version))
            if item is not None and item.status == 'COMPLETED':
                return
            if item is None:
                item = BaselineSymbolDay(market_date=day_text, symbol=symbol,
                    strategy_version=self.strategy_version, status='IN_PROGRESS',
                    sector=candidate.get('sector'), provenance=candidate.get('sources', []),
                    created_at=now, updated_at=now)
                session.add(item)
                session.flush()
            else:
                item.status, item.error, item.updated_at = 'IN_PROGRESS', None, now
            symbol_day_id, replay_id = item.id, item.replay_id
        if replay_id is None:
            replay = self._create_replay(symbol, day)
            replay_id = replay['id']
            with Session(self.engine) as session, session.begin():
                item = session.get(BaselineSymbolDay, symbol_day_id)
                item.replay_id, item.updated_at = replay_id, datetime.now(timezone.utc)
        cursor = datetime.combine(day, time(8, 33), CT)
        end = datetime.combine(day, time(10, 0), CT)
        while cursor <= end:
            self._evaluate(symbol_day_id, replay_id, day, cursor)
            cursor += timedelta(minutes=3)
        with Session(self.engine) as session, session.begin():
            for episode in session.scalars(select(BaselineEpisode).where(
                BaselineEpisode.symbol_day_id == symbol_day_id,
                BaselineEpisode.ended_at.is_(None))):
                episode.ended_at = end.astimezone(timezone.utc)
        self._outcomes(symbol_day_id, replay_id)
        with Session(self.engine) as session, session.begin():
            item = session.get(BaselineSymbolDay, symbol_day_id)
            item.status, item.error = 'COMPLETED', None
            item.updated_at = datetime.now(timezone.utc)

    def _evaluate(self, symbol_day_id, replay_id, day, cursor):
        evaluated_at = cursor.astimezone(timezone.utc)
        with Session(self.engine) as session:
            if session.scalar(select(BaselineEvaluation.id).where(
                BaselineEvaluation.symbol_day_id == symbol_day_id,
                BaselineEvaluation.evaluated_at == evaluated_at)):
                return
        replay = self.lab.baseline_evaluation(replay_id, cursor.isoformat())
        latest = replay.get('latest_3m') or {}
        price, state = latest.get('close'), replay['state_3m']
        with Session(self.engine) as session, session.begin():
            previous = session.scalar(select(BaselineEvaluation).where(
                BaselineEvaluation.symbol_day_id == symbol_day_id,
                BaselineEvaluation.evaluated_at < evaluated_at).order_by(
                    BaselineEvaluation.evaluated_at.desc()).limit(1))
            prior_state = previous.state_3m if previous else 'NONE'
            evaluation = BaselineEvaluation(symbol_day_id=symbol_day_id,
                evaluated_at=evaluated_at, context_10m=replay['context_10m'], state_3m=state,
                price=price, ema_5=latest.get('ema_5'), ema_12=latest.get('ema_12'),
                ema_34=latest.get('ema_34'), ema_50=latest.get('ema_50'),
                vwap=latest.get('vwap'), provider=replay['provider'], feed=replay['feed'],
                candle_state='COMPLETED', decision_eligible=price is not None)
            session.add(evaluation)
            if prior_state in FORMING and prior_state != state:
                open_episode = session.scalar(select(BaselineEpisode).where(
                    BaselineEpisode.symbol_day_id == symbol_day_id,
                    BaselineEpisode.setup_state == prior_state,
                    BaselineEpisode.ended_at.is_(None)).order_by(
                        BaselineEpisode.first_forming_at.desc()).limit(1))
                if open_episode:
                    open_episode.ended_at = evaluated_at
            if state in FORMING and state != prior_state:
                session.add(BaselineEpisode(symbol_day_id=symbol_day_id,
                    setup_state=state, first_forming_at=evaluated_at,
                    observation_price=price, context_10m=replay['context_10m'],
                    available_future_bars=0))

    def _outcomes(self, symbol_day_id, replay_id):
        with Session(self.engine) as session:
            episodes = [(row.id, _aware(row.first_forming_at), row.setup_state,
                         row.observation_price) for row in session.scalars(
                select(BaselineEpisode).where(BaselineEpisode.symbol_day_id == symbol_day_id))]
        for episode_id, at, state, price in episodes:
            values = self.lab.objective_movement(replay_id, at, state, price)
            with Session(self.engine) as session, session.begin():
                row = session.get(BaselineEpisode, episode_id)
                row.available_future_bars = values['available_future_candles']
                row.return_after_3_bars = values['future_3_candle_return']
                row.return_after_5_bars = values['future_5_candle_return']
                row.return_after_10_bars = values['future_10_candle_return']
                row.maximum_favorable_excursion = values['maximum_favorable_excursion']
                row.maximum_adverse_excursion = values['maximum_adverse_excursion']
                row.evaluated_at = datetime.now(timezone.utc)

    def _fail_symbol(self, day, candidate, exc):
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            row = session.scalar(select(BaselineSymbolDay).where(
                BaselineSymbolDay.market_date == day,
                BaselineSymbolDay.symbol == candidate['symbol'],
                BaselineSymbolDay.strategy_version == self.strategy_version))
            if row is None:
                row = BaselineSymbolDay(market_date=day, symbol=candidate['symbol'],
                    strategy_version=self.strategy_version, sector=candidate.get('sector'),
                    provenance=candidate.get('sources', []), created_at=now)
                session.add(row)
            row.status, row.error, row.updated_at = 'FAILED', str(exc)[:1000], now

    def _day_counts(self, day, session=None):
        owns = session is None
        session = session or Session(self.engine)
        try:
            base = select(BaselineSymbolDay).where(BaselineSymbolDay.market_date == day,
                BaselineSymbolDay.strategy_version == self.strategy_version)
            rows = session.scalars(base).all()
            ids = [row.id for row in rows]
            states = list(session.scalars(select(BaselineEpisode.setup_state).where(
                BaselineEpisode.symbol_day_id.in_(ids)))) if ids else []
            return {'completed': sum(row.status == 'COMPLETED' for row in rows),
                    'failed': sum(row.status == 'FAILED' for row in rows),
                    'long': states.count('FORMING_LONG'), 'short': states.count('FORMING_SHORT')}
        finally:
            if owns:
                session.close()

    def _refresh_run(self, run_id):
        with Session(self.engine) as session, session.begin():
            run = session.get(BaselineRun, run_id)
            days = session.scalars(select(BaselineDay).where(BaselineDay.run_id == run_id)).all()
            complete = {'COMPLETED', 'COMPLETED_WITH_FAILURES', 'NO_UNIVERSE'}
            run.trading_days_completed = sum(day.status in complete for day in days)
            run.symbol_failures = sum(day.symbols_failed for day in days)
            run.status = 'COMPLETED' if run.trading_days_completed == run.trading_days_total else 'IN_PROGRESS'
            run.updated_at = datetime.now(timezone.utc)

    def report(self, run_id=None):
        with Session(self.engine) as session:
            run = (session.get(BaselineRun, run_id) if run_id else session.scalar(
                select(BaselineRun).order_by(BaselineRun.updated_at.desc()).limit(1)))
            if run is None:
                return None
            symbol_days = session.scalars(select(BaselineSymbolDay).where(
                BaselineSymbolDay.market_date >= run.start_date,
                BaselineSymbolDay.market_date <= run.end_date,
                BaselineSymbolDay.strategy_version == run.strategy_version)).all()
            ids = [row.id for row in symbol_days]
            episodes = session.scalars(select(BaselineEpisode).where(
                BaselineEpisode.symbol_day_id.in_(ids)).order_by(
                    BaselineEpisode.first_forming_at)).all() if ids else []
            evaluations = session.scalar(select(func.count()).select_from(
                BaselineEvaluation).where(BaselineEvaluation.symbol_day_id.in_(ids))) if ids else 0
            days = session.scalars(select(BaselineDay).where(BaselineDay.run_id == run.id).order_by(
                BaselineDay.market_date)).all()
            def direction(name):
                rows = [row for row in episodes if row.setup_state == f'FORMING_{name}']
                excursions = lambda field: [getattr(row, field) for row in rows
                                             if getattr(row, field) is not None]
                return {'episodes': len(rows),
                    'bars_3': _metric(rows, 'return_after_3_bars', name),
                    'bars_5': _metric(rows, 'return_after_5_bars', name),
                    'bars_10': _metric(rows, 'return_after_10_bars', name),
                    'median_favorable_excursion_percent': _percent(statistics.median(
                        excursions('maximum_favorable_excursion'))) if excursions(
                            'maximum_favorable_excursion') else None,
                    'median_adverse_excursion_percent': _percent(statistics.median(
                        excursions('maximum_adverse_excursion'))) if excursions(
                            'maximum_adverse_excursion') else None}
            return {'id': run.id, 'period': {'start': run.start_date, 'end': run.end_date},
                'strategy_version': run.strategy_version, 'status': run.status,
                'coverage': {'trading_days': run.trading_days_total,
                    'trading_days_completed': run.trading_days_completed,
                    'symbols_evaluated': sum(row.status == 'COMPLETED' for row in symbol_days),
                    'eligible_evaluations': evaluations,
                    'symbol_failures': sum(row.status == 'FAILED' for row in symbol_days),
                    'limitations': [{'date': day.market_date,
                        'message': day.coverage_limitation} for day in days
                        if day.coverage_limitation]},
                'forming_long': direction('LONG'), 'forming_short': direction('SHORT'),
                'episodes': [self._episode_dict(row, session) for row in episodes]}

    @staticmethod
    def _episode_dict(row, session):
        symbol_day = session.get(BaselineSymbolDay, row.symbol_day_id)
        return {'id': row.id, 'symbol': symbol_day.symbol,
            'market_date': symbol_day.market_date, 'first_forming_at': _aware(
                row.first_forming_at).isoformat(), 'setup_state': row.setup_state,
            'observation_price': row.observation_price, 'context_10m': row.context_10m,
            'return_after_3_bars': row.return_after_3_bars,
            'return_after_5_bars': row.return_after_5_bars,
            'return_after_10_bars': row.return_after_10_bars,
            'maximum_favorable_excursion': row.maximum_favorable_excursion,
            'maximum_adverse_excursion': row.maximum_adverse_excursion,
            'available_future_bars': row.available_future_bars,
            'strategy_version': symbol_day.strategy_version}

    def catch_up(self, maximum_days):
        latest = self.calendar.latest_completed()
        days = [latest]
        while len(days) < maximum_days:
            days.append(self.calendar.adjacent(days[-1], 'previous'))
        days = sorted(days)
        missing = []
        with Session(self.engine) as session:
            for day in days:
                candidates = self.catalog.candidates_for_date(day.isoformat())
                if not candidates:
                    continue
                completed = set(session.scalars(select(BaselineSymbolDay.symbol).where(
                    BaselineSymbolDay.market_date == day.isoformat(),
                    BaselineSymbolDay.strategy_version == self.strategy_version,
                    BaselineSymbolDay.status == 'COMPLETED')))
                if any(item['symbol'] not in completed for item in candidates):
                    missing.append(day)
        return self.execute(missing) if missing else self.report()


def make_baseline():
    config = load_config(symbols=())
    return HistoricalBaseline(make_engine(),
        AlpacaHistoricalReplayProvider(config.api_key, config.secret_key))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Frozen FORMING historical baseline')
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--end', type=date.fromisoformat)
    parser.add_argument('--last-trading-days', type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    baseline = make_baseline()
    days = completed_sessions(baseline.calendar, start=args.start, end=args.end,
                              last_trading_days=args.last_trading_days)
    report = baseline.execute(days)
    log.info('Baseline complete: run=%s days=%s/%s long=%s short=%s failures=%s',
        report['id'], report['coverage']['trading_days_completed'],
        report['coverage']['trading_days'], report['forming_long']['episodes'],
        report['forming_short']['episodes'], report['coverage']['symbol_failures'])


if __name__ == '__main__':
    main()
