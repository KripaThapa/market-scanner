"""Aggregate market-time one-minute OHLCV bars."""

import pandas as pd
from .candle_model import frame_of, same_source


def resample_candles(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    candles = frame_of(df).resample(
        timeframe,
        origin="start_day",
        offset="30min"
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "trade_count": "sum"
    })

    candles = candles.dropna(
        subset=["open", "high", "low", "close"]
    )

    return same_source(df, candles, timeframe)
