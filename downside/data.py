"""Daily bars from Nasdaq's public historical-quotes endpoint (no API key), with checks and a local cache.

The endpoint is the one behind the free "Download" button on nasdaq.com's historical-quotes pages. It is
unofficial: requests carry an honest user agent and are spaced a second apart. Bars are split-adjusted
regular-session OHLC. A session's bar only counts after 6 pm New York time, so a run during the day uses
the last settled close.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

URL = ("https://api.nasdaq.com/api/quote/{t}/historical?assetclass={a}"
       "&fromdate={d1}&todate={d2}&limit=9999")
AGENT = "deep-fried/0.1 (personal research script)"  # Nasdaq drops agents that carry a URL
PRICES = ["open", "high", "low", "close"]
COLS = PRICES + ["volume"]
NY = ZoneInfo("America/New_York")
SETTLED_HOUR = 18
HISTORY_YEARS = 4
RECENT = 30
STALE_DAYS = 7


CBOE = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{s}_History.csv"
IMPLIED = {"SPY": "VIX", "QQQ": "VXN"}  # tickers whose forecast uses a Cboe implied-volatility index


class DataError(RuntimeError):
    pass


def load_implied(cache: Path, fetch: bool = True) -> tuple[dict[str, pd.Series], list[str]]:
    """{index name: daily close series} for VIX and VXN from Cboe's free history files, plus warnings.

    A failed download is a warning, not an error: those tickers fall back to HAR-PK.
    """
    out, warnings = {}, []
    cache.mkdir(parents=True, exist_ok=True)
    for name in sorted(set(IMPLIED.values())):
        path = cache / f"_{name}.csv"
        try:
            if fetch:
                path.write_bytes(_get(CBOE.format(s=name)))
            df = pd.read_csv(path)
            df["DATE"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y")
            out[name] = df.set_index("DATE")["CLOSE"].astype(float).sort_index()
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as e:
            warnings.append(f"{name} unavailable ({type(e).__name__}); using HAR-PK instead")
    return out, warnings


@dataclass
class Bars:
    """Daily bars for a set of tickers, plus whatever looked wrong in them."""
    frames: dict[str, pd.DataFrame]
    fetched: str
    warnings: list[str] = field(default_factory=list)
    implied: dict[str, pd.Series] = field(default_factory=dict)   # by index name (VIX, VXN)

    def implied_for(self, ticker: str) -> tuple[pd.Series | None, str]:
        name = IMPLIED.get(ticker, "")
        return self.implied.get(name), name

    def close(self, ticker: str) -> float:
        return float(self.frames[ticker].close.iloc[-1])

    def last_date(self) -> date:
        return max(df.index[-1] for df in self.frames.values()).date()


def _number(s) -> float:
    return float(str(s).replace("$", "").replace(",", ""))


def _parse(body: bytes) -> pd.DataFrame | None:
    rows = ((json.loads(body).get("data") or {}).get("tradesTable") or {}).get("rows") or []
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    for c in PRICES:
        df[c] = df[c].map(_number)
    df["volume"] = pd.to_numeric(df["volume"].astype(str).str.replace(",", ""), errors="coerce")
    return df.set_index("date").sort_index()[COLS]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_one(ticker: str, today: date) -> pd.DataFrame:
    start = (today - timedelta(days=365 * HISTORY_YEARS + 30)).isoformat()
    error = None
    for attempt in range(2):
        for asset in ("stocks", "etf"):
            url = URL.format(t=ticker, a=asset, d1=start, d2=today.isoformat())
            try:
                df = _parse(_get(url))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                error = e
                df = None
            if df is not None:
                return df
            time.sleep(1)
        if error is None:
            break  # both answered with no rows: not a timeout, so retrying won't help
        time.sleep(3)
    if error is not None:
        raise DataError(f"{ticker}: download failed: {error}")
    raise DataError(f"{ticker}: Nasdaq returned no bars (is it a US-listed symbol?)")


def check(frames: dict[str, pd.DataFrame], today: date) -> tuple[list[str], list[str]]:
    """(problems that make a ticker unusable, warnings about recent bars that look wrong)."""
    problems, warnings = [], []
    for t, df in frames.items():
        p = df[PRICES]
        if not df.index.is_unique:
            problems.append(f"{t}: duplicate dates")
        if p.isna().any().any() or (p <= 0).any().any():
            problems.append(f"{t}: missing or non-positive prices")
        r = df.iloc[-RECENT:]
        flat = r.index[r.high <= r.low]
        outside = r.index[(r.high < r[["open", "close"]].max(axis=1) * (1 - 1e-6))
                          | (r.low > r[["open", "close"]].min(axis=1) * (1 + 1e-6))]
        for what, days in (("zero-range bar", flat), ("open or close outside high-low", outside)):
            if len(days):
                warnings.append(f"{t}: {what} on {', '.join(str(d.date()) for d in days)}")
        if (today - df.index[-1].date()).days > STALE_DAYS:
            problems.append(f"{t}: latest bar is {df.index[-1].date()}")
    return problems, warnings


def load(tickers: list[str], cache: Path, fetch: bool = True, now: datetime | None = None) -> Bars:
    """Bars for every ticker: fetched fresh (and cached) or read back from the cache."""
    now = now or datetime.now(NY)
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "manifest.json"
    frames: dict[str, pd.DataFrame] = {}
    if fetch:
        for i, t in enumerate(sorted(set(tickers))):
            if i:
                time.sleep(1)
            df = fetch_one(t, now.date())
            if now.hour < SETTLED_HOUR and df.index[-1].date() == now.date():
                df = df.iloc[:-1]  # today's session may still be trading
            df.to_csv(cache / f"{t}.csv", date_format="%Y-%m-%d", float_format="%.10g")
            frames[t] = df
        fetched = now.isoformat(timespec="minutes")
        manifest_path.write_text(json.dumps({"fetched": fetched, "tickers": sorted(frames)}, indent=2))
    else:
        if not manifest_path.exists():
            raise DataError(f"no cached bars in {cache}; run without --no-fetch first")
        fetched = json.loads(manifest_path.read_text())["fetched"]
        for t in sorted(set(tickers)):
            path = cache / f"{t}.csv"
            if not path.exists():
                raise DataError(f"{t}: not in the cache; run without --no-fetch")
            frames[t] = pd.read_csv(path, parse_dates=["date"], index_col="date").astype(float)
    problems, warnings = check(frames, now.date())
    if problems:
        raise DataError("bars rejected:\n  " + "\n  ".join(problems))
    implied, iv_warnings = ({}, []) if not set(IMPLIED) & set(frames) else load_implied(cache, fetch)
    return Bars(frames, fetched, warnings + iv_warnings, implied)
