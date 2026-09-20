"""Date-bound replay candidates from private evidence, bounded by known-at time."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import (ActiveUniverseMember, DiscoveryMembership,
    ResearchObservation, WatchlistSymbol, WatchlistUpload)


def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class HistoricalUniverseRepository:
    def __init__(self, engine):
        self.engine = engine

    def for_date(self, trading_date):
        candidates = self.candidates_for_date(trading_date)
        forming = {item['symbol'] for item in candidates if item['forming']}
        discovery = {item['symbol'] for item in candidates if item['discovery']}
        scanned = {item['symbol'] for item in candidates if item['scanned']}
        all_symbols = scanned | discovery
        groups = [
            {'id': 'FORMING', 'label': 'Forming that day',
             'symbols': sorted(forming)},
            {'id': 'DISCOVERY', 'label': 'Discovery candidates',
             'symbols': sorted(discovery - forming)},
            {'id': 'ALL_SCANNED', 'label': 'All scanned',
             'symbols': sorted(scanned - forming - discovery)},
        ]
        return {'trading_date': trading_date, 'symbols': sorted(all_symbols),
                'groups': groups, 'recorded': bool(all_symbols)}

    def candidates_for_date(self, trading_date, *, as_of=None):
        """Return symbols backed by same-date evidence known at ``as_of``.

        Each evidence source uses the timestamp that first proves the scanner
        knew the membership. A missing source timestamp is not inferred from
        another table or backfilled from the date alone.
        """
        cutoff = _utc(as_of) if as_of is not None else None
        result = {}

        def add(symbol, known_at, *, source=None, kind, sector=None, forming=False):
            known_at = _utc(known_at)
            if known_at is None or (cutoff is not None and known_at > cutoff):
                return
            value = result.setdefault(symbol, {'symbol': symbol, 'sources': set(),
                'sector': None, 'forming': False, 'discovery': False, 'scanned': False,
                'first_known_at': known_at})
            value['first_known_at'] = min(value['first_known_at'], known_at)
            value['sector'] = value['sector'] or sector
            value['forming'] |= forming
            value['scanned'] |= kind in ('observation', 'active')
            value['discovery'] |= kind == 'discovery'
            if source:
                value['sources'].add(source)

        with Session(self.engine) as session:
            observations = session.execute(select(
                ResearchObservation.symbol, ResearchObservation.discovery_sources,
                ResearchObservation.sector, ResearchObservation.setup_state,
                ResearchObservation.observed_at, ResearchObservation.created_at).where(
                    ResearchObservation.trading_date == trading_date)).all()
            memberships = session.execute(select(
                DiscoveryMembership.symbol, DiscoveryMembership.source_type,
                DiscoveryMembership.first_seen_at).where(
                    DiscoveryMembership.trading_date == trading_date)).all()
            active = session.execute(select(
                ActiveUniverseMember.symbol, ActiveUniverseMember.sources,
                ActiveUniverseMember.sector, ActiveUniverseMember.updated_at,
                WatchlistUpload.uploaded_at, WatchlistSymbol.created_at,
                WatchlistSymbol.validation_status).join(
                    WatchlistUpload,
                    WatchlistUpload.id == ActiveUniverseMember.snapshot_id).outerjoin(
                    WatchlistSymbol,
                    (WatchlistSymbol.watchlist_upload_id == ActiveUniverseMember.snapshot_id) &
                    (WatchlistSymbol.symbol == ActiveUniverseMember.symbol)).where(
                        WatchlistUpload.date == trading_date)).all()

        for symbol, sources, sector, state, observed_at, created_at in observations:
            known_at = max(_utc(observed_at), _utc(created_at))
            for source in sources or []:
                add(symbol, known_at, source=source, kind='observation',
                    sector=sector, forming=state in ('FORMING_LONG', 'FORMING_SHORT'))
            # Old observations may lack source metadata. Their observation time
            # still proves the symbol itself had entered the scanned universe.
            if not sources:
                add(symbol, known_at, kind='observation', sector=sector,
                    forming=state in ('FORMING_LONG', 'FORMING_SHORT'))

        for symbol, source, first_seen_at in memberships:
            add(symbol, first_seen_at, source=source, kind='discovery')

        for symbol, sources, sector, updated_at, uploaded_at, symbol_created_at, validation in active:
            sources = sources or []
            if not sources:
                # The persisted membership row itself is evidence at publication.
                add(symbol, updated_at, kind='active', sector=sector)
                continue
            for source in sources:
                if source == 'UPLOADED_WATCHLIST':
                    if validation == 'validated' and symbol_created_at is not None:
                        known_at = max(_utc(uploaded_at), _utc(symbol_created_at))
                        add(symbol, known_at, source=source, kind='active', sector=sector)
                else:
                    # Active-universe rows are replaced on publication. Their
                    # update time is a conservative known-at bound for sources
                    # without a more specific persisted timestamp.
                    add(symbol, updated_at, source=source, kind='active', sector=sector)

        return [{**value, 'sources': sorted(value['sources'])}
                for value in sorted(result.values(), key=lambda row: row['symbol'])]
