"""Next-week (5-session) variance forecasts, each rescaled by its own recent track record.

Two raw forecasts:

- **HAR-PK** (every ticker): regresses the next 5 sessions' realized variance (sum of squared daily log
  returns) on today's, this week's and this month's Parkinson range variance, over the trailing 500
  sessions.
- **Implied** (SPY and QQQ): the Cboe VIX / VXN close, as 5-session variance. In a pre-registered test
  (2024-2026) implied volatility beat HAR-PK, GARCH and EWMA on these two ETFs in both windows, while
  HAR-PK won across single stocks.

Raw forecasts run biased, so each gets a scale factor k: the mean ratio of realized to forecast variance
over the 52 most recent weekly origins whose outcome was known at the time. `track_record` replays that
rule week by week with no look-ahead, which is what the report's scorecard shows.

Short histories fall back to a 5-session EWMA (lambda 0.94) with no rescaling, and say so.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

HORIZON = 5
WINDOW = 500
K_WEEKS = 52
K_MIN = 26          # weeks of history needed before a k is trusted
LAMBDA = 0.94
TRADING_DAYS = 252
Z80, Z95 = stats.norm.ppf(0.9), stats.norm.ppf(0.975)


@dataclass
class Forecast:
    var5: float          # calibrated 5-session log-return variance
    method: str          # "HAR-PK", "Implied (VIX)", or "EWMA (short history)"
    k: float | None      # scale factor applied to the raw forecast
    weeks: int           # weeks behind k

    @property
    def sd5(self) -> float:
        return float(np.sqrt(self.var5))


@dataclass
class Record:
    """How a ticker's ranges did over recent weeks, each forecast made with only the data of its day."""
    weeks: int
    in80: float          # share of weekly moves inside the 80% range
    in95: float
    last_miss: str | None  # date of the most recent week that broke the 95% range


def ewma_5day(lr: np.ndarray) -> float:
    lr = lr[np.isfinite(lr)]
    s2 = np.var(lr[:60], ddof=1)
    for r in lr[60:]:
        s2 = LAMBDA * s2 + (1 - LAMBDA) * r * r
    return HORIZON * s2


def parkinson(df: pd.DataFrame) -> np.ndarray:
    return np.log(df.high.values / df.low.values) ** 2 / (4 * np.log(2))


def har_raw(df: pd.DataFrame) -> float:
    """Raw HAR-PK forecast at the last row of df (nothing after it is visible)."""
    lr = np.diff(np.log(df.close.values), prepend=np.nan)
    pk = pd.Series(parkinson(df))
    X = np.column_stack([np.ones(len(pk)), pk, pk.rolling(5).mean(), pk.rolling(22).mean()])
    y5 = pd.Series(lr ** 2).rolling(HORIZON).sum().shift(-HORIZON).values
    rows = slice(len(pk) - WINDOW, len(pk) - HORIZON)
    beta, *_ = np.linalg.lstsq(X[rows], y5[rows], rcond=None)
    f = float(X[-1] @ beta)
    return f if f > 0 else ewma_5day(lr)


def weekly_origins(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each ISO week."""
    iso = dates.isocalendar()
    last = pd.Series(dates, index=dates).groupby([iso.year.values, iso.week.values]).max()
    return pd.DatetimeIndex(sorted(last.values))


class _Model:
    """Raw forecasts at weekly origins plus the last row, and the rolling-k rule on top of them."""

    def __init__(self, df: pd.DataFrame, implied: pd.Series | None):
        self.df = df
        self.close = df.close.values
        self.lr = np.diff(np.log(self.close), prepend=np.nan)
        self.last = len(df) - 1
        pos = pd.Series(np.arange(len(df)), index=df.index)
        if implied is not None:
            iv = implied.reindex(df.index, method="ffill")
            self.iv = iv.values
            first = int(np.argmax(np.isfinite(self.iv))) if np.isfinite(self.iv).any() else len(df)
            start = max(first, 60)
        else:
            self.iv = None
            start = WINDOW + 22
        self.origins = [int(pos[o]) for o in weekly_origins(df.index) if pos[o] >= start and pos[o] < self.last]
        self._raw: dict[int, float] = {}

    def raw(self, i: int) -> float:
        if i not in self._raw:
            if self.iv is not None:
                self._raw[i] = float((self.iv[i] / 100) ** 2 * HORIZON / TRADING_DAYS)
            else:
                self._raw[i] = har_raw(self.df.iloc[:i + 1])
        return self._raw[i]

    def realized(self, o: int) -> float:
        return float(np.sum(self.lr[o + 1:o + 1 + HORIZON] ** 2))

    def k_at(self, i: int) -> tuple[float | None, int]:
        """k from up to 52 origins whose 5-session outcome was complete by row i."""
        known = [o for o in self.origins if o + HORIZON <= i][-K_WEEKS:]
        if len(known) < K_MIN:
            return None, len(known)
        return float(np.mean([self.realized(o) / self.raw(o) for o in known])), len(known)


def _model(df: pd.DataFrame, implied: pd.Series | None) -> _Model | None:
    if implied is not None:
        m = _Model(df, implied)
        if m.iv is not None and np.isfinite(m.iv[-1]) and len(m.origins) >= K_MIN:
            return m
    if len(df) >= WINDOW + 22 + HORIZON * (K_MIN + 2):
        return _Model(df, None)
    return None


def forecast(df: pd.DataFrame, implied: pd.Series | None = None, implied_name: str = "VIX") -> Forecast:
    m = _model(df, implied)
    if m is None:
        lr = np.diff(np.log(df.close.values), prepend=np.nan)
        return Forecast(ewma_5day(lr), "EWMA (short history)", None, 0)
    k, weeks = m.k_at(m.last)
    method = f"Implied ({implied_name})" if m.iv is not None else "HAR-PK"
    return Forecast(m.raw(m.last) * k, method, k, weeks)


def track_record(df: pd.DataFrame, implied: pd.Series | None = None, weeks: int = 26) -> Record | None:
    """Replay the last `weeks` weekly forecasts, each with only the data it had, against what happened."""
    m = _model(df, implied)
    if m is None:
        return None
    done = [o for o in m.origins if o + HORIZON <= m.last]
    rows = []
    for o in done[-weeks:]:
        k, _ = m.k_at(o)
        if k is None:
            continue
        sd = np.sqrt(m.raw(o) * k)
        move = abs(np.log(m.close[o + HORIZON] / m.close[o]))
        rows.append((o, move <= Z80 * sd, move <= Z95 * sd))
    if not rows:
        return None
    misses = [o for o, _, ok95 in rows if not ok95]
    return Record(len(rows), float(np.mean([r[1] for r in rows])), float(np.mean([r[2] for r in rows])),
                  str(df.index[misses[-1]].date()) if misses else None)


def correlation(frames: dict[str, pd.DataFrame], tickers: list[str], sessions: int = 250) -> pd.DataFrame:
    """Correlation of daily log returns over the last `sessions` shared sessions."""
    closes = pd.concat({t: frames[t].close for t in tickers}, axis=1).dropna()
    lr = np.log(closes).diff().dropna().iloc[-sessions:]
    return lr.corr()
