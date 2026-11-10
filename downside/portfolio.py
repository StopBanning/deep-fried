"""Read a portfolio file: positions, optional levels, and a watch list."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .levered import resolve


@dataclass
class Position:
    symbol: str
    shares: float
    avg_cost: float
    underlying: str
    leverage: float
    exit_below: float | None = None   # a line on the underlying
    buy_at: float | None = None       # an add level on the underlying

    @property
    def levered(self) -> bool:
        return self.leverage != 1


@dataclass
class Portfolio:
    name: str
    cash: float
    positions: list[Position]
    watch: list[str] = field(default_factory=list)

    def tickers(self) -> list[str]:
        out = {p.symbol for p in self.positions} | {p.underlying for p in self.positions} | set(self.watch)
        return sorted(out)

    def underlyings(self) -> list[str]:
        return sorted({p.underlying for p in self.positions} | set(self.watch))


def parse(raw: dict) -> Portfolio:
    positions = []
    for i, p in enumerate(raw.get("positions") or []):
        try:
            symbol = str(p["symbol"]).upper()
            shares, cost = float(p["shares"]), float(p["avg_cost"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"position {i + 1}: needs symbol, shares and avg_cost ({e})") from e
        if shares <= 0 or cost <= 0:
            raise ValueError(f"{symbol}: shares and avg_cost must be positive")
        und, lev = resolve(symbol, p.get("underlying"), p.get("leverage"))
        levels = p.get("levels") or {}
        positions.append(Position(symbol, shares, cost, und, lev,
                                  _num(levels.get("exit_below")), _num(levels.get("buy_at"))))
    if not positions:
        raise ValueError("the portfolio has no positions")
    return Portfolio(str(raw.get("name") or "Portfolio"), float(raw.get("cash") or 0.0), positions,
                     [str(t).upper() for t in raw.get("watch") or []])


def load(path: str | Path | None) -> Portfolio:
    """From a file, or from the PORTFOLIO_YAML environment variable (how CI passes it without committing it)."""
    if path:
        return parse(yaml.safe_load(Path(path).read_text()) or {})
    text = os.environ.get("PORTFOLIO_YAML")
    if not text:
        raise ValueError("no portfolio: pass --portfolio or set PORTFOLIO_YAML")
    return parse(yaml.safe_load(text) or {})


def _num(x) -> float | None:
    return None if x is None else float(x)
