"""Historical evidence, Central-time windows, source provenance and outcomes."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend.database.models import (ResearchCandle, ResearchObservation,
    ResearchOutcome, StrategyVersion)
from db_support import test_store
from research.config import load_settings
from research.repository import ResearchRepository, calculate_outcome
from ripster_scanner.candle_model import MarketSource
from ripster_scanner.config import FormingThresholds
from ripster_scanner.forming import FormingResult, SetupState
from ripster_scanner.scan import ScanResult
from ripster_scanner.strategy import strategy_version_id

SOURCE = MarketSource('Fake', 'MEMORY', 'test regular-hours policy', 'America/New_York')
ET = ZoneInfo('America/New_York')


def candle(hour, minute, close=100, *, low=None, high=None):
    at = datetime(2026, 9, 18, hour, minute, tzinfo=ET)
    return {'timestamp': at.isoformat(), 'open': close - 0.1,
            'high': high if high is not None else close + 0.5,
            'low': low if low is not None else close - 0.5,
            'close': close, 'volume': 1000,
            'ema_5': close - 0.1, 'ema_12': close - 0.2,
            'ema_34': close - 0.3, 'ema_50': close - 0.4,
            'vwap': close - 0.25}


def result(symbol, *, forming=False, three=None):
    three = three or [candle(9, 42)]
    ten = [candle(9, 40)]
    state = (FormingResult(SetupState.FORMING_LONG, 'test pullback', 0)
             if forming else FormingResult())
    return ScanResult(symbol,
        {'trend': 'BULLISH', 'close': ten[-1]['close'], 'vwap_position': 'ABOVE',
         **{key: ten[-1][key] for key in ('ema_5', 'ema_12', 'ema_34', 'ema_50', 'vwap')}},
        {'trend': 'MIXED', 'close': three[-1]['close'], 'vwap_position': 'ABOVE',
         **{key: three[-1][key] for key in ('ema_5', 'ema_12', 'ema_34', 'ema_50', 'vwap')}},
        state, ten, three, three[-1]['timestamp'] if forming else None, SOURCE)


class WindowTests(unittest.TestCase):
    def test_central_window_respects_dst_and_exclusive_end(self):
        settings = load_settings()
        self.assertTrue(settings.inside_window(datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc)))
        self.assertFalse(settings.inside_window(datetime(2026, 9, 18, 12, 59, tzinfo=timezone.utc)))
        self.assertFalse(settings.inside_window(datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc)))
        self.assertTrue(settings.inside_window(datetime(2026, 1, 16, 14, 0, tzinfo=timezone.utc)))
        self.assertFalse(settings.inside_window(datetime(2026, 1, 16, 13, 0, tzinfo=timezone.utc)))

    def test_manual_nightly_command_accepts_trading_date(self):
        from research.job import main
        with patch('research.job.make_engine'), patch('research.job.ResearchRepository') as repo:
            main(['--date', '2026-09-18'])
        repo.return_value.analyze_date.assert_called_once_with(date(2026, 9, 18))

    def test_short_outcome_and_insufficient_future_data(self):
        anchor = datetime(2026, 9, 18, 13, 42, tzinfo=timezone.utc)
        observation = SimpleNamespace(price=100, setup_state='FORMING_SHORT',
                                      three_min_candle_at=anchor)
        future = [SimpleNamespace(close=100 - n, high=101 if n == 1 else 100,
                                  low=99 - n, candle_at=anchor + timedelta(minutes=3*n))
                  for n in range(1, 11)]
        measured = calculate_outcome(observation, future)
        self.assertAlmostEqual(measured['future_3_candle_return'], -0.03)
        self.assertAlmostEqual(measured['future_5_candle_return'], -0.05)
        self.assertAlmostEqual(measured['future_10_candle_return'], -0.10)
        self.assertAlmostEqual(measured['maximum_favorable_excursion'], 0.11)
        self.assertAlmostEqual(measured['maximum_adverse_excursion'], -0.01)
        self.assertEqual(measured['time_to_mfe_minutes'], 30)
        short = calculate_outcome(observation, future[:2])
        self.assertIsNone(short['future_3_candle_return'])
        self.assertIsNone(short['maximum_favorable_excursion'])
        nondirectional = calculate_outcome(
            SimpleNamespace(price=100, setup_state='NONE', three_min_candle_at=anchor), future)
        self.assertIsNone(nondirectional['maximum_favorable_excursion'])
        self.assertAlmostEqual(nondirectional['future_10_candle_return'], -0.10)


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.repo = ResearchRepository(self.store.engine)
        self.snapshot = self.store.snapshot(('FORM', 'PLAIN'))
        self.store.activate(self.snapshot)
        self.observed_at = datetime(2026, 9, 18, 13, 45, tzinfo=timezone.utc)

    def publish(self, at, results=None, thresholds=None):
        with patch('backend.store.now', return_value=at):
            return self.store.publish(self.snapshot, results or
                [result('FORM', forming=True), result('PLAIN')],
                {'FORM': 'Technology'}, research_settings=load_settings(),
                strategy_thresholds=thresholds or FormingThresholds())

    def test_all_symbols_version_source_dedupe_and_filters(self):
        self.assertTrue(self.publish(self.observed_at))
        rows = self.repo.list_observations(trading_date='2026-09-18')
        self.assertEqual({item['symbol'] for item in rows}, {'FORM', 'PLAIN'})
        self.assertEqual({item['setup_state'] for item in rows}, {'FORMING_LONG', 'NONE'})
        self.assertTrue(all(item['inside_research_window'] for item in rows))
        self.assertTrue(all(item['strategy_version'] == strategy_version_id(FormingThresholds())
                            for item in rows))
        self.assertTrue(all(item['provider'] == 'Fake' and item['feed'] == 'MEMORY'
                            for item in rows))
        self.assertEqual(len(self.repo.list_observations(forming=True)), 1)
        self.assertEqual(len(self.repo.list_observations(forming=False)), 1)
        self.assertEqual(len(self.repo.list_observations(symbol='plain')), 1)
        self.assertEqual(len(self.repo.list_observations(setup_state='NONE')), 1)
        self.assertEqual(len(self.repo.list_observations(strategy_version='wrong')), 0)
        self.publish(self.observed_at + timedelta(minutes=1))
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ResearchObservation)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(ResearchCandle)), 4)
            self.assertEqual(session.scalar(select(func.count()).select_from(StrategyVersion)), 1)

    def test_threshold_change_gets_new_strategy_version(self):
        self.publish(self.observed_at)
        changed = replace(FormingThresholds(), cloud_proximity_pct=0.005)
        self.publish(self.observed_at + timedelta(minutes=1), thresholds=changed)
        self.assertEqual(len(self.repo.list_observations(symbol='FORM')), 2)
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(StrategyVersion)), 2)

    def test_same_candle_state_change_is_preserved_without_identical_duplicates(self):
        self.publish(self.observed_at)
        self.publish(self.observed_at + timedelta(seconds=30),
                     [result('FORM', forming=False), result('PLAIN')])
        states = [item['setup_state'] for item in self.repo.list_observations(symbol='FORM')]
        self.assertEqual(states, ['NONE', 'FORMING_LONG'])
        self.publish(self.observed_at + timedelta(minutes=1),
                     [result('FORM', forming=False), result('PLAIN')])
        self.assertEqual(len(self.repo.list_observations(symbol='FORM')), 2)

    def test_observation_records_partial_and_completed_execution_candle(self):
        self.publish(datetime(2026, 9, 18, 13, 44, tzinfo=timezone.utc))
        partial = self.repo.list_observations(symbol='FORM')[0]
        self.assertEqual(partial['candle_state'], 'PARTIAL')
        self.assertTrue(partial['decision_eligible'])
        self.publish(datetime(2026, 9, 18, 13, 45, tzinfo=timezone.utc))
        completed = self.repo.list_observations(symbol='FORM')[0]
        self.assertEqual(completed['candle_state'], 'COMPLETED')
        self.assertEqual(len(self.repo.list_observations(candle_state='COMPLETED', symbol='FORM')), 1)
        self.assertEqual(len(self.repo.list_observations(symbol='FORM')), 2)

    def test_historical_detail_keeps_rule_snapshot_and_nonforming_has_no_directional_excursion(self):
        self.publish(self.observed_at)
        plain = self.repo.list_observations(symbol='PLAIN')[0]
        detail = self.repo.observation_detail(plain['id'])
        self.assertTrue(detail['rules_at_observation'])
        self.assertEqual(detail['source_timeframe'], '1m')
        self.assertEqual(detail['outcome'], None)

    def test_future_candle_is_not_an_observation_feature(self):
        future = result('FORM', forming=True, three=[candle(9, 42), candle(9, 48, 130)])
        self.publish(self.observed_at, [future, result('PLAIN')])
        row = self.repo.list_observations(symbol='FORM')[0]
        self.assertEqual(row['data_status'], 'FUTURE_DATA_REJECTED')
        self.assertIsNone(row['price'])
        self.assertEqual(row['context_10m'], 'NO DATA')
        detail = self.repo.observation_detail(row['id'])
        self.assertEqual(len(detail['candles_3m']), 1)
        self.assertEqual(detail['candles_3m'][0]['close'], 100)

    def test_later_revision_of_same_candle_does_not_change_past_reconstruction(self):
        self.publish(self.observed_at)
        first = self.repo.list_observations(symbol='FORM')[0]
        self.publish(datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc),
                     [result('FORM', three=[candle(9, 42, 105)]), result('PLAIN')])
        old_chart = self.repo.observation_detail(first['id'])['candles_3m']
        self.assertEqual(old_chart[-1]['close'], 100)
        recent = self.repo.list_observations(symbol='FORM')[0]
        self.assertEqual(self.repo.observation_detail(recent['id'])['candles_3m'][-1]['close'], 105)

    def test_future_candles_are_retained_outside_window_and_nightly_is_idempotent(self):
        self.publish(self.observed_at)
        forming = self.repo.list_observations(symbol='FORM', forming=True)[0]
        future = []
        for n in range(1, 11):
            at = datetime(2026, 9, 18, 9, 42, tzinfo=ET) + timedelta(minutes=3*n)
            future.append(candle(at.hour, at.minute, 100+n,
                                 low=98 if n == 1 else 99+n, high=101+n))
        later = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)
        self.publish(later, [result('FORM', three=[candle(9, 42), *future]), result('PLAIN')])
        outside = self.repo.list_observations(symbol='FORM')[0]
        self.assertFalse(outside['inside_research_window'])
        detail = self.repo.observation_detail(forming['id'])
        self.assertEqual(len(detail['candles_3m']), 1)
        self.assertEqual(self.repo.analyze_date(date(2026, 9, 18), evaluated_at=later), 2)
        outcome = self.repo.observation_detail(forming['id'])['outcome']
        self.assertEqual(outcome['available_future_candles'], 10)
        self.assertAlmostEqual(outcome['future_3_candle_return'], 0.03)
        self.assertAlmostEqual(outcome['future_5_candle_return'], 0.05)
        self.assertAlmostEqual(outcome['future_10_candle_return'], 0.10)
        self.assertAlmostEqual(outcome['maximum_favorable_excursion'], 0.11)
        self.assertAlmostEqual(outcome['maximum_adverse_excursion'], -0.02)
        self.assertEqual(outcome['time_to_mfe_minutes'], 30)
        self.assertEqual(outcome['time_to_mae_minutes'], 3)
        plain = next(item for item in self.repo.list_observations(symbol='PLAIN', forming=False)
                     if item['inside_research_window'])
        self.assertIsNone(self.repo.observation_detail(plain['id'])['outcome']['maximum_favorable_excursion'])
        self.repo.analyze_date(date(2026, 9, 18), evaluated_at=later)
        with self.store.session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ResearchOutcome)), 2)


if __name__ == '__main__':
    unittest.main()
