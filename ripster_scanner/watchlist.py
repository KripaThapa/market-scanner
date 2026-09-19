"""Normalize and validate screenshot candidates before any candle requests."""

from dataclasses import dataclass
import re

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
class WatchlistImport:
    candidates: tuple[str, ...]
    validated: tuple[str, ...]
    rejected: tuple[RejectedCandidate, ...]


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
