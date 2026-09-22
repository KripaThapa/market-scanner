"""SQLAlchemy repository shared by the API and worker. Production uses PostgreSQL."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import math
import threading

from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from .database.config import make_engine
from .database.models import (ActiveUniverseMember, AppState, Alert, FormingSetup,
    ScanResultModel, SectorMetric, SectorSnapshot, WatchlistSymbol, WatchlistUpload,
    DiscoverySourceStatus)


def now():
    return datetime.now(timezone.utc)


def iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def finite(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def analysis_json(value):
    return {key: item if isinstance(item, str) else finite(item) for key, item in value.items()}


class Store:
    def __init__(self, engine=None):
        self.engine = engine or make_engine()
        # Only the test engine uses this fallback. Runtime locks are PostgreSQL advisory locks.
        self._test_locks = {}

    @contextmanager
    def session(self):
        with Session(self.engine) as session, session.begin():
            yield session

    def check_ready(self):
        with self.session() as session:
            if session.get(AppState, 1) is None:
                raise RuntimeError('Run Alembic migrations before starting services')

    def ping(self):
        with self.engine.connect() as connection:
            connection.execute(text('SELECT 1'))

    @contextmanager
    def claim_lock(self, name):
        key = {'scanner': 839201, 'upload': 839202}[name]
        if self.engine.dialect.name != 'postgresql':
            lock = self._test_locks.setdefault(name, threading.Lock())
            acquired = lock.acquire(blocking=False)
            try:
                yield acquired
            finally:
                if acquired:
                    lock.release()
            return
        with self.engine.connect() as connection:
            acquired = connection.execute(text('SELECT pg_try_advisory_lock(hashtext(current_schema()), :key)'), {'key': key}).scalar()
            connection.commit()
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(text('SELECT pg_advisory_unlock(hashtext(current_schema()), :key)'), {'key': key})
                    connection.commit()

    def set_state(self, **values):
        with self.session() as session:
            state = session.get(AppState, 1, with_for_update=True)
            for key, value in values.items():
                setattr(state, key, value)

    def state(self):
        with self.session() as session:
            return self.state_dict(session.get(AppState, 1))

    @staticmethod
    def state_dict(state):
        return {column.name: iso(value) if isinstance(value, datetime) else value
                for column in AppState.__table__.columns
                if column.name != 'id' for value in [getattr(state, column.name)]}

    def snapshot(self, symbols, *, source='config', filename=None, image_path=None,
                 candidates=(), rejected=()):
        timestamp = now()
        with self.session() as session:
            upload = WatchlistUpload(date=timestamp.date().isoformat(), source=source,
                original_filename=filename, stored_filename=image_path, uploaded_at=timestamp,
                processing_status='processing', candidates=list(candidates),
                candidate_count=len(candidates), validated_count=len(symbols))
            session.add(upload)
            session.flush()
            self._symbols(session, upload.id, symbols, rejected, timestamp)
            return upload.id

    def claim_processing_upload(self, *, stale_after=timedelta(minutes=10)):
        """Claim one durable image import, recovering an expired claim safely."""
        current = now()
        cutoff = current - stale_after
        with self.session() as session:
            upload = session.scalar(
                select(WatchlistUpload).where(
                    WatchlistUpload.source == 'image',
                    WatchlistUpload.processing_status == 'processing',
                    or_(WatchlistUpload.processing_claimed_at.is_(None),
                        WatchlistUpload.processing_claimed_at < cutoff),
                ).order_by(WatchlistUpload.uploaded_at, WatchlistUpload.id)
                .with_for_update(skip_locked=True).limit(1)
            )
            if upload is None:
                return None
            recovered = upload.processing_claimed_at is not None
            upload.processing_claimed_at = current
            upload.processing_attempts = (upload.processing_attempts or 0) + 1
            return {
                'id': upload.id,
                'filename': upload.original_filename,
                'image_path': upload.stored_filename,
                'attempt': upload.processing_attempts,
                'recovered': recovered,
            }

    @staticmethod
    def today_date():
        return now().date().isoformat()

    def current_snapshot_for_activation(self, snapshot_id):
        with self.session() as session:
            return self.snapshot_dict(session, session.get(WatchlistUpload, snapshot_id))

    def upload_status(self, snapshot_id):
        with self.session() as session:
            return self.snapshot_dict(session, session.get(WatchlistUpload, snapshot_id))

    @staticmethod
    def _symbols(session, upload_id, symbols, rejected, timestamp, rows=()):
        session.execute(delete(WatchlistSymbol).where(WatchlistSymbol.watchlist_upload_id == upload_id))
        notes = {row.symbol: row.original_note for row in rows}
        for symbol in symbols:
            session.add(WatchlistSymbol(watchlist_upload_id=upload_id, symbol=symbol,
                                       validation_status='validated', original_note=notes.get(symbol),
                                       created_at=timestamp))
        for item in rejected:
            session.add(WatchlistSymbol(watchlist_upload_id=upload_id, symbol=item['candidate'],
                validation_status='rejected', rejection_reason=item['reason'], created_at=timestamp))

    def update_import(self, snapshot_id, imported):
        from dataclasses import asdict
        with self.session() as session:
            upload = session.get(WatchlistUpload, snapshot_id)
            upload.candidates = list(imported.candidates)
            upload.candidate_count = len(imported.candidates)
            upload.validated_count = len(imported.validated)
            upload.processed_at = now()
            upload.processing_claimed_at = None
            upload.processing_status = 'ready_for_review'
            self._symbols(session, snapshot_id, imported.validated,
                          [asdict(item) for item in imported.rejected], now(), imported.rows)

    def activate(self, snapshot_id, *, expected_active=None):
        """Compare-and-set protects fallback/day rollover from racing a new upload."""
        with self.session() as session:
            state = session.get(AppState, 1, with_for_update=True)
            if expected_active is not None and (state.active_watchlist_id or 0) != expected_active:
                return False
            upload = session.get(WatchlistUpload, snapshot_id)
            if not upload.validated_count:
                raise ValueError('Cannot activate an empty watchlist')
            state.active_watchlist_id = snapshot_id
            for setup in session.scalars(select(FormingSetup).where(FormingSetup.active.is_(True))):
                setup.active = False
            upload.processing_status = 'queued'
            upload.processed_at = now()
            return True

    def fail(self, snapshot_id, error):
        with self.session() as session:
            upload = session.get(WatchlistUpload, snapshot_id)
            upload.processing_status = 'failed'
            upload.error = error
            upload.processed_at = now()
            upload.processing_claimed_at = None

    @staticmethod
    def snapshot_dict(session, upload):
        if upload is None:
            return None
        symbols = session.scalars(select(WatchlistSymbol).where(
            WatchlistSymbol.watchlist_upload_id == upload.id).order_by(WatchlistSymbol.id)).all()
        return {'id': upload.id, 'date': upload.date, 'source': upload.source,
                'filename': upload.original_filename, 'created_at': iso(upload.uploaded_at),
                'processed_at': iso(upload.processed_at), 'status': upload.processing_status,
                'candidate_count': upload.candidate_count, 'validated_count': upload.validated_count,
                'candidates': upload.candidates,
                'symbols': [s.symbol for s in symbols if s.validation_status == 'validated'],
                'symbol_rows': [{'symbol': s.symbol, 'original_note': s.original_note}
                                for s in symbols if s.validation_status == 'validated'],
                'rejected': [{'candidate': s.symbol, 'reason': s.rejection_reason}
                             for s in symbols if s.validation_status == 'rejected'], 'error': upload.error}

    def current_snapshot(self):
        with self.session() as session:
            state = session.get(AppState, 1)
            return self.snapshot_dict(session, session.get(WatchlistUpload, state.current_snapshot)
                                      if state.current_snapshot else None)

    def active_snapshot(self):
        with self.session() as session:
            state = session.get(AppState, 1)
            return self.snapshot_dict(session, session.get(WatchlistUpload, state.active_watchlist_id)
                                      if state.active_watchlist_id else None)

    def today_active_uploaded_snapshot(self):
        """Return today's active image upload without exposing it through public reads."""
        active = self.active_snapshot()
        if active and active['source'] == 'image' and active['date'] == now().date().isoformat():
            return active
        return None

    def latest_upload(self):
        with self.session() as session:
            return self.snapshot_dict(session, session.scalars(select(WatchlistUpload).where(
                WatchlistUpload.source == 'image').order_by(WatchlistUpload.id.desc()).limit(1)).first())

    def publish(self, snapshot_id, results, sector_map=None, errors=None, *,
                research_settings=None, strategy_thresholds=None, universe=None):
        timestamp, sectors = now(), {}
        sector_map, errors = sector_map or {}, errors or {}
        from research.config import load_settings
        from research.collector import collect_publication
        from ripster_scanner.config import forming_thresholds
        from discovery.candle_state import candle_state
        research_settings = research_settings or load_settings()
        strategy_thresholds = strategy_thresholds or forming_thresholds()
        if universe is None:
            universe = {result.symbol: {'symbol': result.symbol,
                'sources': ['UPLOADED_WATCHLIST'], 'source_metrics': {},
                'sector': sector_map.get(result.symbol, 'UNKNOWN'),
                'metadata_source': 'config/sectors.json' if result.symbol in sector_map else 'UNAVAILABLE'}
                for result in results}
        sector_map = {symbol: item['sector'] for symbol, item in universe.items()}
        with self.session() as session:
            state = session.get(AppState, 1, with_for_update=True)
            if state.active_watchlist_id != snapshot_id:
                return False  # A newer watchlist became active while this scan ran.
            upload = session.get(WatchlistUpload, snapshot_id)
            sector_groups = {}
            for result in results:
                sector = sector_map.get(result.symbol, 'UNKNOWN')
                group = sector_groups.setdefault(sector, {'symbols': [], 'bullish': 0,
                    'bearish': 0, 'mixed': 0, 'forming_long': 0, 'forming_short': 0})
                group['symbols'].append(result.symbol)
                trend = (result.analysis_10m or {}).get('trend')
                if trend == 'BULLISH': group['bullish'] += 1
                if trend == 'BEARISH': group['bearish'] += 1
                if trend == 'MIXED': group['mixed'] += 1
                if result.forming.state == 'FORMING_LONG': group['forming_long'] += 1
                if result.forming.state == 'FORMING_SHORT': group['forming_short'] += 1
            sector_rows = {}
            for sector, group in sector_groups.items():
                row = SectorSnapshot(snapshot_id=snapshot_id, sector=sector,
                    observed_at=timestamp, trading_date=research_settings.local_date(timestamp).isoformat(),
                    symbols=group['symbols'], symbol_count=len(group['symbols']),
                    bullish_count=group['bullish'], bearish_count=group['bearish'],
                    mixed_count=group['mixed'], forming_long_count=group['forming_long'],
                    forming_short_count=group['forming_short'])
                session.add(row)
                sector_rows[sector] = row
            session.flush()
            collect_publication(session, upload, results, sector_map, errors, timestamp,
                                research_settings, strategy_thresholds, universe=universe,
                                sector_snapshot_ids={name: row.id for name, row in sector_rows.items()})
            session.execute(delete(ScanResultModel).where(ScanResultModel.snapshot_id == snapshot_id))
            session.execute(delete(SectorMetric).where(SectorMetric.snapshot_id == snapshot_id))
            session.execute(delete(ActiveUniverseMember).where(
                ActiveUniverseMember.snapshot_id == snapshot_id))
            active_setups = {item.symbol: item for item in session.scalars(select(FormingSetup).where(
                FormingSetup.snapshot_id == snapshot_id, FormingSetup.active.is_(True))).all()}
            seen_setups = set()
            for result in results:
                ten, three = result.analysis_10m or {}, result.analysis_3m or {}
                trend = ten.get('trend', 'NO DATA')
                session.add(ScanResultModel(snapshot_id=snapshot_id, symbol=result.symbol,
                    context_10m=trend, context_3m=three.get('trend', 'NO DATA'),
                    vwap_position=ten.get('vwap_position'), price=finite(ten.get('close')),
                    scanned_at=timestamp, vwap=finite(ten.get('vwap')),
                    **{f'ema_{span}': finite(ten.get(f'ema_{span}')) for span in (5, 12, 34, 50)},
                    analysis_3m=analysis_json(three),
                    candles_10m=result.candles_10m, candles_3m=result.candles_3m,
                    error=errors.get(result.symbol)))
                member = universe.get(result.symbol, {})
                start = result.candles_3m[-1]['timestamp'] if result.candles_3m else None
                candle = candle_state(start, '3m', result.evaluated_at or timestamp)
                session.add(ActiveUniverseMember(snapshot_id=snapshot_id, symbol=result.symbol,
                    sources=member.get('sources', []),
                    source_metrics=member.get('source_metrics', {}),
                    sector=sector_map.get(result.symbol, 'UNKNOWN'),
                    candle_state=candle, decision_eligible=result.has_data and
                    result.symbol not in errors, updated_at=timestamp))
                forming = result.forming
                if forming.state != 'NONE' and result.symbol not in errors:
                    seen_setups.add(result.symbol)
                    setup = active_setups.get(result.symbol)
                    if setup is not None and setup.first_candle_at is None and result.forming_candle_at:
                        # Older V1 rows predate candle timestamps. Preserve them as
                        # history and start a precisely anchored chart record.
                        setup.active = False
                        setup = None
                    if setup is None:
                        setup = FormingSetup(snapshot_id=snapshot_id, symbol=result.symbol,
                                             detected_at=timestamp, active=True,
                                             first_candle_at=result.forming_candle_at)
                        session.add(setup)
                    setup.last_seen_at = timestamp
                    setup.context_10m = trend
                    setup.setup_state = forming.state.value
                    setup.reason = forming.reason
                    setup.distance_status = f'{forming.cloud_distance_pct * 100:.3f}% from 5/12 cloud'
                    setup.price = finite(three.get('close'))
                    setup.vwap_position = three.get('vwap_position')
                    for span in (5, 12, 34, 50):
                        setattr(setup, f'ema_{span}', finite(three.get(f'ema_{span}')))
                sector = sector_map.get(result.symbol, 'Unclassified')
                group = sectors.setdefault(sector, {'symbols': [], 'bullish': 0, 'bearish': 0})
                group['symbols'].append(result.symbol)
                group['bullish'] += trend == 'BULLISH'
                group['bearish'] += trend == 'BEARISH'
            for symbol, setup in active_setups.items():
                if symbol not in seen_setups:
                    setup.active = False
            for sector, group in sectors.items():
                session.add(SectorMetric(snapshot_id=snapshot_id, sector=sector,
                    symbols=group['symbols'], symbol_count=len(group['symbols']),
                    bullish_count=group['bullish'], bearish_count=group['bearish'], calculated_at=timestamp))
            upload.processing_status = 'scanned'
            upload.error = None
            state.current_snapshot = snapshot_id
            state.last_updated = timestamp
            state.last_error = f'{len(errors)} symbol(s) failed; see individual rows.' if errors else None
            return True

    def read(self):
        # A short shared row lock prevents mixing different publications under READ COMMITTED.
        with self.session() as session:
            state = session.scalar(select(AppState).where(AppState.id == 1).with_for_update(read=True))
            snapshot_id = state.active_watchlist_id
            upload = session.get(WatchlistUpload, snapshot_id) if snapshot_id else None
            active = self.snapshot_dict(session, upload)
            results = session.scalars(select(ScanResultModel).where(
                ScanResultModel.snapshot_id == snapshot_id).order_by(ScanResultModel.id)).all()
            by_symbol = {r.symbol: r for r in results}
            members = session.scalars(select(ActiveUniverseMember).where(
                ActiveUniverseMember.snapshot_id == snapshot_id).order_by(
                    ActiveUniverseMember.symbol)).all()
            rows = []
            watchlist_symbols = (active['symbols'] if active and active['source'] != 'discovery' else [])
            for symbol in watchlist_symbols:
                r = by_symbol.get(symbol)
                rows.append({'symbol': symbol, 'snapshot_id': snapshot_id,
                    'context_10m': r.context_10m if r else 'PENDING',
                    'context_3m': r.context_3m if r else 'PENDING',
                    'vwap_position': r.vwap_position if r else None,
                    'latest_price': r.price if r else None, 'scanned_at': iso(r.scanned_at) if r else None,
                    'error': r.error if r else None})
            universe = []
            for member in members:
                r = by_symbol.get(member.symbol)
                setup = session.scalar(select(FormingSetup).where(
                    FormingSetup.snapshot_id == snapshot_id,
                    FormingSetup.symbol == member.symbol, FormingSetup.active.is_(True)))
                mover = member.source_metrics.get('TOP_GAINER') or member.source_metrics.get('TOP_LOSER') or {}
                universe.append({'symbol': member.symbol, 'sector': member.sector,
                    'sources': member.sources, 'source_metrics': member.source_metrics,
                    'percent_change': mover.get('percent_change'),
                    'context_10m': r.context_10m if r else 'PENDING',
                    'context_3m': r.context_3m if r else 'PENDING',
                    'setup_state': setup.setup_state if setup else 'NONE',
                    'latest_price': r.price if r else None,
                    'candle_state': member.candle_state,
                    'decision_eligible': member.decision_eligible,
                    'scanned_at': iso(r.scanned_at) if r else None,
                    'error': r.error if r else None})
            setups = [{'id': r.id, 'symbol': r.symbol, 'direction': 'LONG' if r.setup_state == 'FORMING_LONG' else 'SHORT',
                       'context_10m': r.context_10m, 'setup_state': r.setup_state,
                       'reason': r.reason, 'distance_status': r.distance_status,
                       'price': r.price, 'vwap_position': r.vwap_position,
                       **{f'ema_{span}': getattr(r, f'ema_{span}') for span in (5, 12, 34, 50)},
                       'first_detected_at': iso(r.detected_at), 'last_seen_at': iso(r.last_seen_at)} for r in session.scalars(select(FormingSetup).where(
                           FormingSetup.snapshot_id == snapshot_id, FormingSetup.active.is_(True)).order_by(FormingSetup.detected_at.desc()))]
            alerts = [{'id': r.id, 'symbol': r.symbol, 'timestamp': iso(r.created_at),
                       'alert_type': r.alert_type, 'reason': r.reason, 'destination': r.destination,
                       'delivery_status': r.delivery_status} for r in session.scalars(select(Alert).order_by(
                           Alert.created_at.desc(), Alert.id.desc()).limit(200))]
            sectors = [{'sector': r.sector, 'symbols': r.symbols,
                        'symbol_count': r.symbol_count, 'bullish_count': r.bullish_count,
                        'bearish_count': r.bearish_count, 'mixed_count': r.mixed_count,
                        'forming_long_count': r.forming_long_count,
                        'forming_short_count': r.forming_short_count,
                        'average_percent_change': None, 'average_volatility': None,
                        'relative_strength': None, 'updated_at': iso(r.observed_at)}
                       for r in session.scalars(select(SectorSnapshot).where(
                           SectorSnapshot.snapshot_id == snapshot_id,
                           SectorSnapshot.observed_at == state.last_updated))]
            sectors.sort(key=lambda item: (-len(item['symbols']), item['sector']))
            latest = session.scalars(select(WatchlistUpload).where(WatchlistUpload.source == 'image').order_by(
                WatchlistUpload.id.desc()).limit(1)).first()
            public_state = self.state_dict(state)
            if state.current_snapshot != snapshot_id:
                public_state['last_updated'] = None
            return {'state': public_state, 'watchlist': rows, 'universe': universe,
                    'setups': setups, 'alerts': alerts,
                    'sectors': sectors, 'latest_upload': self.snapshot_dict(session, latest),
                    'active_watchlist': active}

    def symbol_detail(self, symbol):
        """Read metadata and both chart frames from one committed scan snapshot."""
        with self.session() as session:
            state = session.scalar(select(AppState).where(AppState.id == 1).with_for_update(read=True))
            snapshot_id = state.active_watchlist_id
            if not snapshot_id or (session.scalar(select(WatchlistSymbol.id).where(
                WatchlistSymbol.watchlist_upload_id == snapshot_id,
                WatchlistSymbol.symbol == symbol,
                WatchlistSymbol.validation_status == 'validated')) is None and
                session.scalar(select(ActiveUniverseMember.id).where(
                    ActiveUniverseMember.snapshot_id == snapshot_id,
                    ActiveUniverseMember.symbol == symbol)) is None):
                return None
            row = session.scalar(select(ScanResultModel).where(
                ScanResultModel.snapshot_id == snapshot_id, ScanResultModel.symbol == symbol))
            setup = session.scalar(select(FormingSetup).where(
                FormingSetup.snapshot_id == snapshot_id, FormingSetup.symbol == symbol,
                FormingSetup.active.is_(True)))
            member = session.scalar(select(ActiveUniverseMember).where(
                ActiveUniverseMember.snapshot_id == snapshot_id,
                ActiveUniverseMember.symbol == symbol))
            return {
                'symbol': symbol, 'snapshot_id': snapshot_id,
                'scanned_at': iso(row.scanned_at) if row else None,
                'context_10m': row.context_10m if row else 'PENDING',
                'context_3m': row.context_3m if row else 'PENDING',
                'vwap_position': row.vwap_position if row else None,
                'latest_price': row.price if row else None,
                'error': row.error if row else None,
                'setup_state': setup.setup_state if setup else 'NONE',
                'candle_state': member.candle_state if member else None,
                'reason': setup.reason if setup else None,
                'first_detected_at': iso(setup.detected_at) if setup else None,
                'first_candle_at': setup.first_candle_at if setup else None,
                'last_seen_at': iso(setup.last_seen_at) if setup else None,
                'candles_10m': row.candles_10m or [] if row else [],
                'candles_3m': row.candles_3m or [] if row else [],
            }
