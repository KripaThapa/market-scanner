"""Trend classification used for the 10-minute market context."""

import pandas as pd
from .candle_model import frame_of


def analyze_trend(df: pd.DataFrame) -> dict:

    latest = frame_of(df).iloc[-1]

    close = latest["close"]

    ema_5 = latest["ema_5"]
    ema_12 = latest["ema_12"]
    ema_34 = latest["ema_34"]
    ema_50 = latest["ema_50"]

    vwap = latest["vwap"]

    bullish_fast = ema_5 > ema_12
    bearish_fast = ema_5 < ema_12

    bullish_slow = ema_34 > ema_50
    bearish_slow = ema_34 < ema_50

    above_vwap = close > vwap
    below_vwap = close < vwap

    above_clouds = (
        close > ema_5
        and close > ema_12
        and close > ema_34
        and close > ema_50
    )

    below_clouds = (
        close < ema_5
        and close < ema_12
        and close < ema_34
        and close < ema_50
    )

    if (
        bullish_fast
        and bullish_slow
        and above_vwap
        and above_clouds
    ):
        trend = "BULLISH"

    elif (
        bearish_fast
        and bearish_slow
        and below_vwap
        and below_clouds
    ):
        trend = "BEARISH"

    else:
        trend = "MIXED"

    return {
        "trend": trend,
        "close": close,
        "ema_5": ema_5,
        "ema_12": ema_12,
        "ema_34": ema_34,
        "ema_50": ema_50,
        "vwap": vwap,
        "fast_cloud": (
            "BULLISH"
            if bullish_fast
            else "BEARISH"
        ),
        "slow_cloud": (
            "BULLISH"
            if bullish_slow
            else "BEARISH"
        ),
        "vwap_position": (
            "ABOVE"
            if above_vwap
            else "BELOW"
        )
    }
