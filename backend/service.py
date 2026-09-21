"""Image validation persists a watchlist; only the separate worker scans it."""

from dataclasses import asdict

from ripster_scanner.config import load_config, asset_directory_uses_paper
from ripster_scanner.market_data import fetch_active_symbols
from ripster_scanner.watchlist import validate_candidates
from ripster_scanner.watchlist_image import extract_image_tokens

from .store import now, iso


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
            snapshot_id, report = None, None
            try:
                snapshot_id = self.store.snapshot((), source='image', filename=filename, image_path=str(path))
                tokens = extract_image_tokens(path)
                config = load_config(symbols=())
                directory = fetch_active_symbols(config.api_key, config.secret_key,
                                                 paper=asset_directory_uses_paper())
                imported = validate_candidates(tokens, directory)
                self.store.update_import(snapshot_id, imported)
                rejected = [asdict(item) for item in imported.rejected]
                report = {'status': 'queued' if activate else 'ready_for_review',
                          'candidate_count': len(imported.candidates),
                          'validated_count': len(imported.validated), 'validated_symbols': list(imported.validated),
                          'rejected': [item['candidate'] for item in rejected], 'rejection_details': rejected,
                          'processed_at': iso(now()), 'scan_started': False, 'scan_completed': False,
                          'snapshot_id': snapshot_id}
                if not imported.validated:
                    raise ImportFailed('No validated ticker symbols. Previous watchlist retained.', report)
                if activate:
                    self.store.activate(snapshot_id)
                return report
            except Exception as exc:
                message = (str(exc) if isinstance(exc, ImportFailed) else
                           'Watchlist processing failed. Check Tesseract, server credentials and Alpaca access. Previous watchlist retained.')
                if snapshot_id is not None:
                    self.store.fail(snapshot_id, message)
                if report:
                    report['status'] = 'error'
                raise ImportFailed(message, report) from exc
