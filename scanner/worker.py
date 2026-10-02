"""Polling PostgreSQL worker. Ticker failures never terminate the service."""

from dataclasses import replace
from datetime import date
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time
from uuid import uuid4

from ripster_scanner.alpaca_http import StockHistoricalDataClient
from scanner.progress import error_category
from scanner.price_observation import PriceObservingProvider
from backend.level_alerts import trading_date
from backend.store import Store, now
from discovery.alpaca import AlpacaDiscoveryProvider
from discovery.config import load_settings as load_discovery_settings
from discovery.service import DiscoveryService
from discovery.metadata import SymbolMetadataService
from discovery.fmp import FMPMetadataProvider
from research.config import load_settings as load_research_settings
from ripster_scanner.config import load_config
from ripster_scanner.provider import build_provider
from ripster_scanner.scan import ScanResult, scan_watchlist
from strategy_lab.market_calendar import USEquityMarketCalendar

log = logging.getLogger(__name__)

# US stocks/ETFs use the existing Alpaca/IEX bar path. Spot VIX is unsupported.
CONTEXT_SYMBOLS = ('SPY', 'QQQ', 'MAGS', 'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA')


class ScannerWorker:
    def __init__(self, store, *, sector_path='config/sectors.json',
                 discovery_provider=None, discovery_settings=None, metadata_service=None):
        self.store = store
        self.sector_path = Path(sector_path)
        self.discovery_provider = discovery_provider
        self.discovery_settings = discovery_settings
        self.metadata_service = metadata_service or SymbolMetadataService(store.engine)
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
        cycle_id = uuid4().hex
        started = time.perf_counter()
        log.info('cycle=%s stage=cycle_started', cycle_id)
        try:
            outcome = self._run_once(cycle_id)
        except Exception as exc:
            log.warning('cycle=%s stage=cycle_failed duration_ms=%.1f error_type=%s',
                        cycle_id, (time.perf_counter() - started) * 1000, error_category(exc))
            raise
        log.info('cycle=%s stage=cycle_completed duration_ms=%.1f outcome=%s',
                 cycle_id, (time.perf_counter() - started) * 1000, outcome)
        return outcome

    def _run_once(self, cycle_id):
        with self.store.claim_lock('scanner') as acquired:
            if not acquired:
                log.info('Another scanner owns the scan lock; skipping cycle')
                return 'busy'
            status = 'idle'
            stage = 'state_update'
            try:
                self.store.set_state(status='scanning', last_attempt=now(), scanner_heartbeat=now())
                stage = 'universe_load'
                current_time = now()
                today = trading_date(current_time)
                try:
                    previous_day = self.equity_calendar.adjacent(date.fromisoformat(today), 'previous').isoformat()
                except ValueError:
                    previous_day = None
                    log.warning('XNYS session unavailable for %s; watchlist fallback skipped', today)
                current = self.store.active_snapshot()
                selected = self.store.scanner_watchlist(today, previous_day)
                uploaded = tuple(selected['symbols']) if selected else ()
                if selected and selected['trading_date'] == today:
                    if not current or current['id'] != selected['id']:
                        if not self.store.activate(selected['id'], expected_active=current['id'] if current else 0):
                            return 'superseded'
                    current = selected
                else:
                    # Membership-only snapshot: never re-activate yesterday's daily levels.
                    source = 'rollover' if selected else 'context'
                    symbols = uploaded or CONTEXT_SYMBOLS
                    if (not current or current['source'] != source
                            or trading_date(current['created_at']) != today
                            or tuple(current['symbols']) != symbols):
                        snapshot_id = self.store.snapshot(symbols, source=source)
                        if not self.store.activate(snapshot_id, expected_active=current['id'] if current else 0):
                            self.store.fail(snapshot_id, 'Superseded by a newer watchlist')
                            return 'superseded'
                        # Keep our publication identity even if an upload activates now.
                        current = self.store.upload_status(snapshot_id)
                log.info('cycle=%s stage=universe_loaded uploaded_symbols=%s', cycle_id, len(uploaded))
                settings = self.discovery_settings or load_discovery_settings()
                research_settings = load_research_settings()
                stage = 'configuration'
                config = load_config(symbols=uploaded)
                provider = build_provider(config, client=StockHistoricalDataClient(
                    config.api_key, config.secret_key))
                provider = PriceObservingProvider(provider)
                discovery_provider = (self.discovery_provider or
                    AlpacaDiscoveryProvider(config.api_key, config.secret_key, top=settings.top)
                    if settings.enabled else self.discovery_provider)
                stage = 'discovery'
                stage_started = time.perf_counter()
                log.info('cycle=%s stage=discovery_started', cycle_id)
                universe = DiscoveryService(self.store.engine, discovery_provider, settings,
                    research_settings, metadata_service=self.metadata_service).build_universe(uploaded, self.sector_map(), at=current_time,
                                                     cycle_id=cycle_id, context_symbols=CONTEXT_SYMBOLS)
                log.info('cycle=%s stage=discovery_completed duration_ms=%.1f',
                         cycle_id, (time.perf_counter() - stage_started) * 1000)
                config = replace(config, symbols=tuple(universe))
                results, errors = [], {}
                stage = 'scan'
                for symbol in config.symbols:
                    symbol_started = time.perf_counter()
                    log.info('cycle=%s symbol=%s stage=scan_started', cycle_id, symbol)
                    try:
                        # Reuse the complete existing pipeline with a one-symbol config.
                        results.extend(scan_watchlist(replace(config, symbols=(symbol,)), provider))
                    except Exception as exc:
                        log.warning('cycle=%s symbol=%s stage=scan_failed duration_ms=%.1f error_type=%s',
                                    cycle_id, symbol, (time.perf_counter() - symbol_started) * 1000,
                                    error_category(exc))
                        log.warning('Market-data processing failed for %s; continuing', symbol)
                        results.append(ScanResult(symbol, source=provider.source))
                        errors[symbol] = 'Market-data request or calculation failed'
                    else:
                        log.info('cycle=%s symbol=%s stage=scan_completed duration_ms=%.1f',
                                 cycle_id, symbol, (time.perf_counter() - symbol_started) * 1000)
                stage = 'publication'
                stage_started = time.perf_counter()
                log.info('cycle=%s stage=publication_started results=%s failures=%s',
                         cycle_id, len(results), len(errors))
                if trading_date(now()) != today:
                    return 'superseded'  # Re-select membership after a midnight-spanning fetch.
                published = self.store.publish(current['id'], results, self.sector_map(), errors,
                                               strategy_thresholds=config.forming, universe=universe,
                                               price_observations=provider.observations)
                log.info('cycle=%s stage=publication_completed duration_ms=%.1f published=%s',
                         cycle_id, (time.perf_counter() - stage_started) * 1000, published)
                if not published:
                    log.info('Watchlist changed during scan; discarded superseded results')
                    return 'superseded'
                log.info('Published %s symbols (%s failures)', len(results), len(errors))
                return 'scanned'
            except Exception as exc:
                log.warning('cycle=%s stage=%s_failed error_type=%s',
                            cycle_id, stage, error_category(exc))
                # Provider exception strings may include private configuration. Do not log them.
                log.warning('Scan cycle failed; check credentials, database and sector configuration. Retrying next cycle.')
                self.store.set_state(last_error='Scan failed. Check worker credentials, database and sector configuration.')
                return 'failed'
            finally:
                try:
                    self.store.set_state(status=status, scanner_heartbeat=now())
                except Exception as exc:
                    log.warning('cycle=%s stage=heartbeat_failed error_type=%s',
                                cycle_id, error_category(exc))
                    raise


def main():
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    interval = int(os.getenv('SCANNER_INTERVAL_SECONDS', '60'))
    if interval < 1:
        raise ValueError('SCANNER_INTERVAL_SECONDS must be a positive integer')
    store = Store()
    key = os.getenv('FMP_API_KEY', '').strip()
    metadata = SymbolMetadataService(store.engine, FMPMetadataProvider(key) if key else None)
    worker = ScannerWorker(store, metadata_service=metadata)
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
