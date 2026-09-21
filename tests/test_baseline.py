"""Deterministic frozen-strategy historical baseline tests."""

from datetime import date, datetime, timezone
import unittest
from zoneinfo import ZoneInfo
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.api import create_app
from backend.database.models import (BaselineDay, BaselineEpisode, BaselineEvaluation,
    ActiveUniverseMember, BaselineRun, BaselineSymbolDay, DiscoveryMembership,
    WatchlistUpload)
from backend.internal_api import create_internal_app
from db_support import test_store
from research.baseline import HistoricalBaseline, completed_sessions, main
from ripster_scanner.config import forming_thresholds
from ripster_scanner.strategy import strategy_version_id
from strategy_lab.market_calendar import USEquityMarketCalendar
from strategy_lab.domain import ReplayDataUnavailable
from strategy_lab.service import StrategyLabService
from test_strategy_lab import MemoryProvider


UTC = timezone.utc


class FakeReplay:
    def __init__(self, *, fail_symbol=None, fail_once_at=None):
        self.next_id = 1
        self.symbols = {}
        self.moves = []
        self.fail_symbol = fail_symbol
        self.fail_once_at = fail_once_at
        self.failed_once = False

    def create(self, symbol, asset_type, market_date, start, end):
        if symbol == self.fail_symbol:
            raise RuntimeError('fixture provider failure')
        replay_id = self.next_id
        self.next_id += 1
        self.symbols[replay_id] = symbol
        return {'id': replay_id}

    def move(self, replay_id, seek):
        at = datetime.fromisoformat(seek)
        if self.fail_once_at == at.strftime('%H:%M') and not self.failed_once:
            self.failed_once = True
            raise RuntimeError('fixture interruption')
        self.moves.append((replay_id, at))
        step = int(((at.hour * 60 + at.minute) - (8 * 60 + 33)) / 3)
        state = ('FORMING_LONG' if 1 <= step <= 3 else
                 'FORMING_SHORT' if 5 <= step <= 6 else 'NONE')
        candle_at = at.timestamp() - 180
        return {'id': replay_id, 'provider': 'Memory', 'feed': 'FIXTURE',
            'context_10m': 'BULLISH' if state != 'FORMING_SHORT' else 'BEARISH',
            'state_3m': state,
            'candles_3m': [{'timestamp': datetime.fromtimestamp(candle_at, tz=at.tzinfo).isoformat(),
                'close': 100.0, 'ema_5': 100.1, 'ema_12': 100.0,
                'ema_34': 99.5, 'ema_50': 99.0, 'vwap': 99.8}]}

    def baseline_evaluation(self, replay_id, seek):
        value = self.move(replay_id, seek)
        value['latest_3m'] = value['candles_3m'][-1]
        return value

    def objective_movement(self, replay_id, at, state, price):
        if state == 'FORMING_LONG':
            return {'available_future_candles': 10, 'future_3_candle_return': .01,
                'future_5_candle_return': .02, 'future_10_candle_return': None,
                'maximum_favorable_excursion': .03, 'maximum_adverse_excursion': -.005,
                'time_to_mfe_minutes': 9, 'time_to_mae_minutes': 3}
        return {'available_future_candles': 10, 'future_3_candle_return': -.01,
            'future_5_candle_return': -.02, 'future_10_candle_return': -.03,
            'maximum_favorable_excursion': .04, 'maximum_adverse_excursion': -.006,
            'time_to_mfe_minutes': 12, 'time_to_mae_minutes': 6}


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.day = date(2026, 9, 18)
        at = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)
        with self.store.session() as session:
            session.add(DiscoveryMembership(trading_date=self.day.isoformat(), symbol='AAA',
                source_type='MOST_ACTIVE', provider='Fixture', first_seen_at=at,
                last_seen_at=at, active=True, metrics={}))

    def baseline(self, fake=None):
        return HistoricalBaseline(self.store.engine, replay_service=fake or FakeReplay(),
            provider_retries=1, retry_delay_seconds=0, progress=lambda _: None)

    def test_completed_trading_days_exclude_weekends_holidays_and_future(self):
        calendar = USEquityMarketCalendar()
        now = datetime(2026, 9, 19, 20, tzinfo=UTC)
        recent = completed_sessions(calendar, last_trading_days=3, now=now)
        self.assertEqual(recent, [date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)])
        july = completed_sessions(calendar, start=date(2026, 7, 2), end=date(2026, 7, 6), now=now)
        self.assertEqual(july, [date(2026, 7, 2), date(2026, 7, 6)])

    def test_window_completed_candles_episode_dedup_and_outcomes(self):
        fake = FakeReplay()
        report = self.baseline(fake).execute([self.day])
        self.assertEqual(len(fake.moves), 30)
        self.assertEqual(fake.moves[0][1].strftime('%H:%M'), '08:33')
        self.assertEqual(fake.moves[-1][1].strftime('%H:%M'), '10:00')
        self.assertEqual(report['forming_long']['episodes'], 1)
        self.assertEqual(report['forming_short']['episodes'], 1)
        self.assertEqual(report['forming_long']['bars_5'], {
            'percentage': 100.0, 'numerator': 1, 'denominator': 1,
            'insufficient': 0, 'median_percent': 2.0})
        self.assertEqual(report['forming_long']['bars_10']['denominator'], 0)
        self.assertEqual(report['forming_long']['bars_10']['insufficient'], 1)
        self.assertEqual(report['forming_short']['bars_10']['percentage'], 100.0)
        with self.store.session() as session:
            evaluations = session.scalars(select(BaselineEvaluation).order_by(
                BaselineEvaluation.evaluated_at)).all()
            self.assertTrue(all(row.candle_state == 'COMPLETED' for row in evaluations))
            episodes = session.scalars(select(BaselineEpisode).order_by(
                BaselineEpisode.first_forming_at)).all()
            self.assertEqual([row.setup_state for row in episodes],
                             ['FORMING_LONG', 'FORMING_SHORT'])

    def test_rerun_is_idempotent_and_strategy_versions_coexist(self):
        baseline = self.baseline()
        first = baseline.execute([self.day])
        second = baseline.execute([self.day])
        self.assertEqual(first['id'], second['id'])
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(BaselineEvaluation)), 30)
            self.assertEqual(session.scalar(select(func.count()).select_from(BaselineEpisode)), 2)
        another = self.baseline()
        another.strategy_version = 'experimental-forming-v2/fixture'
        another.execute([self.day])
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(BaselineSymbolDay)), 2)

    def test_interrupted_symbol_resumes_without_duplicate_evaluations(self):
        fake = FakeReplay(fail_once_at='09:00')
        baseline = self.baseline(fake)
        first = baseline.execute([self.day])
        self.assertEqual(first['coverage']['symbol_failures'], 1)
        second = baseline.execute([self.day])
        self.assertEqual(second['coverage']['symbol_failures'], 0)
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(BaselineEvaluation)), 30)
            self.assertEqual(session.scalar(select(func.count()).select_from(BaselineEpisode)), 2)

    def test_one_symbol_failure_does_not_abort_other_symbols(self):
        at = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)
        with self.store.session() as session:
            session.add(DiscoveryMembership(trading_date=self.day.isoformat(), symbol='BAD',
                source_type='TOP_GAINER', provider='Fixture', first_seen_at=at,
                last_seen_at=at, active=True, metrics={}))
        report = self.baseline(FakeReplay(fail_symbol='BAD')).execute([self.day])
        self.assertEqual(report['coverage']['symbols_evaluated'], 1)
        self.assertEqual(report['coverage']['symbol_failures'], 1)

    def test_private_api_available_and_public_api_denied(self):
        report = self.baseline().execute([self.day])
        private = TestClient(create_internal_app(store=self.store,
            replay_provider=MemoryProvider()), base_url='http://localhost')
        public = TestClient(create_app(store=self.store), base_url='http://localhost')
        response = private.get('/api/internal/strategy-lab/baseline')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], report['id'])
        self.assertEqual(private.get('/api/internal/strategy-lab/baseline/episodes').status_code, 200)
        self.assertEqual(public.get('/api/internal/strategy-lab/baseline').status_code, 404)

    def test_private_api_starts_and_reports_fixed_universe_run(self):
        private = TestClient(create_internal_app(store=self.store,
            replay_provider=MemoryProvider()), base_url='http://localhost')
        response = private.post('/api/internal/strategy-lab/baseline/fixed-universe', json={
            'symbols': ['nvda', 'NVDA'],
            'start_date': self.day.isoformat(), 'end_date': self.day.isoformat()})
        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result['run_type'], 'FIXED_RESEARCH_UNIVERSE')
        self.assertEqual(result['research_universe'], ['NVDA'])
        final = private.get('/api/internal/strategy-lab/baseline',
            params={'run_id': result['id']}).json()
        self.assertEqual(final['coverage']['symbol_days_attempted'], 1)
        self.assertEqual(final['coverage']['symbols_evaluated'], 1)

    def test_fixed_universe_cli_uses_same_completed_session_selection(self):
        summary = {'id': 1, 'status': 'COMPLETED',
            'coverage': {'trading_sessions_processed': 1,
                'trading_sessions_requested': 1, 'sessions_with_universe_coverage': 0,
                'sessions_missing_universe': 0, 'symbols_evaluated': 2,
                'eligible_evaluations': 60, 'symbol_failures': 0},
            'forming_long': {'episodes': 1}, 'forming_short': {'episodes': 2}}
        with patch('research.baseline.make_baseline') as make:
            baseline = make.return_value
            baseline.calendar = USEquityMarketCalendar()
            baseline.execute_fixed.return_value = summary
            main(['--fixed-universe', ' nvda,AMD,NVDA ', '--last-trading-days', '1'])
        symbols, days = baseline.execute_fixed.call_args.args
        self.assertEqual(symbols, [' nvda', 'AMD', 'NVDA '])
        self.assertEqual(len(days), 1)
        self.assertTrue(USEquityMarketCalendar().is_session(days[0]))

    def test_missing_universe_records_coverage_limitation(self):
        report = self.baseline().execute([date(2026, 9, 17)])
        self.assertEqual(report['coverage']['symbols_evaluated'], 0)
        self.assertIn('No historical scanner universe',
                      report['coverage']['limitations'][0]['message'])

    def test_twenty_missing_universe_days_are_incomplete_not_covered(self):
        baseline = self.baseline()
        class EmptyCatalog:
            def candidates_for_date(self, trading_date, *, as_of=None):
                return []
        baseline.catalog = EmptyCatalog()
        days = completed_sessions(baseline.calendar, start=date(2026, 8, 21),
            end=date(2026, 9, 18), now=datetime(2026, 9, 20, tzinfo=UTC))
        self.assertEqual(len(days), 20)
        report = baseline.execute(days)
        coverage = report['coverage']
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(coverage['trading_sessions_requested'], 20)
        self.assertEqual(coverage['trading_sessions_processed'], 20)
        self.assertEqual(coverage['sessions_with_universe_coverage'], 0)
        self.assertEqual(coverage['sessions_missing_universe'], 20)
        self.assertEqual(coverage['symbols_evaluated'], 0)
        self.assertEqual(coverage['eligible_evaluations'], 0)
        self.assertEqual(len(coverage['limitations']), 20)
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(BaselineDay)
                .where(BaselineDay.status == 'NO_UNIVERSE')), 20)

    def test_later_discovery_only_enters_baseline_at_first_known_boundary(self):
        late = datetime(2026, 9, 18, 14, 20, tzinfo=UTC)  # 09:20 CT
        with self.store.session() as session:
            session.add(DiscoveryMembership(trading_date=self.day.isoformat(), symbol='LATE',
                source_type='TOP_GAINER', provider='Fixture', first_seen_at=late,
                last_seen_at=late, active=True, metrics={}))
        replay = FakeReplay()
        report = self.baseline(replay).execute([self.day])
        late_id = next(key for key, symbol in replay.symbols.items() if symbol == 'LATE')
        times = [at.astimezone(ZoneInfo('America/Chicago'))
                 for replay_id, at in replay.moves if replay_id == late_id]
        self.assertEqual(times[0].strftime('%H:%M'), '09:21')
        self.assertTrue(all(at >= late for at in times))
        self.assertEqual(len(times), 14)
        self.assertEqual(report['forming_long']['episodes'], 1)

    def test_frozen_forming_version_hash_is_unchanged(self):
        self.assertEqual(strategy_version_id(forming_thresholds()),
                         'experimental-forming-v1/b067b3150de3')

    def test_fixed_universe_uses_only_normalized_user_symbols_and_is_isolated(self):
        before_memberships = self.store.engine.connect().exec_driver_sql(
            'SELECT COUNT(*) FROM discovery_memberships').scalar_one()
        report = self.baseline().execute_fixed([' nvda ', 'AMD', 'NVDA'], [self.day])
        self.assertEqual(report['run_type'], 'FIXED_RESEARCH_UNIVERSE')
        self.assertEqual(report['research_universe'], ['AMD', 'NVDA'])
        self.assertEqual(report['coverage']['symbol_days_attempted'], 2)
        self.assertEqual(report['coverage']['symbols_evaluated'], 2)
        self.assertEqual(report['coverage']['trading_sessions_processed'], 1)
        self.assertEqual(report['research_metadata']['decision_window'], {
            'start': '08:30', 'end': '10:00', 'timezone': 'America/Chicago'})
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(
                DiscoveryMembership)), before_memberships)
            self.assertEqual(session.scalar(select(func.count()).select_from(
                WatchlistUpload)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(
                ActiveUniverseMember)), 0)
            self.assertEqual({row.symbol for row in session.scalars(
                select(BaselineSymbolDay).where(
                    BaselineSymbolDay.baseline_run_id == report['id']))}, {'AMD', 'NVDA'})

    def test_fixed_universe_rerun_is_idempotent_and_separate_from_live_run(self):
        baseline = self.baseline()
        fixed = baseline.execute_fixed(['amd', 'NVDA'], [self.day])
        again = baseline.execute_fixed(['NVDA', 'AMD', 'amd'], [self.day])
        live = baseline.execute([self.day])
        self.assertEqual(fixed['id'], again['id'])
        self.assertNotEqual(fixed['id'], live['id'])
        with self.store.session() as session:
            fixed_days = session.scalars(select(BaselineSymbolDay).where(
                BaselineSymbolDay.baseline_run_id == fixed['id'])).all()
            self.assertEqual(len(fixed_days), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(
                BaselineEvaluation).where(BaselineEvaluation.symbol_day_id.in_(
                    [item.id for item in fixed_days]))), 60)

    def test_nightly_catchup_never_returns_fixed_universe_as_live_baseline(self):
        baseline = self.baseline()
        baseline.execute_fixed(['NVDA'], [self.day])
        class EmptyCatalog:
            def candidates_for_date(self, trading_date, *, as_of=None):
                return []
        baseline.catalog = EmptyCatalog()
        self.assertIsNone(baseline.catch_up(1))

    def test_fixed_symbol_days_never_satisfy_live_nightly_catchup(self):
        at = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)
        with self.store.session() as session:
            session.add(DiscoveryMembership(trading_date=self.day.isoformat(), symbol='NVDA',
                source_type='MOST_ACTIVE', provider='Fixture', first_seen_at=at,
                last_seen_at=at, active=True, metrics={}))
        baseline = self.baseline()
        fixed = baseline.execute_fixed(['NVDA'], [self.day])
        # Keep the scheduler test on the known fixture session rather than
        # whichever XNYS session happens to be current when the suite runs.
        with patch.object(baseline.calendar, 'latest_completed', return_value=self.day):
            live = baseline.catch_up(1)
        self.assertEqual(fixed['run_type'], 'FIXED_RESEARCH_UNIVERSE')
        self.assertEqual(live['run_type'], 'LIVE_RECORDED_UNIVERSE')
        self.assertEqual(live['coverage']['symbols_evaluated'], 2)

    def test_provider_no_data_isolated_to_one_fixed_symbol_day(self):
        class OneNoData(FakeReplay):
            def create(self, symbol, asset_type, market_date, start, end):
                if symbol == 'MISSING':
                    raise ReplayDataUnavailable('fixture has no bars')
                return super().create(symbol, asset_type, market_date, start, end)
        report = self.baseline(OneNoData()).execute_fixed(['MISSING', 'NVDA'], [self.day])
        self.assertEqual(report['coverage']['symbol_days_attempted'], 2)
        self.assertEqual(report['coverage']['symbols_evaluated'], 1)
        self.assertEqual(report['coverage']['provider_no_data'], 1)
        self.assertEqual(report['coverage']['symbol_failures'], 0)

    def test_fixed_universe_decisions_are_bounded_against_future_candles(self):
        from test_strategy_lab import fixture

        reports = []
        for frame in (fixture(extreme=10000), fixture(extreme=999999)):
            store = test_store(self)
            service = StrategyLabService(store.engine, MemoryProvider(frame=frame))
            baseline = HistoricalBaseline(store.engine, replay_service=service,
                provider_retries=1, retry_delay_seconds=0, progress=lambda _: None)
            report = baseline.execute_fixed(['NVDA'], [self.day])
            with store.session() as session:
                rows = session.scalars(select(BaselineEvaluation).where(
                    BaselineEvaluation.evaluated_at <= datetime(2026, 9, 18, 13, 48,
                        tzinfo=UTC))).all()
                reports.append([(row.evaluated_at, row.context_10m, row.state_3m,
                    row.price, row.ema_5, row.ema_12, row.ema_34, row.ema_50, row.vwap)
                    for row in rows])
                self.assertEqual(report['run_type'], 'FIXED_RESEARCH_UNIVERSE')
        self.assertEqual(reports[0], reports[1])

    def test_nightly_catchup_finds_missing_days_in_chronological_order(self):
        baseline = self.baseline()
        class Calendar:
            def latest_completed(self): return date(2026, 9, 18)
            def adjacent(self, day, direction):
                return {date(2026, 9, 18): date(2026, 9, 17),
                        date(2026, 9, 17): date(2026, 9, 16)}[day]
        class Catalog:
            def candidates_for_date(self, day):
                return [{'symbol': 'AAA', 'sources': [], 'sector': None}]
        captured = []
        baseline.calendar, baseline.catalog = Calendar(), Catalog()
        baseline.execute = lambda days: captured.extend(days) or {'days': days}
        now = datetime.now(UTC)
        with self.store.session() as session:
            session.add(BaselineSymbolDay(market_date='2026-09-17', symbol='AAA',
                strategy_version=baseline.strategy_version, status='COMPLETED',
                provenance=[], created_at=now, updated_at=now))
        baseline.catch_up(3)
        self.assertEqual(captured, [date(2026, 9, 16), date(2026, 9, 18)])


if __name__ == '__main__':
    unittest.main()
