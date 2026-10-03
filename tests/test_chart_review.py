"""Private, persisted chart review; no live transport and no detector invocation."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from backend.api import create_app
from backend.internal_api import create_internal_app
from backend.database.models import (Alert, BaselineRun, BaselineSymbolDay, BaselineEpisode,
    BaselineEvaluation, ResearchCandle, ResearchObservation, ResearchOutcome, WatchlistSymbol)
from db_support import activated_watchlist, test_store
from strategy_lab.review import ChartReviewRepository, VERSION, mapped_outcome
from test_alerts import observed, START

DAY = START.date().isoformat()


class ChartReviewTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.upload = activated_watchlist(self.store, ('AAA', 'BBB'), at=START)
        self.repo = ChartReviewRepository(self.store.engine)

    def candles(self, *, count=14, gap=False):
        with self.store.session() as session:
            for tf in ('3m', '10m'):
                for i in range(count if tf == '3m' else 5):
                    minutes = (i + (1 if gap and i > 3 else 0)) * int(tf[:-1])
                    at = START + timedelta(minutes=minutes)
                    session.add(ResearchCandle(symbol='AAA', timeframe=tf, source_timeframe='1m',
                        candle_at=at, captured_at=at + timedelta(minutes=int(tf[:-1])),
                        provider='Fixture', feed='TEST', session_policy='test', source_timezone='America/New_York',
                        content_hash=f'{tf}-{i}', open=100, high=102, low=99, close=100.7,
                        volume=1000, ema_5=100, ema_12=99.8, ema_34=99, ema_50=98.9, vwap=99.6))

    def alert(self):
        result = observed()
        with patch('backend.store.now', return_value=result.evaluated_at):
            self.store.publish(self.upload, [result])
        with self.store.session() as session:
            return session.scalar(select(Alert).where(Alert.alert_type == 'FORMING_LONG')).id

    def test_daily_watchlist_symbols_only_and_latest_upload_not_raw_observations(self):
        self.assertEqual(self.repo.watchlist(DAY)['symbols'], ['AAA', 'BBB'])
        self.store.snapshot(('UNRELATED',), source='discovery')
        self.assertEqual(self.repo.watchlist(DAY)['symbols'], ['AAA', 'BBB'])
        activated_watchlist(self.store, ('CCC',), at=START + timedelta(minutes=1))
        self.assertEqual(self.repo.watchlist(DAY)['symbols'], ['CCC'])
        self.assertEqual(self.repo.watchlist('2020-01-02')['symbols'], [])

    def test_chart_data_and_no_historical_note_parsing(self):
        self.candles()
        with self.store.session() as session:
            row = session.scalar(select(WatchlistSymbol).where(WatchlistSymbol.watchlist_upload_id == self.upload,
                WatchlistSymbol.symbol == 'AAA'))
            row.level_instructions = None
            row.original_note = 'LONG > 187.50'
        result = self.repo.chart(DAY, 'AAA')
        self.assertEqual(len(result['candles_3m']), 14)
        self.assertEqual(len(result['candles_10m']), 5)
        self.assertEqual(result['levels'], [])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['candles_3m'][0]['ema_5'], 100)
        self.assertNotIn('provider', str(result))
        self.assertNotIn('original_note', str(result))

    def test_structured_long_and_short_levels(self):
        with self.store.session() as session:
            row = session.scalar(select(WatchlistSymbol).where(WatchlistSymbol.watchlist_upload_id == self.upload,
                WatchlistSymbol.symbol == 'AAA'))
            row.level_instructions = [{'direction':'LONG', 'trigger_level':'187.50'},
                                      {'direction':'SHORT', 'trigger_level':'184.20'}]
        self.assertEqual(self.repo.chart(DAY, 'AAA')['levels'],
                         [{'direction':'LONG', 'price':187.5}, {'direction':'SHORT', 'price':184.2}])

    def test_repeated_forming_observations_produce_one_persisted_alert_marker(self):
        self.alert()
        for step in (1, 2, 3):
            result = observed(minute=3*step)
            with patch('backend.store.now', return_value=result.evaluated_at):
                self.store.publish(self.upload, [result])
        result = self.repo.chart(DAY, 'AAA')
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['type'], 'FORMING_LONG')
        self.assertEqual(result['events'][0]['origin'], 'Recorded scanner alert')
        with self.store.session() as session:
            self.assertGreater(session.scalar(select(func.count()).select_from(ResearchObservation)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Alert)), 1)

    def test_baseline_episode_single_marker_not_repeated_evaluations(self):
        from strategy_lab.service import StrategyLabService
        from test_strategy_lab import MemoryProvider
        replay = StrategyLabService(self.store.engine, MemoryProvider()).create(
            'AAA', 'EQUITY', DAY, '08:00', '10:00')
        self.candles()
        with self.store.session() as session:
            run = BaselineRun(start_date=DAY, end_date=DAY, status='COMPLETED', strategy_version=VERSION,
                run_type='LIVE_RECORDED_UNIVERSE', universe_key='LIVE', universe_symbols=[], trading_days_total=1,
                created_at=START, updated_at=START)
            session.add(run); session.flush()
            day = BaselineSymbolDay(baseline_run_id=run.id, market_date=DAY, symbol='AAA',
                strategy_version=VERSION, status='COMPLETED', replay_id=replay['id'],
                provenance=[], created_at=START, updated_at=START)
            session.add(day); session.flush()
            for i in range(1, 4):
                session.add(BaselineEvaluation(symbol_day_id=day.id, evaluated_at=START+timedelta(minutes=3*i),
                    state_3m='FORMING_LONG', context_10m='BULLISH', price=100, vwap=99,
                    provider='Fixture', feed='TEST', candle_state='COMPLETED', decision_eligible=True))
            session.add(BaselineEpisode(symbol_day_id=day.id, setup_state='FORMING_LONG',
                first_forming_at=START+timedelta(minutes=3), context_10m='BULLISH', observation_price=100))
        result = self.repo.chart(DAY, 'AAA')
        self.assertEqual(len(result['events']), 1)
        marker = result['events'][0]
        self.assertEqual(marker['origin'], 'Historical baseline episode')
        self.assertEqual(datetime.fromisoformat(marker['chart_time']), START)
        self.assertEqual(marker['vwap_position'], 'ABOVE')

    def test_level_marker_uses_persisted_crossing_not_future_price(self):
        self.candles()
        at = START + timedelta(minutes=4, seconds=15)
        with self.store.session() as session:
            session.add(Alert(symbol='AAA', alert_type='WATCHLIST_LEVEL_SHORT', created_at=at,
                level_key=f'{DAY}|AAA|SHORT|100.00000000', snapshot={
                    'trading_date':DAY, 'crossing_timestamp':at.isoformat(), 'trigger_level':'100', 'price':99.9}))
        result = self.repo.chart(DAY, 'AAA')
        marker = result['events'][0]
        self.assertEqual(marker['type'], 'WATCHLIST_LEVEL_SHORT')
        self.assertEqual(datetime.fromisoformat(marker['chart_time']), START + timedelta(minutes=3))
        self.assertEqual(marker['price'], 99.9)
        self.assertIsNone(marker['outcome']['returns']['9'])
        self.assertEqual(result['levels'], [])  # Never backfill an upload from its events.

    def test_missing_candle_does_not_snap_marker_to_unrelated_bar(self):
        self.alert()
        with self.store.session() as session:
            rows = list(session.scalars(select(ResearchCandle)))
            for row in rows:
                session.delete(row)  # Disposable test evidence only.
        result = self.repo.chart(DAY, 'AAA')
        self.assertIsNone(result['events'][0]['chart_time'])

    def test_missing_outcome_and_no_future_detector_leakage(self):
        self.alert()
        before = self.repo.chart(DAY, 'AAA')['events']
        self.candles()
        with patch('ripster_scanner.forming.detect_forming', side_effect=AssertionError('Must not run detector'), ):
            after = self.repo.chart(DAY, 'AAA')['events']
        self.assertEqual(before, after)
        self.assertEqual(after[0]['outcome']['returns'], {'9':None,'15':None,'30':None})

    def test_outcome_mapping_requires_exact_elapsed_horizons(self):
        at = START
        future = [{'at':at+timedelta(minutes=3*i)} for i in range(10)]
        values = {'return_3':.007,'return_5':.01,'return_10':.02,'best':.03,'adverse':-.01}
        mapped = mapped_outcome(values, future, at)
        self.assertEqual(mapped['returns'], {'9':.007,'15':.01,'30':.02})
        self.assertEqual(mapped['best_move'], .03)
        self.assertEqual(mapped['adverse_move'], -.01)
        gapped = [{'at':bar['at']+timedelta(minutes=3)} for bar in future]
        self.assertEqual(mapped_outcome(values, gapped, at)['returns'], {'9':None,'15':None,'30':None})
        self.assertEqual(mapped_outcome(values, future[:2], at)['returns'], {'9':None,'15':None,'30':None})

    def test_live_stored_outcome_reuse_and_batched_reads(self):
        from research.repository import ResearchRepository
        from datetime import date
        self.alert()
        with self.store.session() as session:
            obs = session.scalar(select(ResearchObservation))
            for i in range(1, 11):
                at = START + timedelta(minutes=3*i)
                session.add(ResearchCandle(symbol='AAA', timeframe='3m', source_timeframe='1m',
                    candle_at=at, captured_at=at+timedelta(minutes=3),
                    provider=obs.provider, feed=obs.feed, session_policy=obs.session_policy,
                    source_timezone=obs.market_timezone, content_hash=f'future-{i}',
                    open=100, high=101, low=99, close=100.7, volume=1000))
        ResearchRepository(self.store.engine).analyze_date(date.fromisoformat(DAY),
            evaluated_at=START+timedelta(hours=1))
        statements = []
        def record(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(self.store.engine, 'before_cursor_execute', record)
        try:
            result = self.repo.chart(DAY, 'AAA')
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', record)
        outcome = result['events'][0]['outcome']
        for value in outcome['returns'].values():
            self.assertAlmostEqual(value, .007)
        self.assertAlmostEqual(outcome['best_move'], .01)
        self.assertAlmostEqual(outcome['adverse_move'], -.01)
        self.assertLessEqual(len(statements), 7)
        self.assertTrue(all(statement.lstrip().upper().startswith('SELECT') for statement in statements))

    def test_legacy_upload_date_and_missing_indicators_are_not_backfilled(self):
        from backend.database.models import WatchlistUpload
        with self.store.session() as session:
            session.get(WatchlistUpload, self.upload).trading_date = None
        self.assertTrue(self.repo.watchlist(DAY)['legacy_date'])
        self.candles()
        with self.store.session() as session:
            candle = session.scalar(select(ResearchCandle))
            candle.ema_5 = None
        self.assertIsNone(self.repo.chart(DAY, 'AAA')['candles_3m'][0]['ema_5'])

    def test_private_read_only_api_validation_and_public_boundary(self):
        with TestClient(create_internal_app(store=self.store, start_watchlist_processor=False)) as client:
            prefix='/api/internal/strategy-lab/review/'
            self.assertEqual(client.get(prefix+'watchlist', params={'date':DAY}).json()['symbols'], ['AAA','BBB'])
            self.assertEqual(client.get(prefix+'chart', params={'date':DAY,'symbol':'AAA'}).status_code, 200)
            for path, params, code in [('chart',{'date':DAY,'symbol':'XXX'},404),
                ('chart',{'date':DAY,'symbol':'../AAA'},422),
                ('watchlist',{'date':'2026-02-30'},422), ('watchlist',{'date':'2099-01-01'},422)]:
                self.assertEqual(client.get(prefix+path, params=params).status_code, code)
        with TestClient(create_app(store=self.store), base_url='http://localhost') as public:
            self.assertEqual(public.get('/api/internal/strategy-lab/review/chart', params={'date':DAY,'symbol':'AAA'}).status_code,404)

    def test_candle_revisions_do_not_change_event_time_evidence(self):
        self.alert()
        before = self.repo.chart(DAY, 'AAA')
        with self.store.session() as session:
            original = session.scalar(select(ResearchCandle).where(ResearchCandle.timeframe == '3m'))
            values = {c.name:getattr(original,c.name) for c in ResearchCandle.__table__.columns if c.name != 'id'}
            values.update(content_hash='revised', close=999, captured_at=START+timedelta(hours=5))
            session.add(ResearchCandle(**values))
        after = self.repo.chart(DAY, 'AAA')
        self.assertEqual(after['events'], before['events'])
        self.assertTrue(any(row['close']==999 for row in after['candles_3m']))

    def test_frozen_baseline_candles_outcomes_and_no_detector_or_provider_calls(self):
        from strategy_lab.service import StrategyLabService
        from test_strategy_lab import MemoryProvider
        provider = MemoryProvider()
        lab = StrategyLabService(self.store.engine, provider)
        replay = lab.create('AAA', 'EQUITY', DAY, '08:00', '10:00')
        at = START + timedelta(minutes=3)
        measured = lab.objective_movement(replay['id'], at, 'FORMING_SHORT', 100)
        with self.store.session() as session:
            run = BaselineRun(start_date=DAY, end_date=DAY, status='COMPLETED', strategy_version=VERSION,
                run_type='LIVE_RECORDED_UNIVERSE', universe_key='LIVE', universe_symbols=[],
                trading_days_total=1, created_at=START, updated_at=START)
            session.add(run)
            session.flush()
            day = BaselineSymbolDay(baseline_run_id=run.id, market_date=DAY, symbol='AAA',
                strategy_version=VERSION, status='COMPLETED', replay_id=replay['id'],
                provenance=[], created_at=START, updated_at=START)
            session.add(day)
            session.flush()
            session.add(BaselineEpisode(symbol_day_id=day.id, setup_state='FORMING_SHORT',
                first_forming_at=at, context_10m='BEARISH', observation_price=100,
                return_after_3_bars=measured['future_3_candle_return'],
                return_after_5_bars=measured['future_5_candle_return'],
                return_after_10_bars=measured['future_10_candle_return'],
                maximum_favorable_excursion=measured['maximum_favorable_excursion'],
                maximum_adverse_excursion=measured['maximum_adverse_excursion'],
                available_future_bars=measured['available_future_candles'], evaluated_at=START))
        with patch('strategy_lab.service.detect_forming', side_effect=AssertionError('No detector')):
            result = self.repo.chart(DAY, 'AAA')
        self.assertEqual(provider.fetch_count, 1)  # Snapshot creation only.
        self.assertTrue(result['candles_10m'])
        self.assertTrue(result['candles_3m'])
        self.assertIsNotNone(result['candles_3m'][0]['ema_5'])
        self.assertEqual(len(result['events']), 1)
        marker = result['events'][0]
        self.assertEqual(marker['type'], 'FORMING_SHORT')
        self.assertEqual(datetime.fromisoformat(marker['chart_time']), START)
        self.assertEqual(marker['outcome']['returns']['9'], measured['future_3_candle_return'])
        self.assertEqual(marker['outcome']['returns']['30'], measured['future_10_candle_return'])
        self.assertEqual(marker['outcome']['best_move'], measured['maximum_favorable_excursion'])

    def test_unrelated_fixed_research_run_does_not_create_scanner_events(self):
        with self.store.session() as session:
            run = BaselineRun(start_date=DAY, end_date=DAY, status='COMPLETED', strategy_version=VERSION,
                run_type='FIXED_RESEARCH_UNIVERSE', universe_key='FIXED', universe_symbols=['AAA'],
                trading_days_total=1, created_at=START, updated_at=START)
            session.add(run)
            session.flush()
            day = BaselineSymbolDay(baseline_run_id=run.id, market_date=DAY, symbol='AAA',
                strategy_version=VERSION, status='COMPLETED', provenance=[], created_at=START, updated_at=START)
            session.add(day)
            session.flush()
            session.add(BaselineEpisode(symbol_day_id=day.id, setup_state='FORMING_LONG',
                first_forming_at=START, context_10m='BULLISH', observation_price=100))
        self.assertEqual(self.repo.chart(DAY, 'AAA')['events'], [])
