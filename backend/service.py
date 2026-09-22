"""Image validation persists a watchlist; only the separate worker scans it."""

from dataclasses import asdict
import logging
import time

from ripster_scanner.config import load_config, asset_directory_uses_paper
from ripster_scanner.market_data import fetch_active_symbols
from ripster_scanner.watchlist import extract_watchlist_rows, validate_candidates, validate_watchlist_rows
from ripster_scanner.watchlist_image import extract_image_tokens

from .store import now, iso


log = logging.getLogger(__name__)


class BusyError(Exception):
    pass


class ImportFailed(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


class ImportService:
    def __init__(self, store):
        self.store = store

    def import_image(self, path, filename, *, activate=True):
        with self.store.claim_lock('upload') as acquired:
            if not acquired:
                raise BusyError('Another watchlist import is already running. Try again when it finishes.')
            snapshot_id = self.store.snapshot((), source='image', filename=filename, image_path=str(path))
            return self.process_snapshot(snapshot_id, path, filename, activate=activate)

    def process_snapshot(self, snapshot_id, path, filename, *, activate=False):
        """Process a previously persisted upload; callers provide concurrency control."""
        started = time.perf_counter()
        stage = 'started'
        report = None
        log.info('watchlist_import stage=started filename=%s activate=%s', filename, activate)
        try:
            log.info('watchlist_import stage=snapshot_created snapshot_id=%s elapsed_ms=%.1f',
                     snapshot_id, (time.perf_counter() - started) * 1000)

            stage = 'ocr'
            ocr_started = time.perf_counter()
            log.info('watchlist_import stage=ocr_started snapshot_id=%s', snapshot_id)
            tokens = extract_image_tokens(path)
            rows = extract_watchlist_rows(tokens)
            log.info('watchlist_import stage=ocr_completed snapshot_id=%s elapsed_ms=%.1f token_count=%s row_count=%s',
                     snapshot_id, (time.perf_counter() - ocr_started) * 1000, len(tokens), len(rows))

            config = load_config(symbols=())
            stage = 'provider_directory'
            provider_started = time.perf_counter()
            log.info('watchlist_import stage=provider_directory_started snapshot_id=%s', snapshot_id)
            directory = fetch_active_symbols(config.api_key, config.secret_key,
                                             paper=asset_directory_uses_paper())
            log.info('watchlist_import stage=provider_directory_completed snapshot_id=%s elapsed_ms=%.1f symbol_count=%s',
                     snapshot_id, (time.perf_counter() - provider_started) * 1000, len(directory))

            stage = 'candidate_validation'
            validation_started = time.perf_counter()
            # Keep the legacy flat-token path for old/test OCR adapters which
            # do not provide geometry. Real screenshot imports are row-aware.
            imported = (validate_watchlist_rows(rows, directory) if rows
                        else validate_candidates(tokens, directory))
            log.info('watchlist_import stage=candidate_validation_completed snapshot_id=%s elapsed_ms=%.1f candidate_count=%s validated_count=%s rejected_count=%s',
                     snapshot_id, (time.perf_counter() - validation_started) * 1000,
                     len(imported.candidates), len(imported.validated), len(imported.rejected))

            stage = 'database_update'
            persistence_started = time.perf_counter()
            self.store.update_import(snapshot_id, imported)
            log.info('watchlist_import stage=database_update_completed snapshot_id=%s elapsed_ms=%.1f',
                     snapshot_id, (time.perf_counter() - persistence_started) * 1000)
            rejected = [asdict(item) for item in imported.rejected]
            report = {'status': 'queued' if activate else 'ready_for_review',
                      'candidate_count': len(imported.candidates),
                      'validated_count': len(imported.validated), 'validated_symbols': list(imported.validated),
                      'rejected': [item['candidate'] for item in rejected], 'rejection_details': rejected,
                      'processed_at': iso(now()), 'scan_started': False, 'scan_completed': False,
                      'snapshot_id': snapshot_id}
            report['validated_rows'] = [row.as_dict() for row in imported.rows]
            if not imported.validated:
                raise ImportFailed('No validated ticker symbols. Previous watchlist retained.', report)
            if activate:
                stage = 'activation'
                self.store.activate(snapshot_id)
            log.info('watchlist_import stage=completed snapshot_id=%s elapsed_ms=%.1f validated_count=%s',
                     snapshot_id, (time.perf_counter() - started) * 1000, len(imported.validated))
            return report
        except Exception as exc:
            log.info('watchlist_import stage=failed snapshot_id=%s failed_stage=%s elapsed_ms=%.1f',
                     snapshot_id if snapshot_id is not None else 'none', stage,
                     (time.perf_counter() - started) * 1000)
            message = (str(exc) if isinstance(exc, ImportFailed) else
                       'Watchlist processing failed. Check Tesseract, server credentials and Alpaca access. Previous watchlist retained.')
            if snapshot_id is not None:
                self.store.fail(snapshot_id, message)
            if report:
                report['status'] = 'error'
            raise ImportFailed(message, report) from exc
