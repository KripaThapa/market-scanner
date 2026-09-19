"""One-shot watchlist scanner orchestration and command-line input selection."""

import argparse
from dataclasses import replace

from alpaca.data.historical import StockHistoricalDataClient

from .config import asset_directory_uses_paper, load_config
from .display import print_watchlist_import, print_watchlist_summary
from .market_data import fetch_active_symbols
from .provider import build_provider
from .scan import scan_watchlist
from .watchlist import validate_candidates
from .watchlist_image import extract_image_tokens


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan Ripster watchlist market context")
    parser.add_argument("--watchlist-image", metavar="PATH",
                        help="OCR a screenshot instead of loading config/watchlist.json")
    args = parser.parse_args(argv)
    try:
        if args.watchlist_image is not None:
            tokens = extract_image_tokens(args.watchlist_image)
            # Explicit empty symbols bypass the JSON file; only validated OCR is used.
            config = load_config(symbols=())
            symbols = fetch_active_symbols(config.api_key, config.secret_key,
                                           paper=asset_directory_uses_paper())
            imported = validate_candidates(tokens, symbols)
            print_watchlist_import(imported)
            if not imported.validated:
                parser.error("No validated symbols in screenshot; scan not started.")
            config = replace(config, symbols=imported.validated)
        else:
            config = load_config()
    except ValueError as exc:
        parser.error(str(exc))

    provider = build_provider(config, client=StockHistoricalDataClient(
        config.api_key, config.secret_key))
    print_watchlist_summary(scan_watchlist(config, provider))
