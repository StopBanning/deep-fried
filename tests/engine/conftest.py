import numpy as np
import pandas as pd
import pytest

from downside.data import Bars


def gbm_bars(seed: int, n: int = 1000, sigma_daily: float = 0.02, start: float = 100.0,
             end: str = "2026-11-06") -> pd.DataFrame:
    """Daily OHLC from a driftless GBM sampled 40 times a day, so high/low behave like real ranges."""
    rng = np.random.default_rng(seed)
    steps = 40
    z = rng.standard_normal((n, steps)) * sigma_daily / np.sqrt(steps)
    path = start * np.exp(np.cumsum(z.ravel() - 0.5 * (sigma_daily ** 2) / steps)).reshape(n, steps)
    opens = np.concatenate([[start], path[:-1, -1]])
    df = pd.DataFrame({
        "open": opens,
        "high": np.maximum(path.max(axis=1), opens),
        "low": np.minimum(path.min(axis=1), opens),
        "close": path[:, -1],
        "volume": 1e6,
    }, index=pd.bdate_range(end=end, periods=n, name="date"))
    return df


@pytest.fixture
def bars():
    frames = {
        "NVDA": gbm_bars(1, start=180, sigma_daily=0.03),
        "QQQ": gbm_bars(2, start=650, sigma_daily=0.012),
        "GOOGL": gbm_bars(3, start=280, sigma_daily=0.018),
        "SPY": gbm_bars(5, start=730, sigma_daily=0.01),
    }
    # Leveraged funds built from their underlyings, so prices agree with the model.
    for fund, und, lev in (("TQQQ", "QQQ", 3), ("GGLL", "GOOGL", 2)):
        u = frames[und]
        r = u.close.pct_change().fillna(0.0)
        close = 50 * np.cumprod(1 + lev * r)
        frames[fund] = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                                     "close": close, "volume": 1e6}, index=u.index)
    return Bars(frames, "test")


@pytest.fixture
def raw_portfolio():
    return {
        "name": "Test",
        "cash": 100,
        "positions": [
            {"symbol": "NVDA", "shares": 5, "avg_cost": 200, "levels": {"buy_at": 170}},
            {"symbol": "TQQQ", "shares": 10, "avg_cost": 60, "levels": {"exit_below": 600}},
            {"symbol": "GGLL", "shares": 8, "avg_cost": 70},
        ],
        "watch": ["SPY"],
    }
