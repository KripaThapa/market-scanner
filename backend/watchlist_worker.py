"""Durable PostgreSQL-backed processor for staged private watchlist uploads."""

from pathlib import Path
import logging
import time

from .service import ImportFailed, ImportService


log = logging.getLogger(__name__)


class WatchlistProcessor:
    def __init__(self, store):
        self.store = store
        self.import_service = ImportService(store)

    def process_once(self):
        """Claim and process at most one upload; safe to call repeatedly."""
        with self.store.claim_lock('upload') as acquired:
            if not acquired:
                return False
            claim = self.store.claim_processing_upload()
            if claim is None:
                return False
            snapshot_id = claim['id']
            log.info('watchlist_import stage=claimed snapshot_id=%s attempt=%s recovered=%s',
                     snapshot_id, claim['attempt'], claim['recovered'])
            if claim['recovered']:
                log.info('watchlist_import stage=recovery snapshot_id=%s', snapshot_id)
            started = time.perf_counter()
            try:
                self.import_service.process_snapshot(
                    snapshot_id, Path(claim['image_path']), claim['filename'], activate=False)
            except ImportFailed:
                # ImportService has persisted the sanitized failure state.
                pass
            except Exception:
                self.store.fail(snapshot_id, 'Watchlist processing failed. Please upload the screenshot again.')
                log.info('watchlist_import stage=failed snapshot_id=%s failed_stage=worker elapsed_ms=%.1f',
                         snapshot_id, (time.perf_counter() - started) * 1000)
            return True
