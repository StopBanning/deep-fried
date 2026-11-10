# -*- coding: utf-8 -*-
"""Downside block for the portfolio risk report, computed by the Deep Fried engine (`downside/` in this repo).

Takes the replayed portfolio snapshot (US positions only), and returns the book's leverage-adjusted
exposure, next week's dollar range, a stress table, exit/buy levels translated into the held fund's
loss from cost, historical drawdowns at the holder's leverage, calibrated weekly ranges, and an
out-of-sample scorecard. Every number comes from code; none from a language model.

Config (all optional):
  DOWNSIDE_ENABLED  "false" turns the block off (default on)
  DOWNSIDE_LEVELS   comma list of UNDERLYING:exit_below:PRICE or UNDERLYING:buy_at:PRICE, e.g.
                    "AVGO:exit_below:290,TSM:exit_below:375,NVDA:buy_at:200"
  DOWNSIDE_WATCH    extra tickers to show ranges for, e.g. "SMH,QQQ"
  DOWNSIDE_CACHE_HOURS  how long fetched daily bars are reused (default 6)

Fail-open: any problem returns {"available": False, "reason": ...} and never breaks the risk report.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(os.getenv("DOWNSIDE_CACHE_DIR", "data/downside_bars"))
_lock = Lock()
_last_fetch: Dict[Tuple[str, ...], float] = {}


def _parse_levels(text: str) -> Dict[str, Dict[str, float]]:
    """{UNDERLYING: {"exit_below": price, "buy_at": price}} from DOWNSIDE_LEVELS."""
    out: Dict[str, Dict[str, float]] = {}
    for item in (text or "").split(","):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) != 3 or parts[1] not in {"exit_below", "buy_at"}:
            continue
        try:
            out.setdefault(parts[0].upper(), {})[parts[1]] = float(parts[2])
        except ValueError:
            continue
    return out


def _round(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), n)


def _aggregate_positions(snapshot: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """US positions summed across accounts (quantity-weighted cost), plus skipped non-US symbols."""
    merged: Dict[str, Dict[str, float]] = {}
    skipped: List[str] = []
    for account in snapshot.get("accounts", []) or []:
        for pos in account.get("positions", []) or []:
            symbol = str(pos.get("symbol") or "").strip().upper()
            qty = float(pos.get("quantity") or 0.0)
            cost = float(pos.get("avg_cost") or 0.0)
            if not symbol or qty <= 0 or cost <= 0:
                continue
            if str(pos.get("market") or "").lower() != "us":
                skipped.append(symbol)
                continue
            row = merged.setdefault(symbol, {"shares": 0.0, "cost_total": 0.0})
            row["shares"] += qty
            row["cost_total"] += qty * cost
    positions = [{"symbol": s, "shares": r["shares"], "avg_cost": r["cost_total"] / r["shares"]}
                 for s, r in sorted(merged.items())]
    return positions, sorted(set(skipped))


def _load_bars(tickers: List[str]):
    from downside import data as D

    hours = float(os.getenv("DOWNSIDE_CACHE_HOURS", "6") or 6)
    key = tuple(sorted(tickers))
    with _lock:
        fresh = time.time() - _last_fetch.get(key, 0.0) < hours * 3600
        if fresh:
            try:
                return D.load(tickers, _CACHE_DIR, fetch=False)
            except D.DataError:
                pass
        bars = D.load(tickers, _CACHE_DIR, fetch=True)
        _last_fetch[key] = time.time()
        return bars


def last_close(symbol: str, as_of) -> Optional[Tuple[float, Any]]:
    """Latest daily close on or before `as_of` for a US ticker, from the engine's Nasdaq bars.

    The portfolio page falls back to this when no live quote and no stored close exist (weekends,
    after hours, or a throttled quote source), so US positions stop showing "missing price".
    Returns (price, date) or None; never raises.
    """
    if os.getenv("DOWNSIDE_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return None
    try:
        from data_provider.us_index_mapping import is_us_stock_code
        from downside import data as D
    except ImportError:
        return None
    sym = str(symbol or "").strip().upper()
    if not sym or not is_us_stock_code(sym):
        return None
    try:
        hours = float(os.getenv("DOWNSIDE_CACHE_HOURS", "6") or 6)
        path = _CACHE_DIR / f"{sym}.csv"
        with _lock:
            fresh = path.exists() and time.time() - path.stat().st_mtime < hours * 3600
            bars = D.load([sym], _CACHE_DIR, fetch=not fresh)
        closes = bars.frames[sym].close
        closes = closes[closes.index.date <= as_of]
        if closes.empty or not float(closes.iloc[-1]) > 0:
            return None
        return float(closes.iloc[-1]), closes.index[-1].date()
    except Exception as exc:  # fail-open
        logger.info("downside close fallback skipped for %s: %s", sym, exc)
        return None


def build_downside(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if os.getenv("DOWNSIDE_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return {"available": False, "reason": "disabled"}
    try:
        from downside import portfolio as P
        from downside import risk as R
    except ImportError:
        return {"available": False, "reason": "Deep Fried engine (downside/) not importable"}

    positions, skipped = _aggregate_positions(snapshot)
    if not positions:
        return {"available": False, "reason": "no US positions", "skipped": skipped}
    if str(snapshot.get("currency") or "USD").upper() != "USD":
        return {"available": False, "reason": "portfolio currency is not USD", "skipped": skipped}

    levels = _parse_levels(os.getenv("DOWNSIDE_LEVELS", ""))
    try:
        pf = P.parse({
            "name": "Portfolio",
            "cash": float(snapshot.get("total_cash") or 0.0),
            "positions": positions,
            "watch": [t.strip().upper() for t in os.getenv("DOWNSIDE_WATCH", "").split(",") if t.strip()],
        })
        for pos in pf.positions:  # levels are keyed by the underlying they sit on
            lv = levels.get(pos.underlying, {})
            pos.exit_below = lv.get("exit_below")
            pos.buy_at = lv.get("buy_at")
        bars = _load_bars(pf.tickers())
        a = R.analyze(pf, bars)
    except Exception as exc:  # fail-open: never break the risk report
        logger.warning("downside block unavailable: %s", exc)
        return {"available": False, "reason": str(exc).splitlines()[0][:200], "skipped": skipped}

    recs = [r for r in a.ranges if r.record]
    n = sum(r.record.weeks for r in recs)
    return {
        "available": True,
        "as_of": a.as_of,
        "book_value": _round(a.book_value, 2),
        "cost_basis": _round(a.cost_basis, 2),
        "pnl": _round(a.pnl, 2),
        "day_change": _round(a.day_change, 2),
        "exposure": _round(a.exposure, 2),
        "leverage_ratio": _round(a.exposure / a.book_value if a.book_value > 0 else None, 4),
        "week_range_80": _round(R.Z80 * a.week_sd, 2),
        "week_range_95": _round(R.Z95 * a.week_sd, 2),
        "holdings": [{
            "symbol": h.pos.symbol, "underlying": h.pos.underlying, "leverage": h.pos.leverage,
            "price": _round(h.price), "value": _round(h.value, 2), "pnl": _round(h.pnl, 2),
            "pnl_pct": _round(h.pnl_pct), "to_cost": _round(h.fund_needed), "underlying_to_cost": _round(h.und_needed),
        } for h in a.holdings],
        "stress": [{"move": s.move, "smooth": _round(s.smooth, 2), "choppy": _round(s.choppy, 2),
                    "book_after": _round(s.book_after, 2)} for s in a.stress],
        "levels": [{
            "symbol": r.pos.symbol, "underlying": r.pos.underlying, "kind": r.kind, "level": r.level,
            "distance": _round(r.distance), "touch": _round(r.touch), "close_beyond": _round(r.close_beyond),
            "holding_at_level": _round(r.fund_at_level), "from_cost": _round(r.loss_from_cost),
            "late": bool(r.kind == "exit_below" and r.loss_from_cost <= -0.25),
        } for r in a.levels],
        "history": [{
            "underlying": r.pos.underlying, "leverage": r.pos.leverage, "since": r.start,
            "worst_fall": _round(r.und_dd), "peak": r.und_dd_dates[0], "trough": r.und_dd_dates[1],
            "at_leverage": _round(r.fund_dd), "worst_week": _round(r.worst_week),
        } for r in a.history],
        "ranges": [{
            "ticker": r.ticker, "last": _round(r.last), "weekly_vol": _round(r.fc.sd5),
            "r80_low": _round(r.r80[0], 2), "r80_high": _round(r.r80[1], 2),
            "r95_low": _round(r.r95[0], 2), "r95_high": _round(r.r95[1], 2), "method": r.fc.method,
            "record": None if not r.record else {"weeks": r.record.weeks, "in80": _round(r.record.in80),
                                                 "in95": _round(r.record.in95), "last_miss": r.record.last_miss},
        } for r in a.ranges],
        "scorecard": None if not n else {
            "weeks": n,
            "in80": _round(sum(r.record.in80 * r.record.weeks for r in recs) / n),
            "in95": _round(sum(r.record.in95 * r.record.weeks for r in recs) / n),
        },
        "warnings": a.warnings,
        "skipped": skipped,
    }


def leverage_prompt_note(code: str, english: bool = True) -> str:
    """A prompt section telling the model a ticker is a daily-reset leveraged ETF (empty for anything else)."""
    try:
        from downside.levered import REGISTRY
    except ImportError:
        return ""
    entry = REGISTRY.get(str(code or "").strip().upper())
    if not entry:
        return ""
    underlying, lev = entry
    lev_txt = f"{abs(lev):g}x {'inverse ' if lev < 0 else ''}"
    if english:
        return (
            "\n## ⚠️ Leveraged ETF\n"
            f"**{code.upper()}** is a daily-reset {lev_txt}fund on **{underlying}**. Each day it moves about "
            f"{lev:g} times {underlying}'s daily move; over weeks, choppy markets erode it even if {underlying} ends flat, "
            f"and drawdowns run about {abs(lev):g} times deeper. Analyse the trend through {underlying}, judge position "
            "risk on the fund's own path, and never describe it as an ordinary stock or a long-term hold without saying so.\n\n---\n"
        )
    return (
        "\n## ⚠️ 杠杆 ETF\n"
        f"**{code.upper()}** 是追踪 **{underlying}** 的每日重置 {lev_txt}基金：单日涨跌约为 {underlying} 的 {lev:g} 倍，"
        "震荡行情中会产生损耗，回撤幅度约为标的的数倍。请以标的趋势为分析基础，并按基金本身的路径评估持仓风险。\n\n---\n"
    )


def stock_risk_lines(code: str, english: bool = True) -> List[str]:
    """Markdown lines with a US ticker's calibrated weekly range, scorecard and worst fall (at its leverage).

    Numbers from code; empty list for non-US tickers, when disabled, or on any data problem.
    """
    if os.getenv("DOWNSIDE_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return []
    try:
        from data_provider.us_index_mapping import is_us_stock_code
        from downside import levered as LV
        from downside import vol as V
        from downside.data import IMPLIED
    except ImportError:
        return []
    symbol = str(code or "").strip().upper()
    if not symbol or not is_us_stock_code(symbol):
        return []
    try:
        underlying, lev = LV.resolve(symbol)
        bars = _load_bars(sorted({symbol, underlying}))
        df = bars.frames[underlying]
        iv, name = bars.implied_for(underlying)
        fc = V.forecast(df, iv, name)
        rec = V.track_record(df, iv)
        last = float(bars.frames[symbol].close.iloc[-1])
        sd = fc.sd5 * (abs(lev) if lev != 1 else 1.0)
        lo80, hi80 = last * float(np.exp(-V.Z80 * sd)), last * float(np.exp(V.Z80 * sd))
        dd = LV.max_drawdown(df.close)[0]
        fund_dd = LV.max_drawdown(LV.synthetic(df.close, lev))[0] if lev != 1 else None
    except Exception as exc:  # fail-open
        logger.info("stock risk lines skipped for %s: %s", symbol, exc)
        return []
    if not english:
        return []  # this edition writes the risk section in English only
    out = ["### 📉 Downside check (numbers from code)", ""]
    if lev != 1:
        out.append(f"- **{symbol}** is a daily-reset {lev:g}x fund on {underlying}; ranges below are for {symbol} itself.")
    out.append(f"- Next week, 4 weeks in 5: **{lo80:,.2f} to {hi80:,.2f}** ({fc.method}, weekly vol {sd:.1%}).")
    if rec:
        out.append(f"- Scorecard: this model's 80% range held **{rec.in80:.0%}** of the last {rec.weeks} weeks "
                   f"(95% range: {rec.in95:.0%}).")
    worst = f"- Worst fall in the data window: {underlying} {dd:.1%}"
    out.append(worst + (f"; at {lev:g}x that stretch was **{fund_dd:.1%}**." if fund_dd is not None else "."))
    out.append("")
    return out
