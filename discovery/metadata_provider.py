"""Provider-neutral company reference metadata, never candle/price data."""

from dataclasses import dataclass
from typing import Protocol


def usable(value, limit=120):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (not value or len(value) > limit or not value.isprintable()
            or value.upper() in {'UNKNOWN', 'UNCLASSIFIED', 'N/A', 'NONE', 'NULL', '-'}):
        return None
    return value


@dataclass(frozen=True)
class CompanyMetadata:
    symbol: str
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    cik: str | None = None
    isin: str | None = None
    cusip: str | None = None
    exchange: str | None = None
    country: str | None = None


@dataclass(frozen=True)
class MetadataResult:
    status: str
    metadata: CompanyMetadata | None = None


class SymbolMetadataProvider(Protocol):
    name: str

    def fetch(self, symbol: str) -> MetadataResult: ...
