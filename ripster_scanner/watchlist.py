"""Normalize and validate screenshot candidates before any candle requests."""

from dataclasses import dataclass
import re
from statistics import median

from .watchlist_image import OCRToken

MIN_OCR_CONFIDENCE = 80.0
# Ambiguous annotation words are excluded even when they also name real assets.
OCR_NOISE = frozenset("""
RIPSTER WATCHLIST DAILY SYMBOL SYMBOLS TICKER TICKERS DATE TODAY
LONG SHORT LONGS SHORTS BULLISH BEARISH MIXED BUY SELL ENTRY EXIT
EMA VWAP PRICE LEVEL LEVELS KEY SUPPORT RESISTANCE BREAKOUT PULLBACK
CURL NEWS OPTIONS FLOW ALERT ALERTS SETUP SETUPS NOTES CONTEXT TREND
ABOVE BELOW FIRST HIGH LOW OPEN CLOSE VOLUME TARGET STOP TBD
THE AND OR FOR TO OF IN ON AT IS IT AS IF A AN ALL WITH FROM
""".split())


@dataclass(frozen=True)
class RejectedCandidate:
    candidate: str
    reason: str


@dataclass(frozen=True)
class ExtractedWatchlistRow:
    """A symbol and the verbatim OCR text from its visual table row."""
    symbol: str
    original_note: str
    confidence: float
    source_bbox: tuple[int, int, int, int]
    tokens: tuple[OCRToken, ...] = ()

    def as_dict(self):
        left, top, right, bottom = self.source_bbox
        return {'symbol': self.symbol, 'original_note': self.original_note,
                'confidence': self.confidence,
                'source_bbox': {'left': left, 'top': top, 'right': right, 'bottom': bottom}}


@dataclass(frozen=True)
class WatchlistImport:
    candidates: tuple[str, ...]
    validated: tuple[str, ...]
    rejected: tuple[RejectedCandidate, ...]
    rows: tuple[ExtractedWatchlistRow, ...] = ()


def normalize_ticker(value: str) -> str:
    """Uppercase and remove surrounding noise, retaining meaningful class separators.

    Never delete embedded digits or join separated words: that could create a
    different valid symbol. Malformed interiors are rejected by validation.
    """
    return re.sub(r"^[^A-Z0-9]+|[^A-Z0-9]+$", "", value.strip().upper())


def validate_candidates(tokens: list[OCRToken], active_symbols: set[str]) -> WatchlistImport:
    # Prefer the highest-confidence reading of an identical normalized symbol.
    unique: dict[str, OCRToken] = {}
    for token in tokens:
        candidate = normalize_ticker(token.text) or token.text.strip()
        if not candidate:
            continue
        if candidate not in unique or token.confidence > unique[candidate].confidence:
            unique[candidate] = token

    candidates, validated, rejected = [], [], []
    for candidate, token in unique.items():
        reason = None
        if candidate in OCR_NOISE:
            reason = "annotation/common OCR text (ambiguous as a ticker)"
        elif not re.fullmatch(r"[A-Z]{1,6}(?:[.-][A-Z])?", candidate):
            reason = "not a supported ticker token; no OCR correction attempted"
        else:
            candidates.append(candidate)
            if not MIN_OCR_CONFIDENCE <= token.confidence <= 100:
                reason = "low or invalid OCR confidence"
            elif candidate not in active_symbols:
                reason = "not found in Alpaca active US-equity assets"
        if reason:
            rejected.append(RejectedCandidate(candidate, reason))
        else:
            validated.append(candidate)
    return WatchlistImport(tuple(candidates), tuple(validated), tuple(rejected))


def extract_watchlist_rows(tokens: list[OCRToken]) -> tuple[ExtractedWatchlistRow, ...]:
    """Select symbols from the repeated left-hand table column.

    The supplied watchlist is a table, not a prose document: symbols repeat at
    one visual x anchor while headlines and notes begin much farther right.
    Geometry is therefore evidence of membership; asset-directory membership
    is applied later as validity checking.
    """
    geometric = [token for token in tokens if token.width > 0 and token.height > 0]
    if not geometric:
        return ()
    heights = [token.height for token in geometric]
    typical_height = max(1.0, median(heights))
    image_width = max(token.right for token in geometric)
    possible = []
    for token in geometric:
        candidate = normalize_ticker(token.text)
        if not re.fullmatch(r"[A-Z]{1,6}(?:[.-][A-Z])?", candidate or ""):
            continue
        # The table's symbol column is a narrow, repeated left-side column.
        # A very wide logo/header token is never a row candidate.
        if token.width > typical_height * 8 or token.center_x > image_width * 0.18:
            continue
        possible.append(token)
    if not possible:
        return ()

    # Find the dominant repeated x anchor. This avoids promoting words in the
    # headline bands which happen to be valid Alpaca symbols.
    bin_width = max(typical_height * 3, image_width * 0.01)
    bins = {}
    for token in possible:
        bucket = round(token.center_x / bin_width)
        bins.setdefault(bucket, []).append(token)
    dominant = max(bins.values(), key=len)
    anchor_x = median([token.center_x for token in dominant])
    tolerance = max(bin_width * 0.65, typical_height * 2)
    anchors = [token for token in possible if abs(token.center_x - anchor_x) <= tolerance]
    if len(anchors) < 2:
        return ()

    anchors.sort(key=lambda token: token.center_y)
    row_gap = typical_height * 2.5
    groups: list[list[OCRToken]] = []
    for token in anchors:
        if not groups or token.center_y - groups[-1][-1].center_y > row_gap:
            groups.append([token])
        else:
            groups[-1].append(token)

    rows = []
    for group in groups:
        top = int(min(token.top for token in group) - typical_height * 1.5)
        bottom = int(max(token.bottom for token in group) + typical_height * 1.5)
        row_tokens = [token for token in geometric if top <= token.center_y <= bottom]
        row_tokens.sort(key=lambda token: (token.top, token.left))
        anchor_ids = {id(token) for token in group}
        notes = [token.text for token in row_tokens
                 if id(token) not in anchor_ids and token.left >= min(item.left for item in group)]
        note = " ".join(notes).strip()
        left = min(token.left for token in row_tokens)
        right = max(token.right for token in row_tokens)
        for anchor in group:
            rows.append(ExtractedWatchlistRow(
                normalize_ticker(anchor.text), note, anchor.confidence,
                (left, top, right, bottom), tuple(row_tokens)))
    return tuple(rows)


def validate_watchlist_rows(rows: tuple[ExtractedWatchlistRow, ...], active_symbols: set[str]) -> WatchlistImport:
    """Run the existing candidate checks after spatial row selection."""
    tokens = [OCRToken(row.symbol, row.confidence) for row in rows]
    imported = validate_candidates(tokens, active_symbols)
    by_symbol = {}
    for row in rows:
        if row.symbol not in by_symbol or row.confidence > by_symbol[row.symbol].confidence:
            by_symbol[row.symbol] = row
    validated_rows = tuple(by_symbol[symbol] for symbol in imported.validated if symbol in by_symbol)
    return WatchlistImport(imported.candidates, imported.validated, imported.rejected, validated_rows)
