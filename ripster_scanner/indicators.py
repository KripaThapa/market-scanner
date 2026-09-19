"""EMA clouds and per-session VWAP calculations."""

import pandas as pd
from .candle_model import frame_of, same_source


def add_emas(df: pd.DataFrame) -> pd.DataFrame:

    original = df
    df = frame_of(df).copy()

    df["ema_5"] = (
        df["close"]
        .ewm(span=5, adjust=False)
        .mean()
    )

    df["ema_12"] = (
        df["close"]
        .ewm(span=12, adjust=False)
        .mean()
    )

    df["ema_34"] = (
        df["close"]
        .ewm(span=34, adjust=False)
        .mean()
    )

    df["ema_50"] = (
        df["close"]
        .ewm(span=50, adjust=False)
        .mean()
    )

    return same_source(original, df)


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate session VWAP.

    VWAP resets every trading day.
    """

    original = df
    df = frame_of(df).copy()

    typical_price = (
        df["high"] +
        df["low"] +
        df["close"]
    ) / 3

    df["price_volume"] = typical_price * df["volume"]

    # Each market session gets its own VWAP calculation
    session = df.index.date

    cumulative_pv = (
        df["price_volume"]
        .groupby(session)
        .cumsum()
    )

    cumulative_volume = (
        df["volume"]
        .groupby(session)
        .cumsum()
    )

    df["vwap"] = cumulative_pv / cumulative_volume

    df.drop(
        columns=["price_volume"],
        inplace=True
    )

    return same_source(original, df)
