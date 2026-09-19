"""Normalized discovery values, independent of screener SDK models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from typing import Protocol


class SourceType(StrEnum):
    UPLOADED_WATCHLIST = 'UPLOADED_WATCHLIST'
    MOST_ACTIVE = 'MOST_ACTIVE'
    TOP_GAINER = 'TOP_GAINER'
    TOP_LOSER = 'TOP_LOSER'


AUTOMATIC_SOURCES = (SourceType.MOST_ACTIVE, SourceType.TOP_GAINER, SourceType.TOP_LOSER)
SYMBOL_PATTERN = re.compile(r'^[A-Z][A-Z0-9.-]{0,19}$')


def normalize_symbol(value):
    if not isinstance(value, str):
        return None
    symbol = value.strip().upper()
    return symbol if SYMBOL_PATTERN.fullmatch(symbol) else None


@dataclass(frozen=True)
class DiscoveryItem:
    symbol: str
    source_type: SourceType
    provider: str
    discovered_at: datetime
    rank: int | None = None
    metrics: dict = field(default_factory=dict)


class DiscoveryProvider(Protocol):
    name: str

    def fetch(self, source_type: SourceType, at: datetime) -> list[DiscoveryItem]: ...


def merge_sources(items):
    """One symbol in the scan universe, all source memberships retained."""
    merged = {}
    for item in items:
        symbol = normalize_symbol(item.symbol)
        if symbol:
            merged.setdefault(symbol, {})[item.source_type.value] = item
    return merged
