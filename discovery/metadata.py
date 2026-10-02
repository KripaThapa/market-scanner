"""Persistent reference cache refreshed once at the universe boundary.

The scanner's existing single-worker lock serializes runtime refreshes. No database
transaction is held open during HTTP requests. Failures never erase known values.
"""

from datetime import timedelta, timezone
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import SymbolMetadata
from .metadata_provider import MetadataResult, SymbolMetadataProvider, usable

log = logging.getLogger(__name__)
FIELDS = ('company_name', 'sector', 'industry', 'cik', 'isin', 'cusip', 'exchange', 'country')
LIMITS = dict(zip(FIELDS, (240, 100, 120, 20, 20, 20, 80, 80)))


def utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


class SymbolMetadataService:
    ttl = timedelta(days=7)
    retry_interval = timedelta(days=1)
    max_requests = 40
    budget_seconds = 20

    def __init__(self, engine, provider: SymbolMetadataProvider | None = None):
        self.engine = engine
        self.provider = provider

    def resolve(self, symbols, fallback=None, *, at):
        at = utc(at)
        symbols = tuple(dict.fromkeys(symbols))
        fallback = fallback or {}
        result = {symbol: {'sector': usable(fallback.get(symbol), 100) or 'UNKNOWN',
                           'industry': None, 'metadata_source': 'UNAVAILABLE'} for symbol in symbols}
        try:
            with Session(self.engine) as session:
                cached = {row.symbol: row for row in session.scalars(
                    select(SymbolMetadata).where(SymbolMetadata.symbol.in_(symbols)))}
            for symbol, row in cached.items():
                result[symbol] = self._view(row)
        except Exception:
            log.warning('Metadata cache unavailable; continuing universe processing')
            return result
        started, calls, unavailable = time.monotonic(), 0, False
        for symbol in symbols:
            row = cached.get(symbol)
            if row and row.next_refresh_at and utc(row.next_refresh_at) > at:
                continue
            if row and row.last_status == 'OK' and utc(row.retrieved_at) + self.ttl > at:
                continue
            if calls >= self.max_requests or time.monotonic() - started >= self.budget_seconds:
                break  # Remaining symbols stay due for a later cycle.
            # Save a retry deadline BEFORE HTTP, including for crashes/restarts.
            try:
                with Session(self.engine) as session, session.begin():
                    record = session.get(SymbolMetadata, symbol)
                    if record is None:
                        sector = usable(fallback.get(symbol), 100)
                        record = SymbolMetadata(symbol=symbol, sector=sector or 'UNKNOWN',
                            metadata_source='config/sectors.json' if sector else 'UNAVAILABLE',
                            retrieved_at=at, updated_at=at)
                        session.add(record)
                    elif not usable(record.sector, 100) and usable(fallback.get(symbol), 100):
                        record.sector = usable(fallback[symbol], 100)
                        record.metadata_source = 'config/sectors.json'
                        record.updated_at = at
                    record.last_attempt_at = at
                    record.next_refresh_at = at + self.retry_interval
                    record.last_status = 'UNAVAILABLE'
                    session.flush()
                    view = self._view(record)
                result[symbol] = view
            except Exception:
                log.warning('Metadata cache write failed; continuing with cached classification')
                continue
            outcome = MetadataResult('UNAVAILABLE')
            if self.provider is not None and not unavailable:
                calls += 1
                try:
                    outcome = self.provider.fetch(symbol)
                except Exception:
                    # Third-party exception strings/URLs are never logged.
                    outcome = MetadataResult('UNAVAILABLE')
            if outcome.status not in {'OK', 'PARTIAL', 'NOT_FOUND'}:
                unavailable = True  # Avoid N timeouts/auth/rate-limit failures in one universe.
            try:
                with Session(self.engine) as session, session.begin():
                    record = session.get(SymbolMetadata, symbol)
                    record.last_status = outcome.status if outcome.status in {
                        'OK', 'PARTIAL', 'NOT_FOUND', 'TIMEOUT', 'HTTP_ERROR', 'MALFORMED'
                    } else 'UNAVAILABLE'
                    metadata = outcome.metadata
                    if metadata and metadata.symbol == symbol and outcome.status in {'OK', 'PARTIAL'}:
                        accepted = False
                        for field in FIELDS:
                            value = usable(getattr(metadata, field), LIMITS[field])
                            if value:
                                setattr(record, field, value)
                                accepted = True
                        if accepted:
                            record.metadata_source = self.provider.name
                            record.retrieved_at = at
                            record.updated_at = at
                            record.next_refresh_at = at + (self.ttl if outcome.status == 'OK' else self.retry_interval)
                    session.flush()
                    view = self._view(record)
                result[symbol] = view
            except Exception:
                log.warning('Metadata refresh could not be persisted; retaining cached classification')
        return result

    @staticmethod
    def _view(row):
        return {'sector': usable(row.sector, 100) or 'UNKNOWN',
                'industry': row.industry, 'metadata_source': row.metadata_source}
