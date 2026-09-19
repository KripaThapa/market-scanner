"""3-minute context only; entry rules remain undefined."""

import pandas as pd

from .market_context import analyze_trend


def analyze_entry_context(df: pd.DataFrame) -> dict:
    """Preserve the prototype's trend summary without generating entries."""
    return analyze_trend(df)
