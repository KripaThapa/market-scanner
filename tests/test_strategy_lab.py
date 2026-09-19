"""Private visual replay, hard as-of boundary and human research persistence."""

from datetime import date, datetime, timezone
import unittest
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.internal_api import create_internal_app
from backend.database.models import RuleProposal, StrategyReplayObservation
from db_support import test_store
from strategy_lab.domain import (AssetType, HistoricalCandleSet, Instrument,
                                 MarketClosed, ReplayDataUnavailable)
from strategy_lab.market_calendar import USEquityMarketCalendar
from strategy_lab.provider import AlpacaHistoricalReplayProvider
from strategy_lab.service import StrategyLabService
from ripster_scanner.candle_model import MarketSource
from sqlalchemy import func, select

CT = ZoneInfo('America/Chicago')
SOURCE = MarketSource('Memory', 'FIXTURE',
    'Extended session fixture; opening timestamps', 'America/Chicago')


def fixture(extreme=10000):
    index = pd.date_range('2026-09-18 06:30', '2026-09-18 10:30', freq='min', tz=CT)
    close = [100 + n / 100 for n in range(len(index))]
    frame = pd.DataFrame({'open': close, 'high': [v + .25 for v in close],
        'low': [v - .25 for v in close], 'close': close,
        'volume': [100 + n for n in range(len(index))], 'trade_count': [10] * len(index)}, index=index)
    # Obvious future information at 08:51 CT.
    frame.loc[pd.Timestamp('2026-09-18 08:51', tz=CT), ['high', 'low', 'close', 'volume']] = [extreme, 1, extreme, extreme]
    return frame


class MemoryProvider:
    source = SOURCE
    def __init__(self, frame=None, future=False):
        self.frame = frame if frame is not None else fixture()
        self.future = future
        self.fetch_count = 0

    def supports(self, asset_type):
        return asset_type == AssetType.EQUITY or self.future

    def fetch_range(self, instrument, start, end):
        self.fetch_count += 1
        return HistoricalCandleSet(instrument, self.frame.copy(), self.source)


class StrategyLabTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.provider = MemoryProvider()
        self.lab = StrategyLabService(self.store.engine, self.provider)
        self.replay = self.lab.create('SPY', 'EQUITY', '2026-09-18', '08:00', '10:00')

    def test_create_move_seek_and_exact_aggregation_alignment(self):
        self.assertEqual(self.replay['status'], 'CREATED')
        self.assertEqual(self.replay['candles_3m'], [])
        step = self.lab.move(self.replay['id'], direction=1)
        self.assertTrue(step['current_replay_time'].endswith('13:03:00+00:00'))
        self.assertEqual(pd.Timestamp(step['candles_3m'][-1]['timestamp']).astimezone(CT).strftime('%H:%M'), '08:00')
        at_806 = self.lab.move(self.replay['id'], seek='2026-09-18T08:06:00-05:00')
        self.assertEqual([pd.Timestamp(c['timestamp']).astimezone(CT).strftime('%H:%M')
                          for c in at_806['candles_3m']], ['08:00', '08:03'])
        self.assertEqual([pd.Timestamp(c['timestamp']).astimezone(CT).strftime('%H:%M')
                          for c in at_806['candles_10m']], ['08:00'])
        # 08:00 10m is partial at 08:06: source minutes 08:00..08:05 only.
        self.assertEqual(at_806['candles_10m'][0]['volume'], sum(190 + n for n in range(6)))
        previous = self.lab.move(self.replay['id'], direction=-1)
        self.assertTrue(previous['current_replay_time'].endswith('13:03:00+00:00'))
        with self.assertRaises(ValueError):
            self.lab.move(self.replay['id'], seek='2026-09-18T08:07:00-05:00')

    def test_replay_boundaries_follow_chicago_daylight_saving_time(self):
        summer = self.lab._local_boundary(date(2026, 9, 18), '08:00', CT)
        winter = self.lab._local_boundary(date(2026, 1, 16), '08:00', CT)
        self.assertEqual(summer.astimezone(timezone.utc).strftime('%H:%M'), '13:00')
        self.assertEqual(winter.astimezone(timezone.utc).strftime('%H:%M'), '14:00')

    def test_us_equity_calendar_open_weekend_holiday_and_adjacent_sessions(self):
        calendar = USEquityMarketCalendar()
        self.assertTrue(calendar.is_session(date(2026, 9, 18)))
        for closed, reason, previous_day, next_day in (
            (date(2026, 9, 19), 'WEEKEND', '2026-09-18', '2026-09-21'),
            (date(2026, 9, 20), 'WEEKEND', '2026-09-18', '2026-09-21'),
            (date(2026, 12, 25), 'MARKET_HOLIDAY', '2026-12-24', '2026-12-28')):
            with self.assertRaises(MarketClosed) as raised:
                calendar.validate(closed)
            self.assertEqual(raised.exception.details['reason'], reason)
            self.assertEqual(raised.exception.details['previous_trading_day'], previous_day)
            self.assertEqual(raised.exception.details['next_trading_day'], next_day)

    def test_closed_equity_date_does_not_fetch_or_create_replay(self):
        before = self.provider.fetch_count
        with self.assertRaises(MarketClosed) as raised:
            self.lab.create('SPY', 'EQUITY', '2026-09-19', '08:00', '10:00')
        self.assertEqual(self.provider.fetch_count, before)
        self.assertEqual(raised.exception.details['session_status'], 'CLOSED')

    def test_open_equity_date_with_empty_provider_data_is_no_data(self):
        empty = fixture().iloc[0:0]
        lab = StrategyLabService(self.store.engine, MemoryProvider(empty))
        with self.assertRaises(ReplayDataUnavailable) as raised:
            lab.create('SPY', 'EQUITY', '2026-09-18', '08:00', '10:00')
        self.assertEqual(raised.exception.details['error'], 'NO_DATA')
        self.assertEqual(raised.exception.details['session_status'], 'OPEN')

    def test_equity_calendar_is_not_applied_to_future(self):
        provider = MemoryProvider(future=True)
        replay = StrategyLabService(self.store.engine, provider).create(
            'MES', 'FUTURE', '2026-09-19', '08:00', '10:00')
        self.assertEqual(replay['asset_type'], 'FUTURE')
        self.assertEqual(provider.fetch_count, 1)

    def test_future_3m_10m_high_low_volume_ema_vwap_and_context_cannot_leak(self):
        first = self.lab.move(self.replay['id'], seek='2026-09-18T08:48:00-05:00')
        other = StrategyLabService(self.store.engine, MemoryProvider(fixture(extreme=999999)))
        second_id = other.create('QQQ', 'EQUITY', '2026-09-18', '08:00', '10:00')['id']
        second = other.move(second_id, seek='2026-09-18T08:48:00-05:00')
        # Different future extremes at 08:51 produce identical bounded features/context.
        for field in ('context_10m', 'state_3m'):
            self.assertEqual(first[field], second[field])
        for timeframe in ('candles_3m', 'candles_10m'):
            a, b = first[timeframe], second[timeframe]
            self.assertEqual(a, b)
            self.assertTrue(all(pd.Timestamp(row['timestamp']).astimezone(CT) <
                                pd.Timestamp('2026-09-18 08:48', tz=CT) for row in a))
            self.assertTrue(all(row['high'] < 10000 and row['low'] > 1 and row['volume'] < 10000
                                for row in a))
            self.assertTrue(all(row['ema_50'] < 10000 and row['vwap'] < 10000 for row in a))
        self.assertNotIn('outcome', first)
        self.assertNotIn('future', str(first).lower())
        self.assertTrue(all(pd.Timestamp(marker['timestamp']).astimezone(CT) <
                            pd.Timestamp('2026-09-18 08:48', tz=CT)
                            for marker in first['forming_markers']))

    def test_baseline_path_reuses_bounded_strategy_calculation(self):
        first = self.lab.baseline_evaluation(
            self.replay['id'], '2026-09-18T08:48:00-05:00')
        other = StrategyLabService(self.store.engine,
            MemoryProvider(fixture(extreme=999999)))
        second_id = other.create('QQQ', 'EQUITY', '2026-09-18',
                                 '08:00', '10:00')['id']
        second = other.baseline_evaluation(
            second_id, '2026-09-18T08:48:00-05:00')
        self.assertEqual({key: value for key, value in first.items() if key != 'id'},
                         {key: value for key, value in second.items() if key != 'id'})
        self.assertLess(first['latest_3m']['close'], 10000)
        self.assertLess(first['latest_3m']['ema_50'], 10000)
        self.assertLess(first['latest_3m']['vwap'], 10000)
        self.assertNotIn('outcome', first)

    def test_human_observations_do_not_change_strategy_and_outcome_requires_reveal(self):
        replay_id = self.replay['id']
        self.lab.move(replay_id, seek='2026-09-18T08:48:00-05:00')
        before = self.lab.get(replay_id)
        for decision in ('NOT_YET', 'INTERESTING', 'WOULD_CONSIDER_ENTRY'):
            saved = self.lab.observe(replay_id, decision, f'Free text for {decision}')
            self.assertTrue(saved['replay_time'].endswith('13:48:00+00:00'))
        after = self.lab.get(replay_id)
        self.assertEqual((before['context_10m'], before['state_3m']),
                         (after['context_10m'], after['state_3m']))
        with self.assertRaises(PermissionError):
            self.lab.outcomes(replay_id)
        self.lab.complete(replay_id)
        with self.assertRaises(PermissionError):
            self.lab.outcomes(replay_id)
        revealed = self.lab.reveal(replay_id)
        self.assertEqual(revealed['label'], 'POST-OBSERVATION MARKET MOVEMENT')
        self.assertNotIn('win', str(revealed).lower())
        self.assertNotIn('loss', str(revealed).lower())
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(StrategyReplayObservation)), 3)
            self.assertEqual(session.scalar(select(func.count()).select_from(RuleProposal)), 0)

    def test_private_api_and_public_separation(self):
        private = TestClient(create_internal_app(store=self.store, replay_provider=self.provider),
                             base_url='http://localhost')
        public = TestClient(create_app(store=self.store), base_url='http://localhost')
        created = private.post('/api/internal/replays', json={'instrument': 'SPY',
            'asset_type': 'EQUITY', 'market_date': '2026-09-18', 'start': '08:00',
            'end': '10:00', 'blind_mode': True})
        self.assertEqual(created.status_code, 201, created.text)
        replay_id = created.json()['id']
        self.assertEqual(private.post(f'/api/internal/replays/{replay_id}/next').status_code, 200)
        sought = private.post(f'/api/internal/replays/{replay_id}/seek', json={
            'replay_time': '2026-09-18T08:48:00-05:00'})
        self.assertEqual(sought.status_code, 200)
        chart = private.get(f'/api/internal/replays/{replay_id}/chart?timeframe=3m').json()
        self.assertTrue(all(pd.Timestamp(row['timestamp']).astimezone(CT) <
                            pd.Timestamp('2026-09-18 08:48', tz=CT) for row in chart['candles']))
        self.assertTrue(all(row['high'] < 10000 and row['volume'] < 10000
                            for row in chart['candles']))
        self.assertEqual(private.get(f'/api/internal/replays/{replay_id}/outcome').status_code, 409)
        for path in ('/api/internal/replays', f'/api/internal/replays/{replay_id}',
                     f'/api/internal/replays/{replay_id}/outcome'):
            self.assertEqual(public.get(path).status_code, 404)

    def test_market_closed_api_response_is_structured(self):
        private = TestClient(create_internal_app(store=self.store, replay_provider=self.provider),
                             base_url='http://localhost')
        response = private.post('/api/internal/replays', json={'instrument': 'SPY',
            'asset_type': 'EQUITY', 'market_date': '2026-09-19', 'start': '08:00',
            'end': '10:00', 'blind_mode': True})
        self.assertEqual(response.status_code, 422)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'MARKET_CLOSED')
        self.assertEqual(detail['reason'], 'WEEKEND')
        self.assertEqual(detail['previous_trading_day'], '2026-09-18')
        self.assertEqual(detail['next_trading_day'], '2026-09-21')

    def test_mes_is_truthfully_unavailable_with_current_provider(self):
        response = TestClient(create_internal_app(store=self.store, replay_provider=self.provider),
            base_url='http://localhost').post('/api/internal/replays', json={
                'instrument': 'MES', 'asset_type': 'FUTURE', 'market_date': '2026-09-18',
                'start': '08:00', 'end': '10:00', 'blind_mode': True})
        self.assertEqual(response.status_code, 422)
        self.assertIn('futures history is unavailable', response.text)


class AlpacaReplayAdapterTests(unittest.TestCase):
    def test_extended_hours_are_not_filtered_from_equity_replay(self):
        class Bars:
            df = fixture().rename_axis('timestamp').reset_index().assign(symbol='SPY')
        class Client:
            def get_stock_bars(self, request): return Bars()
        provider = AlpacaHistoricalReplayProvider('', '', client=Client())
        result = provider.fetch_range(Instrument('SPY', AssetType.EQUITY),
            datetime(2026, 9, 18, 12, tzinfo=timezone.utc),
            datetime(2026, 9, 18, 16, tzinfo=timezone.utc))
        local = result.frame.index.tz_convert(CT)
        self.assertIn(pd.Timestamp('2026-09-18 08:00', tz=CT), local)
        self.assertIn(pd.Timestamp('2026-09-18 08:29', tz=CT), local)
        self.assertFalse(provider.supports(AssetType.FUTURE))


if __name__ == '__main__':
    unittest.main()
