"""Scheduled or manual objective outcome analysis; never changes scanner rules."""

import argparse
from datetime import date, datetime, timezone
import logging
import signal
import threading
import os

from backend.database.config import make_engine
from .config import load_settings
from .repository import ResearchRepository

log = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Calculate objective research outcomes')
    parser.add_argument('--date', type=date.fromisoformat,
                        help='Research trading date YYYY-MM-DD; run once and exit')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    settings = load_settings()
    repository = ResearchRepository(make_engine())
    if args.date:
        count = repository.analyze_date(args.date)
        log.info('Analyzed %s research observations for %s', count, args.date)
        return
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    last_run = None
    while not stop.is_set():
        local = datetime.now(timezone.utc).astimezone(settings.nightly_timezone)
        due = local.timetz().replace(tzinfo=None) >= settings.nightly_time
        if due and last_run != local.date():
            try:
                count = repository.analyze_date(local.date())
                log.info('Nightly outcomes: %s observations for %s', count, local.date())
                if os.getenv('BASELINE_NIGHTLY_ENABLED', 'true').lower() == 'true':
                    from .baseline import make_baseline
                    report = make_baseline().catch_up(settings.baseline_catchup_days)
                    if report:
                        log.info('Nightly baseline: run=%s status=%s days=%s/%s',
                            report['id'], report['status'],
                            report['coverage']['trading_days_completed'],
                            report['coverage']['trading_days'])
                last_run = local.date()
            except Exception:
                log.warning('Nightly research failed; retrying without changing scanner state')
        stop.wait(60)


if __name__ == '__main__':
    main()
