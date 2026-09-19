"""Experimental 3-minute pullback detector; never emits entry signals."""

from dataclasses import dataclass
from enum import StrEnum
import math

import pandas as pd
from .candle_model import frame_of

from .config import FormingThresholds


class SetupState(StrEnum):
    NONE = 'NONE'
    FORMING_LONG = 'FORMING_LONG'
    FORMING_SHORT = 'FORMING_SHORT'


@dataclass(frozen=True)
class FormingResult:
    state: SetupState = SetupState.NONE
    reason: str | None = None
    cloud_distance_pct: float | None = None


def detect_forming(context_10m: str, three: pd.DataFrame,
                   thresholds: FormingThresholds = FormingThresholds()) -> FormingResult:
    """Compare latest 3m close to a previous move, fast cloud and slow cloud."""
    three = frame_of(three)
    if context_10m not in {'BULLISH', 'BEARISH'} or len(three) < thresholds.lookback_bars + 1:
        return FormingResult()
    window = three.iloc[-(thresholds.lookback_bars + 1):]
    latest, previous = window.iloc[-1], window.iloc[:-1]
    fields = ('close', 'ema_5', 'ema_12', 'ema_34', 'ema_50')
    if any(not math.isfinite(float(latest[key])) for key in fields) or not math.isfinite(float(previous['high'].max())) or not math.isfinite(float(previous['low'].min())):
        return FormingResult()
    price = float(latest['close'])
    if price <= 0:
        return FormingResult()
    fast_low = min(float(latest['ema_5']), float(latest['ema_12']))
    fast_high = max(float(latest['ema_5']), float(latest['ema_12']))
    distance = max(fast_low - price, 0, price - fast_high) / price
    if distance > thresholds.cloud_proximity_pct:
        return FormingResult()
    slow_34, slow_50 = float(latest['ema_34']), float(latest['ema_50'])
    tolerance = thresholds.slow_cloud_tolerance_pct
    if context_10m == 'BULLISH':
        peak = float(previous['high'].max())
        retrace = (peak - price) / peak if peak > 0 else 0
        if (retrace >= thresholds.min_retrace_pct and slow_34 > slow_50
                and price >= min(slow_34, slow_50) * (1 - tolerance)):
            return FormingResult(SetupState.FORMING_LONG,
                '10m bullish; 3m pullback toward 5/12 while 34/50 remains intact.', distance)
    else:
        trough = float(previous['low'].min())
        retrace = (price - trough) / trough if trough > 0 else 0
        if (retrace >= thresholds.min_retrace_pct and slow_34 < slow_50
                and price <= max(slow_34, slow_50) * (1 + tolerance)):
            return FormingResult(SetupState.FORMING_SHORT,
                '10m bearish; 3m bounce toward 5/12 while 34/50 remains intact.', distance)
    return FormingResult()
