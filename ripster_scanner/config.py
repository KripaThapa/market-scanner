"""Scanner defaults, watchlist validation, and local credential loading."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

LOOKBACK_DAYS = 3
DEFAULT_WATCHLIST_PATH = Path("config/watchlist.json")


@dataclass(frozen=True)
class FormingThresholds:
    """EXPERIMENTAL V1 thresholds; fractions of price, not official setup rules."""
    lookback_bars: int = 6
    min_retrace_pct: float = 0.003
    cloud_proximity_pct: float = 0.004
    slow_cloud_tolerance_pct: float = 0.002


def forming_thresholds() -> FormingThresholds:
    values = FormingThresholds(
        lookback_bars=int(os.getenv('FORMING_LOOKBACK_BARS', '6')),
        min_retrace_pct=float(os.getenv('FORMING_MIN_RETRACE_PCT', '0.003')),
        cloud_proximity_pct=float(os.getenv('FORMING_CLOUD_PROXIMITY_PCT', '0.004')),
        slow_cloud_tolerance_pct=float(os.getenv('FORMING_SLOW_TOLERANCE_PCT', '0.002')),
    )
    if values.lookback_bars < 2 or any(not (0 <= value < 1) for value in (
        values.min_retrace_pct, values.cloud_proximity_pct, values.slow_cloud_tolerance_pct
    )):
        raise ValueError('Invalid experimental forming thresholds')
    return values


def load_watchlist(path: str | Path = DEFAULT_WATCHLIST_PATH) -> tuple[str, ...]:
    """Read a nonempty JSON list; normalize case and deduplicate in file order."""
    path = Path(path)
    try:
        symbols = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load watchlist {path}: {exc}") from exc
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("Watchlist must be a nonempty JSON list of ticker symbols")
    if any(not isinstance(symbol, str) or not symbol.strip()
           or any(char.isspace() for char in symbol.strip()) for symbol in symbols):
        raise ValueError("Each watchlist symbol must be a nonempty string without internal whitespace")
    return tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols))


@dataclass(frozen=True)
class Config:
    api_key: str
    secret_key: str
    symbols: tuple[str, ...]
    lookback_days: int = LOOKBACK_DAYS
    forming: FormingThresholds = FormingThresholds()
    market_data_provider: str = 'alpaca_iex'


def load_config(
    watchlist_path: str | Path = DEFAULT_WATCHLIST_PATH,
    *, symbols: tuple[str, ...] | None = None,
) -> Config:
    if symbols is None:
        symbols = load_watchlist(watchlist_path)
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env")
    provider = os.getenv('MARKET_DATA_PROVIDER', 'alpaca_iex').strip().lower()
    if provider != 'alpaca_iex':
        raise ValueError('MARKET_DATA_PROVIDER currently supports only alpaca_iex')
    return Config(api_key=api_key, secret_key=secret_key, symbols=symbols,
                  forming=forming_thresholds(), market_data_provider=provider)


def asset_directory_uses_paper() -> bool:
    """Select the read-only asset endpoint matching the credential environment."""
    value = os.getenv("ALPACA_PAPER", "true").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError("ALPACA_PAPER must be true or false")
    return value == "true"
