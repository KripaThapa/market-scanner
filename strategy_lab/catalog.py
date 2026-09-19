"""Date-bound replay candidates from immutable/private historical records."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import (ActiveUniverseMember, DiscoveryMembership,
    ResearchObservation, WatchlistUpload)


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

    def candidates_for_date(self, trading_date):
        with Session(self.engine) as session:
            observations = session.execute(select(
                ResearchObservation.symbol, ResearchObservation.setup_state,
                ResearchObservation.discovery_sources, ResearchObservation.sector).where(
                    ResearchObservation.trading_date == trading_date)).all()
            memberships = session.execute(select(
                DiscoveryMembership.symbol, DiscoveryMembership.source_type).where(
                    DiscoveryMembership.trading_date == trading_date)).all()
            active = session.execute(select(ActiveUniverseMember.symbol,
                ActiveUniverseMember.sources, ActiveUniverseMember.sector).join(
                WatchlistUpload, WatchlistUpload.id == ActiveUniverseMember.snapshot_id).where(
                    WatchlistUpload.date == trading_date)).all()
        result = {}
        def item(symbol):
            return result.setdefault(symbol, {'symbol': symbol, 'sources': set(),
                'sector': None, 'forming': False, 'discovery': False, 'scanned': False})
        for symbol, state, sources, sector in observations:
            value = item(symbol)
            value['scanned'] = True
            value['forming'] |= state in ('FORMING_LONG', 'FORMING_SHORT')
            value['sources'].update(sources or [])
            value['sector'] = value['sector'] or sector
        for symbol, source in memberships:
            value = item(symbol)
            value['discovery'] = True
            value['sources'].add(source)
        for symbol, sources, sector in active:
            value = item(symbol)
            value['scanned'] = True
            value['sources'].update(sources or [])
            value['sector'] = value['sector'] or sector
        return [{**value, 'sources': sorted(value['sources'])}
                for value in sorted(result.values(), key=lambda row: row['symbol'])]
