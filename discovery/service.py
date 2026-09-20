"""Refresh sources independently and retain current membership plus transition history."""

from datetime import timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import (DiscoveryEvent, DiscoveryMembership,
    DiscoverySourceStatus, SymbolMetadata)
from strategy_lab.market_calendar import USEquityMarketCalendar
from .domain import AUTOMATIC_SOURCES, DiscoveryItem, SourceType, normalize_symbol

log = logging.getLogger(__name__)


class DiscoveryService:
    def __init__(self, engine, provider, settings, research_settings, *, equity_calendar=None):
        self.engine = engine
        self.provider = provider
        self.settings = settings
        self.research_settings = research_settings
        self.equity_calendar = equity_calendar or USEquityMarketCalendar()

    @staticmethod
    def _record(session, source, items, at, trading_date, provider):
        existing = {row.symbol: row for row in session.scalars(select(DiscoveryMembership).where(
            DiscoveryMembership.trading_date == trading_date,
            DiscoveryMembership.source_type == source.value))}
        incoming = {item.symbol: item for item in items}
        for symbol, item in incoming.items():
            row = existing.get(symbol)
            changed = row is None or not row.active or row.rank != item.rank or row.metrics != item.metrics
            if row is None:
                row = DiscoveryMembership(trading_date=trading_date, symbol=symbol,
                    source_type=source.value, provider=provider, first_seen_at=at,
                    last_seen_at=at, active=True, rank=item.rank, metrics=item.metrics)
                session.add(row)
            else:
                row.last_seen_at = at
                row.active = True
                row.rank = item.rank
                row.metrics = item.metrics
                row.provider = provider
            if changed:
                session.add(DiscoveryEvent(trading_date=trading_date, symbol=symbol,
                    source_type=source.value, provider=provider, discovered_at=at,
                    active=True, rank=item.rank, metrics=item.metrics))
        for symbol, row in existing.items():
            if row.active and symbol not in incoming:
                row.active = False
                session.add(DiscoveryEvent(trading_date=trading_date, symbol=symbol,
                    source_type=source.value, provider=provider, discovered_at=at,
                    active=False, rank=row.rank, metrics=row.metrics))

    def build_universe(self, uploaded_symbols, sector_mapping=None, *, at):
        """Return unique symbols with every successful or last-known source."""
        at = at.astimezone(timezone.utc)
        trading_date = self.research_settings.local_date(at).isoformat()
        sector_mapping = sector_mapping or {}
        uploaded = [DiscoveryItem(symbol, SourceType.UPLOADED_WATCHLIST, 'Uploaded Watchlist', at)
                    for value in uploaded_symbols if (symbol := normalize_symbol(value))]
        results = {}
        with Session(self.engine) as session:
            status_rows = {row.source_type: row for row in session.scalars(
                select(DiscoverySourceStatus))}
        inside = self.research_settings.inside_window(at)
        try:
            is_session = self.equity_calendar.is_session(
                self.research_settings.local_date(at))
        except ValueError:
            is_session = False
        if self.settings.enabled and inside and not is_session:
            log.info('Non-XNYS session %s; automatic discovery skipped', trading_date)
        if self.settings.enabled and inside and is_session:
            for source in AUTOMATIC_SOURCES:
                status = status_rows.get(source.value)
                due = (status is None or status.last_attempt_at is None or
                       (at - (status.last_attempt_at.astimezone(timezone.utc)
                        if status.last_attempt_at.tzinfo else status.last_attempt_at.replace(tzinfo=timezone.utc)))
                       .total_seconds() >= self.settings.interval_seconds)
                if not due:
                    continue
                try:
                    results[source] = self.provider.fetch(source, at)
                except Exception:
                    results[source] = None
                    log.warning('Discovery source %s failed; retaining its last-known membership', source.value)
        with Session(self.engine) as session, session.begin():
            self._record(session, SourceType.UPLOADED_WATCHLIST, uploaded, at,
                         trading_date, 'Uploaded Watchlist')
            for source, items in results.items():
                status = session.get(DiscoverySourceStatus, source.value)
                if status is None:
                    status = DiscoverySourceStatus(source_type=source.value,
                        provider=self.provider.name, status='PENDING')
                    session.add(status)
                status.last_attempt_at = at
                if items is None:
                    status.status = 'FAILED'
                    status.error = 'Provider request failed; last-known membership retained'
                    continue
                status.status = 'OK' if items else 'EMPTY'
                status.last_success_at = at
                status.error = None
                self._record(session, source, items, at, trading_date, self.provider.name)
            memberships = session.scalars(select(DiscoveryMembership).where(
                DiscoveryMembership.trading_date == trading_date,
                DiscoveryMembership.active.is_(True))).all()
            universe = {}
            for row in memberships:
                entry = universe.setdefault(row.symbol, {'symbol': row.symbol, 'sources': [],
                    'source_metrics': {}, 'sector': 'UNKNOWN', 'metadata_source': 'UNAVAILABLE'})
                entry['sources'].append(row.source_type)
                if row.metrics:
                    entry['source_metrics'][row.source_type] = row.metrics
            for symbol, entry in universe.items():
                entry['sources'].sort()
                sector = sector_mapping.get(symbol) or 'UNKNOWN'
                metadata_source = 'config/sectors.json' if symbol in sector_mapping else 'UNAVAILABLE'
                metadata = session.get(SymbolMetadata, symbol)
                if metadata is None:
                    metadata = SymbolMetadata(symbol=symbol, sector=sector, industry=None,
                        metadata_source=metadata_source, retrieved_at=at, updated_at=at)
                    session.add(metadata)
                elif metadata.sector != sector or metadata.metadata_source != metadata_source:
                    metadata.sector = sector
                    metadata.metadata_source = metadata_source
                    metadata.updated_at = at
                entry['sector'] = metadata.sector
                entry['metadata_source'] = metadata.metadata_source
            return universe
