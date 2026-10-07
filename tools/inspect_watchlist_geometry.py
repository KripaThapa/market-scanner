"""Development-only OCR geometry report. No database, provider or web API access.

Run from the repository root; stdout contains only the explicitly supplied
watchlist image's OCR and extracted cells. Keep reports private/local.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ripster_scanner.watchlist import extract_watchlist_rows
from ripster_scanner.watchlist_image import extract_image_tokens, tokens_from_tsv
from ripster_scanner.watchlist_table import column_boundaries, header_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--tsv', type=Path, help='Inspect saved TSV instead of rerunning OCR')
    args = parser.parse_args()
    tokens = (tokens_from_tsv(args.tsv.read_text()) if args.tsv else
              extract_image_tokens(args.image))
    rows = extract_watchlist_rows(tokens, image_path=args.image)
    first = min((t.top for row in rows for t in row.tokens if t.text == row.symbol), default=0)
    print(json.dumps({
        'columns': column_boundaries(tokens, first, args.image),
        'header_tokens': [asdict(t) for t in tokens if t.top < first],
        'recognized_header_words': [t.text for t in tokens if t.top < first and
            header_name(t.text) in {'news', 'support', 'resistance', 'pivot', 'game', 'plan', 'mtf'}],
        'tokens': [asdict(t) for t in tokens],
        'rows': [row.as_dict() for row in rows],
    }, indent=2))


if __name__ == '__main__':
    main()
