"""Public scanner API: display-only, source-agnostic DTOs."""

from contextlib import asynccontextmanager
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .store import Store
from .alerts import public_alert, public_marker
from .security import PublicSecurityMiddleware


def _public_universe(row):
    return {key: row.get(key) for key in
            ('symbol', 'sector', 'percent_change', 'context_10m', 'context_3m',
             'setup_state', 'latest_price', 'candle_state', 'scanned_at')}


def _public_setup(row):
    return {key: row.get(key) for key in
            ('symbol', 'direction', 'context_10m', 'setup_state', 'price',
             'first_detected_at', 'last_seen_at')}


def _public_sector(row):
    return {key: row.get(key) for key in
            ('sector', 'symbols', 'symbol_count', 'bullish_count', 'bearish_count',
             'mixed_count', 'forming_long_count', 'forming_short_count', 'updated_at')}


def _public_candles(candles):
    return [{key: candle.get(key) for key in
             ('timestamp', 'open', 'high', 'low', 'close', 'volume')} for candle in candles]


def _public_detail(detail):
    result = {key: detail.get(key) for key in
              ('symbol', 'scanned_at', 'context_10m', 'context_3m', 'latest_price',
               'setup_state', 'first_detected_at', 'last_seen_at', 'candle_state')}
    result['alerts'] = [public_marker(row) for row in detail['alerts']]
    result['candles_3m'] = _public_candles(detail['candles_3m'])
    result['candles_10m'] = _public_candles(detail['candles_10m'])
    return result


def create_app(data_dir=None, *, store=None):
    store = store or Store()

    @asynccontextmanager
    async def lifespan(app):
        store.check_ready()
        yield

    app = FastAPI(title='Market Scanner', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(PublicSecurityMiddleware)
    origins = [item.strip() for item in os.getenv('CORS_ALLOWED_ORIGINS',
              'http://localhost:3000,http://127.0.0.1:3000').split(',') if item.strip()]
    if '*' in origins:
        raise ValueError('Wildcard CORS origins are forbidden')
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET'],
                       allow_headers=['Accept', 'Content-Type'], allow_credentials=False)
    hosts = [item.strip() for item in os.getenv('TRUSTED_HOSTS',
             'localhost,127.0.0.1,backend').split(',') if item.strip()]
    if '*' in hosts or not hosts:
        raise ValueError('Explicit trusted hosts are required')
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.state.store = store

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse({'detail': 'Database unavailable. Please retry.'}, status_code=503)

    @app.get('/health')
    def health():
        try:
            store.ping()
            return {'status': 'ok', 'backend': 'ok', 'database': 'connected'}
        except Exception:
            return JSONResponse({'status': 'degraded', 'backend': 'ok', 'database': 'unavailable'}, status_code=503)

    @app.get('/api/dashboard')
    def dashboard():
        data = store.read()
        rows = data['universe']
        state = {key: data['state'].get(key) for key in ('status', 'last_updated')}
        return {'state': state,
                'universe': [_public_universe(row) for row in data['universe']],
                'setups': [_public_setup(row) for row in data['setups']],
                'alerts': [public_alert(row) for row in data['alerts']],
                'sectors': [_public_sector(row) for row in data['sectors']],
                'counts': {
            'total': sum(r['context_10m'] != 'PENDING' for r in rows),
            'pending': sum(r['context_10m'] == 'PENDING' for r in rows), 'bullish': sum(r['context_10m'] == 'BULLISH' for r in rows),
            'bearish': sum(r['context_10m'] == 'BEARISH' for r in rows),
            'mixed': sum(r['context_10m'] == 'MIXED' for r in rows),
            'no_data': sum(r['context_10m'] == 'NO DATA' for r in rows),
            'developing': len(data['setups']),
            'forming_long': sum(r['setup_state'] == 'FORMING_LONG' for r in data['universe']),
            'forming_short': sum(r['setup_state'] == 'FORMING_SHORT' for r in data['universe']),
            'sectors_represented': len({r['sector'] for r in rows if r['sector'] and r['sector'].strip().upper() not in {'UNKNOWN', 'UNCLASSIFIED'}}),
            'missing_sector_data': sum(not r['sector'] or r['sector'].strip().upper() in {'UNKNOWN', 'UNCLASSIFIED'} for r in rows),
        }, 'capabilities': {'forming_setups': True, 'alerts': True,
                             'volatility': False, 'relative_strength': False}}

    @app.get('/api/discovery')
    def discovery():
        data = store.read()
        return {'items': [_public_universe(item) for item in data['universe']],
                'last_updated': data['state'].get('last_updated')}

    @app.get('/api/setups/forming')
    def setups():
        return {'items': [_public_setup(row) for row in store.read()['setups']], 'implemented': True,
                'message': 'Developing scanner state; no entry signals.'}

    @app.get('/api/alerts')
    def alerts():
        return {'items': [public_alert(row) for row in store.read()['alerts']], 'implemented': True,
                'message': 'Latest 200 stored events. Completed-candle FORMING alerts are experimental, not trade entries.'}

    @app.get('/api/sectors')
    def sectors():
        return {'items': [_public_sector(row) for row in store.read()['sectors']],
                'message': 'Objective counts across the active universe; no sector trading rule.'}

    @app.get('/api/sectors/{sector}')
    def sector_detail(sector: str = Path(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9 &/.-]+$')):
        data = store.read()
        item = next((row for row in data['sectors'] if row['sector'] == sector), None)
        if item is None:
            raise HTTPException(404, 'Sector not found')
        return {'sector': _public_sector(item), 'symbols': [_public_universe(row) for row in data['universe']
                                            if row['sector'] == sector]}

    @app.get('/api/symbols/{symbol}')
    def symbol_detail(symbol: str = Path(pattern=r'^[A-Za-z][A-Za-z0-9.-]{0,9}$')):
        detail = store.symbol_detail(symbol.upper())
        if detail is None:
            raise HTTPException(404, 'Symbol is not in the current scan')
        return _public_detail(detail)

    @app.get('/api/symbols/{symbol}/chart')
    def symbol_chart(timeframe: Literal['3m', '10m'], symbol: str = Path(pattern=r'^[A-Za-z][A-Za-z0-9.-]{0,9}$')):
        detail = store.symbol_detail(symbol.upper())
        if detail is None:
            raise HTTPException(404, 'Symbol is not in the current scan')
        return {'symbol': detail['symbol'], 'timeframe': timeframe,
                'scanned_at': detail['scanned_at'],
                'candles': _public_candles(detail[f'candles_{timeframe}']),
                'alerts': [public_marker(row) for row in detail['alerts']] if timeframe == '3m' else []}

    return app
