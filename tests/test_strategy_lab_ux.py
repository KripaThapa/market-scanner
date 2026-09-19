"""Replay creation calendar, historical universe, and session-default tests."""

from datetime import date, datetime, timezone
import unittest

from fastapi.testclient import TestClient
import pandas as pd

from backend.database.models import (DiscoveryMembership, ResearchObservation,
                                     StrategyVersion, WatchlistUpload)
from backend.internal_api import create_internal_app
from db_support import test_store
from strategy_lab.catalog import HistoricalUniverseRepository
from strategy_lab.market_calendar import USEquityMarketCalendar
from strategy_lab.service import StrategyLabService
from test_strategy_lab import CT, MemoryProvider, fixture


UTC = timezone.utc


class StrategyLabCreationUxTests(unittest.TestCase):
    def setUp(self):
        self.store = test_store(self)
        self.provider = MemoryProvider(future=True)

    def seed_universe(self):
        at = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
        with self.store.session() as session:
            upload = WatchlistUpload(date='2026-09-18', source='config',
                uploaded_at=at, processing_status='scanned', candidate_count=0,
                validated_count=3, candidates=[])
            session.add(upload)
            session.flush()
            session.add(StrategyVersion(id='forming-v1', name='Experimental Forming Setup V1',
                status='EXPERIMENTAL', config_snapshot={}, rules_snapshot=[], created_at=at))
            for symbol, state in (('NVDA', 'FORMING_LONG'), ('MSFT', 'NONE'), ('AMD', 'NONE')):
                session.add(ResearchObservation(
                    dedupe_key=f'{symbol}-2026-09-18', snapshot_id=upload.id, symbol=symbol,
                    observed_at=at, created_at=at, trading_date='2026-09-18',
                    strategy_version='forming-v1', watchlist_source='config',
                    context_10m='BULLISH', context_3m='MIXED', setup_state=state,
                    inside_research_window=True, provider='Memory', feed='FIXTURE',
                    source_timeframe='1m', session_policy='extended',
                    market_timezone='America/Chicago', research_timezone='America/Chicago',
                    data_status='OK'))
            for symbol in ('NVDA', 'AMD', 'TSLA'):
                session.add(DiscoveryMembership(trading_date='2026-09-18', symbol=symbol,
                    source_type='MOST_ACTIVE', provider='Fixture', first_seen_at=at,
                    last_seen_at=at, active=True, metrics={}))
            # This later date proves the selected-date query never uses a current/future universe.
            session.add(DiscoveryMembership(trading_date='2026-09-21', symbol='FUTR',
                source_type='TOP_GAINER', provider='Fixture', first_seen_at=at,
                last_seen_at=at, active=True, metrics={'future_return': 99}))

    def test_calendar_month_marks_sessions_closed_dates_and_future(self):
        calendar = USEquityMarketCalendar()
        now = datetime(2026, 9, 19, 20, tzinfo=UTC)
        september = calendar.month(2026, 9, now=now)
        by_day = {item['date']: item for item in september['days']}
        self.assertEqual(september['default_date'], '2026-09-18')
        self.assertEqual(by_day['2026-09-18']['status'], 'OPEN')
        self.assertEqual(by_day['2026-09-19'], {
            'date': '2026-09-19', 'status': 'CLOSED', 'reason': 'WEEKEND'})
        self.assertEqual(by_day['2026-09-21']['reason'], 'FUTURE_DATE')
        july = calendar.month(2026, 7, now=now)
        holiday = next(item for item in july['days'] if item['date'] == '2026-07-03')
        self.assertEqual((holiday['status'], holiday['reason']),
                         ('CLOSED', 'MARKET_HOLIDAY'))

    def test_previous_and_next_trading_days(self):
        calendar = USEquityMarketCalendar()
        selected = date(2026, 9, 18)
        self.assertEqual(calendar.adjacent(selected, 'previous'), date(2026, 9, 17))
        self.assertEqual(calendar.adjacent(selected, 'next'), date(2026, 9, 21))

    def test_historical_universe_is_date_bound_grouped_and_has_no_outcomes(self):
        self.seed_universe()
        result = HistoricalUniverseRepository(self.store.engine).for_date('2026-09-18')
        groups = {group['id']: group['symbols'] for group in result['groups']}
        self.assertEqual(groups['FORMING'], ['NVDA'])
        self.assertEqual(groups['DISCOVERY'], ['AMD', 'TSLA'])
        self.assertEqual(groups['ALL_SCANNED'], ['MSFT'])
        self.assertEqual(result['symbols'], ['AMD', 'MSFT', 'NVDA', 'TSLA'])
        self.assertNotIn('FUTR', str(result))
        self.assertNotIn('return', str(result).lower())

    def test_empty_historical_universe_and_private_api_boundary(self):
        private = TestClient(create_internal_app(store=self.store,
            replay_provider=self.provider), base_url='http://localhost')
        response = private.get('/api/internal/strategy-lab/universe?date=2026-09-18')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['recorded'])
        self.assertEqual(response.json()['symbols'], [])

    def test_equity_defaults_and_custom_times(self):
        lab = StrategyLabService(self.store.engine, self.provider)
        defaulted = lab.create('SPY', 'EQUITY', '2026-09-18')
        self.assertTrue(defaulted['visible_start'].endswith('13:30:00+00:00'))
        self.assertTrue(defaulted['visible_end'].endswith('15:00:00+00:00'))
        custom = lab.create('QQQ', 'EQUITY', '2026-09-18', '08:00', '09:30')
        self.assertTrue(custom['visible_start'].endswith('13:00:00+00:00'))
        self.assertTrue(custom['visible_end'].endswith('14:30:00+00:00'))

    def test_equity_defaults_do_not_apply_to_future(self):
        replay = StrategyLabService(self.store.engine, self.provider).create(
            'MES', 'FUTURE', '2026-09-18')
        self.assertTrue(replay['visible_start'].endswith('13:00:00+00:00'))
        self.assertTrue(replay['visible_end'].endswith('15:00:00+00:00'))

    def test_chart_context_has_previous_session_but_never_future_candles(self):
        previous = fixture().copy()
        previous.index = previous.index - pd.Timedelta(days=1)
        provider = MemoryProvider(pd.concat([previous, fixture()]).sort_index())
        lab = StrategyLabService(self.store.engine, provider)
        created = lab.create('SPY', 'EQUITY', '2026-09-18')
        with self.store.session() as session:
            row = lab._row(session, created['id'])
            calculated_dates = {item.date() for item in
                lab._calculated(session, row, datetime(2026, 9, 18, 13, 48, tzinfo=UTC))['3m'].index}
        self.assertIn(date(2026, 9, 17), calculated_dates)
        replay = lab.move(created['id'], seek='2026-09-18T08:48:00-05:00')
        timestamps = [pd.Timestamp(item['timestamp']).tz_convert(CT)
                      for item in replay['candles_3m']]
        self.assertTrue(any(item.date() == date(2026, 9, 17) for item in timestamps), timestamps)
        self.assertTrue(any(item.date() == date(2026, 9, 18) for item in timestamps))
        self.assertTrue(all(item < pd.Timestamp('2026-09-18 08:48', tz=CT)
                            for item in timestamps if item.date() == date(2026, 9, 18)))
        self.assertFalse(any(item >= pd.Timestamp('2026-09-18 08:51', tz=CT)
                             for item in timestamps))

    def test_internal_calendar_and_universe_endpoints(self):
        self.seed_universe()
        client = TestClient(create_internal_app(store=self.store,
            replay_provider=self.provider), base_url='http://localhost')
        calendar = client.get('/api/internal/strategy-lab/calendar?year=2026&month=9')
        self.assertEqual(calendar.status_code, 200)
        self.assertEqual(calendar.json()['market'], 'US_EQUITY')
        adjacent = client.get('/api/internal/strategy-lab/calendar/adjacent', params={
            'date': '2026-09-18', 'direction': 'previous'})
        self.assertEqual(adjacent.json()['date'], '2026-09-17')
        universe = client.get('/api/internal/strategy-lab/universe?date=2026-09-18')
        self.assertEqual(universe.status_code, 200)
        self.assertEqual(universe.json()['trading_date'], '2026-09-18')


if __name__ == '__main__':
    unittest.main()
