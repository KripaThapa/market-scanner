"""Research-only API factory. Not mounted by the public Compose backend.

Deployment requires separate authentication/authorization before exposing it.
"""

from fastapi import FastAPI, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from typing import Literal
from pathlib import Path
import os

from backend.store import Store
from research.config import load_settings
from research.repository import ResearchRepository
from backend.service import BusyError, ImportFailed, ImportService
from backend.uploads import save_image, UploadBoundary
from strategy_lab.domain import (MarketClosed, ReplayDataUnavailable,
                                 ReplayDateUnavailable)
from strategy_lab.catalog import HistoricalUniverseRepository
from strategy_lab.market_calendar import USEquityMarketCalendar
from strategy_lab.service import StrategyLabService


class RuleProposalInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=4000)
    rationale: str = Field(min_length=2, max_length=4000)
    timeframe: Literal['10m', '3m', 'both']
    condition: str = Field(min_length=2, max_length=4000)
    threshold_config: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)


class ReplayInput(BaseModel):
    instrument: str = Field(min_length=1, max_length=20, pattern=r'^[A-Za-z][A-Za-z0-9.-]*$')
    asset_type: Literal['EQUITY', 'FUTURE']
    market_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    start: str | None = Field(default=None, pattern=r'^\d{2}:\d{2}$')
    end: str | None = Field(default=None, pattern=r'^\d{2}:\d{2}$')
    blind_mode: bool = True


class ReplaySeekInput(BaseModel):
    replay_time: str = Field(min_length=20, max_length=40)


class ReplayObservationInput(BaseModel):
    decision: Literal['NOT_YET', 'INTERESTING', 'WOULD_CONSIDER_ENTRY']
    reason: str = Field(min_length=1, max_length=4000)


def create_internal_app(*, store=None, data_dir=None, replay_provider=None):
    store = store or Store()
    research = ResearchRepository(store.engine)
    replay_catalog = HistoricalUniverseRepository(store.engine)
    equity_calendar = USEquityMarketCalendar()
    app = FastAPI(title='Market Scanner Internal Research')
    app.add_middleware(UploadBoundary)
    import_service = ImportService(store)
    upload_dir = Path(data_dir or os.getenv('RIPSTER_DATA_DIR', 'data')) / 'uploads'
    lab_instance = None
    baseline_instance = None

    def lab():
        nonlocal lab_instance
        if lab_instance is None:
            provider = replay_provider
            if provider is None:
                from ripster_scanner.config import load_config
                from strategy_lab.provider import AlpacaHistoricalReplayProvider
                config = load_config(symbols=())
                provider = AlpacaHistoricalReplayProvider(config.api_key, config.secret_key)
            lab_instance = StrategyLabService(store.engine, provider)
        return lab_instance

    def baseline():
        nonlocal baseline_instance
        if baseline_instance is None:
            from research.baseline import HistoricalBaseline
            baseline_instance = HistoricalBaseline(store.engine, lab().provider)
        return baseline_instance

    def replay_call(action):
        try:
            return action()
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'")) from None
        except MarketClosed as exc:
            raise HTTPException(422, exc.details) from None
        except ReplayDateUnavailable as exc:
            raise HTTPException(422, exc.details) from None
        except ReplayDataUnavailable as exc:
            raise HTTPException(422, exc.details) from None
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from None
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get('/internal/health')
    def internal_health():
        try:
            store.ping()
            return {'status': 'ok'}
        except Exception:
            raise HTTPException(503, 'Internal service unavailable') from None

    @app.get('/api/internal/strategy-lab/capabilities')
    def replay_capabilities():
        return replay_call(lambda: lab().capabilities())

    @app.get('/api/internal/strategy-lab/calendar')
    def replay_calendar(year: int = Query(ge=1990, le=2100),
                        month: int = Query(ge=1, le=12)):
        return replay_call(lambda: equity_calendar.month(year, month))

    @app.get('/api/internal/strategy-lab/calendar/adjacent')
    def adjacent_trading_day(date_value: str = Query(alias='date', pattern=r'^\d{4}-\d{2}-\d{2}$'),
                             direction: Literal['previous', 'next'] = 'previous'):
        from datetime import date
        return {'date': replay_call(lambda: equity_calendar.adjacent(
            date.fromisoformat(date_value), direction)).isoformat()}

    @app.get('/api/internal/strategy-lab/universe')
    def replay_universe(date_value: str = Query(alias='date', pattern=r'^\d{4}-\d{2}-\d{2}$')):
        return replay_catalog.for_date(date_value)

    @app.get('/api/internal/strategy-lab/baseline')
    def historical_baseline(run_id: int | None = Query(default=None, ge=1)):
        report = baseline().report(run_id)
        if report is None:
            return {'status': 'NOT_RUN', 'episodes': []}
        return {key: value for key, value in report.items() if key != 'episodes'}

    @app.get('/api/internal/strategy-lab/baseline/episodes')
    def historical_baseline_episodes(run_id: int | None = Query(default=None, ge=1),
                                     limit: int = Query(default=100, ge=1, le=500)):
        report = baseline().report(run_id)
        return {'items': (report or {}).get('episodes', [])[:limit]}

    @app.get('/api/internal/replays')
    def list_replays(limit: int = Query(default=50, ge=1, le=100)):
        return {'items': replay_call(lambda: lab().list(limit))}

    @app.post('/api/internal/replays', status_code=201)
    def create_replay(body: ReplayInput):
        return replay_call(lambda: lab().create(**body.model_dump()))

    @app.get('/api/internal/replays/{replay_id}')
    def get_replay(replay_id: int):
        return replay_call(lambda: lab().get(replay_id))

    @app.post('/api/internal/replays/{replay_id}/next')
    def next_candle(replay_id: int):
        return replay_call(lambda: lab().move(replay_id, direction=1))

    @app.post('/api/internal/replays/{replay_id}/previous')
    def previous_candle(replay_id: int):
        return replay_call(lambda: lab().move(replay_id, direction=-1))

    @app.post('/api/internal/replays/{replay_id}/seek')
    def seek_replay(replay_id: int, body: ReplaySeekInput):
        return replay_call(lambda: lab().move(replay_id, seek=body.replay_time))

    @app.get('/api/internal/replays/{replay_id}/chart')
    def replay_chart(replay_id: int, timeframe: Literal['3m', '10m']):
        replay = replay_call(lambda: lab().get(replay_id))
        return {'replay_id': replay_id, 'timeframe': timeframe,
                'current_replay_time': replay['current_replay_time'],
                'candles': replay[f'candles_{timeframe}']}

    @app.post('/api/internal/replays/{replay_id}/observations', status_code=201)
    def create_replay_observation(replay_id: int, body: ReplayObservationInput):
        return replay_call(lambda: lab().observe(replay_id, body.decision, body.reason))

    @app.get('/api/internal/replays/{replay_id}/observations')
    def replay_observations(replay_id: int):
        return {'items': replay_call(lambda: lab().observations(replay_id))}

    @app.post('/api/internal/replays/{replay_id}/complete')
    def complete_replay(replay_id: int):
        return replay_call(lambda: lab().complete(replay_id))

    @app.post('/api/internal/replays/{replay_id}/reveal')
    def reveal_replay(replay_id: int):
        return replay_call(lambda: lab().reveal(replay_id))

    @app.get('/api/internal/replays/{replay_id}/outcome')
    def replay_outcome(replay_id: int):
        return replay_call(lambda: lab().outcomes(replay_id))

    @app.post('/internal/watchlist/upload', status_code=202)
    def upload(file: UploadFile):
        path = None
        try:
            path, filename = save_image(file, upload_dir)
            return import_service.import_image(path, filename)
        except BusyError:
            if path:
                path.unlink(missing_ok=True)
            raise HTTPException(409, 'Another import is in progress') from None
        except ImportFailed as exc:
            report = exc.report or {}
            raise HTTPException(422 if report and not report.get('validated_count') else 502,
                                {'message': 'Watchlist import failed', 'report': report}) from None
        finally:
            file.file.close()

    @app.get('/internal/rules')
    def rules():
        data = research.rules()
        settings = load_settings()
        return {**data, 'research_window': {'start': settings.start.strftime('%H:%M'),
                'end': settings.end.strftime('%H:%M'), 'timezone': str(settings.timezone)}}

    @app.post('/internal/rules/proposals', status_code=201)
    def add_rule_proposal(body: RuleProposalInput):
        return research.add_proposal(body.model_dump())

    @app.get('/internal/research/observations')
    def research_observations(trading_date: str | None = Query(default=None, alias='date',
                              pattern=r'^\d{4}-\d{2}-\d{2}$'),
                              symbol: str | None = None,
                              strategy_version: str | None = None,
                              setup_state: Literal['NONE', 'FORMING_LONG', 'FORMING_SHORT'] | None = None,
                              forming: bool | None = None,
                              discovery_source: Literal['UPLOADED_WATCHLIST', 'MOST_ACTIVE',
                                                        'TOP_GAINER', 'TOP_LOSER'] | None = None,
                              sector: str | None = None,
                              candle_state: Literal['PARTIAL', 'COMPLETED'] | None = None,
                              decision_eligible: bool | None = None,
                              limit: int = Query(default=200, ge=1, le=500)):
        return {'items': research.list_observations(trading_date=trading_date,
            symbol=symbol, strategy_version=strategy_version,
            setup_state=setup_state, forming=forming, discovery_source=discovery_source,
            sector=sector, candle_state=candle_state,
            decision_eligible=decision_eligible, limit=limit)}

    @app.get('/internal/research/observations/{observation_id}')
    def research_observation(observation_id: int):
        item = research.observation_detail(observation_id)
        if item is None:
            raise HTTPException(404, 'Observation not found')
        return item

    @app.get('/internal/discovery/sources')
    def discovery_sources():
        from sqlalchemy import select
        from backend.database.models import DiscoverySourceStatus
        with store.session() as session:
            return {'items': [{name: getattr(row, name) for name in
                ('source_type', 'provider', 'status', 'last_attempt_at',
                 'last_success_at', 'error')} for row in session.scalars(
                     select(DiscoverySourceStatus))]}

    return app
