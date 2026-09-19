"""Deterministic frozen-strategy historical baseline tests."""

from datetime import date, datetime, timezone
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.api import create_app
from backend.database.models import (BaselineEpisode, BaselineEvaluation,
    BaselineRun, BaselineSymbolDay, DiscoveryMembership)
from backend.internal_api import create_internal_app
from db_support import test_store
from research.baseline import HistoricalBaseline, completed_sessions
from strategy_lab.market_calendar import USEquityMarketCalendar
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

    def test_missing_universe_records_coverage_limitation(self):
        report = self.baseline().execute([date(2026, 9, 17)])
        self.assertEqual(report['coverage']['symbols_evaluated'], 0)
        self.assertIn('No historical scanner universe',
                      report['coverage']['limitations'][0]['message'])

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
