"""Everything the report says, as numbers: the book, ranges, level odds, stress tests and history.

Odds assume a driftless lognormal path over the next 5 sessions. "Touch" is the chance the price reaches a
level at any point (reflection principle: twice the end-of-week chance, capped at 1); "close beyond" is
the chance the week ends past it. Book ranges treat dollar moves as linear in each underlying's return,
with correlations from the last 250 sessions.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from . import levered as LV
from .data import Bars
from .portfolio import Portfolio, Position
from .vol import HORIZON, Forecast, Record, correlation, forecast, track_record

Z80, Z95 = stats.norm.ppf(0.9), stats.norm.ppf(0.975)
STRESS_MOVES = (-0.10, -0.20, -0.30, -0.40, 0.10, 0.20)
MONTH = 21


@dataclass
class Holding:
    pos: Position
    price: float
    prev: float
    value: float
    pnl: float
    pnl_pct: float
    day: float
    fund_needed: float        # move in this holding to get back to cost
    und_needed: float         # rough move in the underlying for the same (smooth path)


@dataclass
class LevelRow:
    pos: Position
    kind: str                 # "exit_below" or "buy_at"
    level: float
    und_price: float
    distance: float           # log distance from the underlying's price
    touch: float
    close_beyond: float
    fund_at_level: float      # this holding's price if the underlying gets there smoothly
    loss_from_cost: float     # that price against the holding's average cost


@dataclass
class StressRow:
    move: float
    smooth: float             # book dollar change on a smooth path
    choppy: float             # same move with a month of forecast volatility along the way
    book_after: float


@dataclass
class HistoryRow:
    pos: Position
    start: str
    und_dd: float
    und_dd_dates: tuple[str, str]
    fund_dd: float | None     # synthetic daily-reset fund over the same window
    worst_week: float         # worst 5-session move in the underlying


@dataclass
class RangeRow:
    ticker: str
    last: float
    fc: Forecast
    r80: tuple[float, float]
    r95: tuple[float, float]
    record: Record | None


@dataclass
class Analysis:
    portfolio: Portfolio
    as_of: str
    holdings: list[Holding]
    book_value: float
    cost_basis: float
    day_change: float
    exposure: float            # dollars of underlying the book moves like
    week_sd: float             # book's weekly dollar standard deviation
    levels: list[LevelRow]
    stress: list[StressRow]
    history: list[HistoryRow]
    ranges: list[RangeRow]
    warnings: list[str]

    @property
    def pnl(self) -> float:
        return self.book_value - self.portfolio.cash - self.cost_basis


def odds(distance: float, sd: float) -> tuple[float, float]:
    end = float(stats.norm.sf(abs(distance) / sd))
    return min(1.0, 2 * end), end


def analyze(pf: Portfolio, bars: Bars) -> Analysis:
    f = bars.frames
    fc, record = {}, {}
    for t in pf.underlyings():
        iv, name = bars.implied_for(t)
        fc[t] = forecast(f[t], iv, name)
        record[t] = track_record(f[t], iv)

    holdings = []
    for p in pf.positions:
        price, prev = bars.close(p.symbol), float(f[p.symbol].close.iloc[-2])
        value = p.shares * price
        need = p.avg_cost / price - 1
        holdings.append(Holding(p, price, prev, value, value - p.shares * p.avg_cost, price / p.avg_cost - 1,
                                p.shares * (price - prev), need,
                                LV.underlying_move_for(1 + need, p.leverage) if p.levered else need))

    book = sum(h.value for h in holdings) + pf.cash
    cost = sum(h.pos.shares * h.pos.avg_cost for h in holdings)

    # Book weekly range: dollar exposure per underlying, scaled by its forecast sd and correlations.
    und = pf.underlyings()
    expo = {u: 0.0 for u in und}
    for h in holdings:
        expo[h.pos.underlying] += h.value * h.pos.leverage
    corr = correlation(f, und).reindex(index=und, columns=und).fillna(0.0).to_numpy(copy=True)
    np.fill_diagonal(corr, 1.0)
    dollars = np.array([expo[u] * fc[u].sd5 for u in und])
    week_sd = float(np.sqrt(max(dollars @ corr @ dollars, 0.0)))

    levels = []
    for h in holdings:
        p = h.pos
        u_price = bars.close(p.underlying)
        for kind in ("exit_below", "buy_at"):
            lvl = getattr(p, kind)
            if lvl is None:
                continue
            d = float(np.log(lvl / u_price))
            touch, end = odds(d, fc[p.underlying].sd5)
            at = h.price * LV.multiplier(lvl / u_price - 1, p.leverage)
            levels.append(LevelRow(p, kind, lvl, u_price, d, touch, end, at, at / p.avg_cost - 1))

    stress = []
    for R in STRESS_MOVES:
        smooth = choppy = 0.0
        for h in holdings:
            v = fc[h.pos.underlying].var5 * MONTH / HORIZON
            smooth += h.value * (LV.multiplier(R, h.pos.leverage) - 1)
            choppy += h.value * (LV.multiplier(R, h.pos.leverage, v) - 1)
        stress.append(StressRow(R, smooth, choppy, book + smooth))

    history, seen = [], set()
    for h in holdings:
        p = h.pos
        if (p.underlying, p.leverage) in seen:
            continue
        seen.add((p.underlying, p.leverage))
        close = f[p.underlying].close
        dd, peak, trough = LV.max_drawdown(close)
        fund_dd = LV.max_drawdown(LV.synthetic(close, p.leverage))[0] if p.levered else None
        worst_week = float((close / close.shift(HORIZON) - 1).min())
        history.append(HistoryRow(p, str(close.index[0].date()), dd, (str(peak.date()), str(trough.date())),
                                  fund_dd, worst_week))

    ranges = []
    for t in und:
        last, sd = bars.close(t), fc[t].sd5
        ranges.append(RangeRow(t, last, fc[t],
                               tuple(last * np.exp(np.array([-1, 1]) * Z80 * sd)),
                               tuple(last * np.exp(np.array([-1, 1]) * Z95 * sd)), record[t]))

    return Analysis(pf, str(bars.last_date()), holdings, book, cost, sum(h.day for h in holdings),
                    sum(expo.values()), week_sd, levels, stress, history, ranges, list(bars.warnings))
