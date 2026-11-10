"""Daily-reset leveraged funds: what they are, and how they move when the underlying moves.

A fund that resets to L times leverage every day returns L x the underlying each day, not over a week or a
year. Under a lognormal path its value after a move R in the underlying is

    (1 + R) ** L  *  exp(-0.5 * L * (L - 1) * v)

where v is the underlying's log-return variance along the path. A smooth move has v near 0; a choppy
one has more, and the fund loses more. Fees and financing costs are ignored, so real funds do a little
worse than this.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# symbol: (underlying, daily leverage). Check a fund's prospectus before relying on an entry.
# Index funds use the closest liquid ETF as the underlying (QQQ for the Nasdaq-100, SOXX for the
# NYSE Semiconductor Index, SPY for the S&P 500).
REGISTRY: dict[str, tuple[str, float]] = {
    "TQQQ": ("QQQ", 3), "QLD": ("QQQ", 2), "SQQQ": ("QQQ", -3), "QID": ("QQQ", -2),
    "UPRO": ("SPY", 3), "SPXL": ("SPY", 3), "SSO": ("SPY", 2), "SPXU": ("SPY", -3), "SDS": ("SPY", -2),
    "SOXL": ("SOXX", 3), "SOXS": ("SOXX", -3),
    "NVDL": ("NVDA", 2), "NVDU": ("NVDA", 2),
    "GGLL": ("GOOGL", 2), "AVL": ("AVGO", 2), "TSMX": ("TSM", 2),
    "TSLL": ("TSLA", 2), "AAPU": ("AAPL", 2), "MSFU": ("MSFT", 2), "AMZU": ("AMZN", 2),
    "METU": ("META", 2), "CONL": ("COIN", 2), "MSTU": ("MSTR", 2),
}


def resolve(symbol: str, underlying: str | None = None, leverage: float | None = None) -> tuple[str, float]:
    """(underlying, leverage) for a holding: explicit values win, then the registry, then itself at 1x."""
    if underlying or leverage:
        return (underlying or symbol).upper(), float(leverage or 1)
    return REGISTRY.get(symbol.upper(), (symbol.upper(), 1.0))


def multiplier(R: float, L: float, v: float = 0.0) -> float:
    """Fund value multiple after an underlying move R with path variance v."""
    if 1 + R <= 0:
        return 0.0 if L > 0 else float("inf")
    return float((1 + R) ** L * np.exp(-0.5 * L * (L - 1) * v))


def underlying_move_for(m: float, L: float, v: float = 0.0) -> float:
    """The underlying move R that takes the fund to multiple m (inverse of multiplier)."""
    return float((m * np.exp(0.5 * L * (L - 1) * v)) ** (1 / L) - 1)


def synthetic(close: pd.Series, L: float) -> pd.Series:
    """A daily-reset L x fund built from the underlying's closes (starts at 1, no fees, floored at 0)."""
    r = close.pct_change().fillna(0.0).values
    return pd.Series(np.cumprod(np.maximum(1 + L * r, 0.0)), index=close.index)


def max_drawdown(series: pd.Series) -> tuple[float, pd.Timestamp, pd.Timestamp]:
    """(worst peak-to-trough fall as a negative fraction, peak date, trough date)."""
    peak = series.cummax()
    dd = series / peak - 1
    trough = dd.idxmin()
    return float(dd.min()), series.loc[:trough].idxmax(), trough
