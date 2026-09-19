"""Fetch Alpaca IEX minute bars, retaining provider-supplied extended hours."""

from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


def fetch_one_minute_bars(symbol: str, client: StockHistoricalDataClient, lookback_days: int) -> pd.DataFrame:

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=lookback_days)

    request = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Minute,
        start=start_time,
        end=end_time,
        feed=DataFeed.IEX
    )

    bars = client.get_stock_bars(request)

    df = bars.df.reset_index()

    if df.empty:
        return df

    df = df[df["symbol"] == symbol].copy()

    if df.empty:
        return df

    # Convert UTC timestamps to New York market time
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"])
        .dt.tz_convert("America/New_York")
    )

    df = df.set_index("timestamp")

    return df


def fetch_active_symbols(api_key: str, secret_key: str, *, paper: bool = True) -> set[str]:
    """Read only the asset directory; never instantiate an order/trading client."""
    import json
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    host = "paper-api.alpaca.markets" if paper else "api.alpaca.markets"
    request = Request(
        f"https://{host}/v2/assets?status=active&asset_class=us_equity",
        headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            assets = json.load(response)
        if not isinstance(assets, list) or any(
            not isinstance(asset, dict) or not isinstance(asset.get("symbol"), str)
            or "status" not in asset or "class" not in asset for asset in assets
        ):
            raise ValueError("Invalid asset directory response")
        symbols = {asset["symbol"] for asset in assets
                   if asset["status"] == "active" and asset["class"] == "us_equity"}
        if not symbols:
            raise ValueError("Empty asset directory")
        return symbols
    except (URLError, OSError, ValueError) as exc:
        raise ValueError(
            "Cannot validate screenshot symbols with Alpaca's asset directory. "
            "Check network access, credentials, and ALPACA_PAPER (true or false). "
            "No screenshot symbols will be scanned."
        ) from exc
