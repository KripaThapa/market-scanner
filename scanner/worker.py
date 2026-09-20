"""Polling PostgreSQL worker. Ticker failures never terminate the service."""

from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import signal
import threading

from alpaca.data.historical import StockHistoricalDataClient
from backend.store import Store, now
from discovery.alpaca import AlpacaDiscoveryProvider
from discovery.config import DiscoverySettings, load_settings as load_discovery_settings
from discovery.service import DiscoveryService
from research.config import load_settings as load_research_settings
from ripster_scanner.config import load_config, load_watchlist
from ripster_scanner.provider import build_provider
from ripster_scanner.scan import ScanResult, scan_watchlist
from strategy_lab.market_calendar import USEquityMarketCalendar

log = logging.getLogger(__name__)


class ScannerWorker:
    def __init__(self, store, *, json_fallback=False, sector_path='config/sectors.json',
                 discovery_provider=None, discovery_settings=None):
        self.store = store
        self.json_fallback = json_fallback
        self.sector_path = Path(sector_path)
        self.discovery_provider = discovery_provider
        self.discovery_settings = discovery_settings
        self.equity_calendar = USEquityMarketCalendar()

    def sector_map(self):
        if not self.sector_path.exists():
            return {}
        mapping = json.loads(self.sector_path.read_text())
        if not isinstance(mapping, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                or not v.strip() for k, v in mapping.items()):
            raise ValueError('Invalid sector mapping')
        return {key.upper(): value.strip() for key, value in mapping.items()}

    def run_once(self):
        with self.store.claim_lock('scanner') as acquired:
            if not acquired:
                log.info('Another scanner owns the scan lock; skipping cycle')
                return 'busy'
            status = 'idle'
            try:
                self.store.set_state(status='scanning', last_attempt=now(), scanner_heartbeat=now())
                current = self.store.active_snapshot()
                if not current and self.json_fallback:
                    snapshot_id = self.store.snapshot(load_watchlist())
                    if not self.store.activate(snapshot_id, expected_active=0):
                        self.store.fail(snapshot_id, 'Superseded by a validated upload')
                    current = self.store.active_snapshot()
                settings = self.discovery_settings or load_discovery_settings()
                # Existing SQLite-backed tests and the standalone CLI keep their
                # existing watchlist-only path unless a fake source is injected.
                if self.store.engine.dialect.name != 'postgresql' and self.discovery_provider is None:
                    settings = DiscoverySettings(False, settings.interval_seconds, settings.top)
                research_settings = load_research_settings()
                current_time = now()
                inside_window = research_settings.inside_window(current_time)
                session_date = research_settings.local_date(current_time)
                try:
                    is_session = self.equity_calendar.is_session(session_date)
                except ValueError:
                    # Outside the bundled exchange calendar's supported range,
                    # fail closed for automatic discovery but keep active scans alive.
                    is_session = False
                    log.warning('XNYS session status unavailable for %s; automatic discovery skipped',
                                session_date.isoformat())
                can_discover = settings.enabled and inside_window and is_session
                if not current and not can_discover:
                    status = 'waiting'
                    if not settings.enabled:
                        log.info('Automatic discovery is disabled; no active watchlist; nothing to scan')
                    elif not inside_window:
                        log.info('Outside research window; no active watchlist; nothing to scan')
                    elif not is_session:
                        log.info('Non-XNYS session %s; automatic discovery skipped',
                                 session_date.isoformat())
                    return 'empty'
                if current:
                    log.info('Active universe available (%s symbols); scanning',
                             len(current['symbols']))
                    if settings.enabled and inside_window and not is_session:
                        log.info('Non-XNYS session %s; automatic discovery skipped',
                                 session_date.isoformat())
                    if current['source'] == 'discovery' and not is_session:
                        status = 'waiting'
                        log.info('Discovery-sourced active universe is not scanned outside XNYS sessions')
                        return 'empty'
                if current and current['date'] != now().date().isoformat() and current['source'] != 'discovery':
                    snapshot_id = self.store.snapshot(current['symbols'], source='rollover')
                    if not self.store.activate(snapshot_id, expected_active=current['id']):
                        self.store.fail(snapshot_id, 'Superseded by a newer watchlist')
                        return 'superseded'
                    current = self.store.active_snapshot()
                uploaded = tuple(current['symbols']) if current and current['source'] != 'discovery' else ()
                config = load_config(symbols=uploaded)
                provider = build_provider(config, client=StockHistoricalDataClient(
                    config.api_key, config.secret_key))
                discovery_provider = (self.discovery_provider or
                    AlpacaDiscoveryProvider(config.api_key, config.secret_key, top=settings.top)
                    if settings.enabled else self.discovery_provider)
                cycle_settings = (settings if is_session else DiscoverySettings(
                    False, settings.interval_seconds, settings.top))
                universe = DiscoveryService(self.store.engine, discovery_provider, cycle_settings,
                    research_settings).build_universe(uploaded, self.sector_map(), at=current_time)
                if not universe and not current:
                    status = 'waiting'
                    log.info('Discovery completed without an active universe; nothing to scan')
                    return 'empty'
                if not current or (current['source'] == 'discovery' and
                                   current['date'] != now().date().isoformat() and universe):
                    snapshot_id = self.store.snapshot(tuple(universe), source='discovery')
                    self.store.activate(snapshot_id, expected_active=current['id'] if current else 0)
                    current = self.store.active_snapshot()
                config = replace(config, symbols=tuple(universe))
                results, errors = [], {}
                for symbol in config.symbols:
                    try:
                        # Reuse the complete existing pipeline with a one-symbol config.
                        results.extend(scan_watchlist(replace(config, symbols=(symbol,)), provider))
                    except Exception:
                        log.warning('Market-data processing failed for %s; continuing', symbol)
                        results.append(ScanResult(symbol, source=provider.source))
                        errors[symbol] = 'Market-data request or calculation failed'
                if not self.store.publish(current['id'], results, self.sector_map(), errors,
                                          strategy_thresholds=config.forming, universe=universe):
                    log.info('Watchlist changed during scan; discarded superseded results')
                    return 'superseded'
                log.info('Published %s symbols (%s failures)', len(results), len(errors))
                return 'scanned'
            except Exception:
                # Provider exception strings may include private configuration. Do not log them.
                log.warning('Scan cycle failed; check credentials, database and sector configuration. Retrying next cycle.')
                self.store.set_state(last_error='Scan failed. Check worker credentials, database and sector configuration.')
                return 'failed'
            finally:
                self.store.set_state(status=status, scanner_heartbeat=now())


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    interval = int(os.getenv('SCANNER_INTERVAL_SECONDS', '60'))
    if interval < 1:
        raise ValueError('SCANNER_INTERVAL_SECONDS must be a positive integer')
    fallback = os.getenv('SCANNER_JSON_FALLBACK', 'false').lower()
    if fallback not in {'true', 'false'}:
        raise ValueError('SCANNER_JSON_FALLBACK must be true or false')
    store = Store()
    worker = ScannerWorker(store, json_fallback=fallback == 'true')
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            store.check_ready()
            store.set_state(scan_interval_seconds=interval)
            worker.run_once()
        except Exception:
            log.warning('Database unavailable; worker remains alive and will retry')
        stop.wait(interval)


if __name__ == '__main__':
    main()
