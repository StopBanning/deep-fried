# -*- coding: utf-8 -*-
"""Desk mode: keep one portfolio account in step with a broker, and store a daily desk note.

Desk mode is for running this app next to an assistant that can read your brokerage account (for
example a scheduled Claude session with a read-only Robinhood connector). The assistant:

1. writes your current positions and cash to a JSON file and runs
   `python scripts/desk.py sync --file positions.json`; when they differ from the app, the account is
   rebuilt to match: one buy per position at the broker's average cost, plus one cash entry.
   The broker is the source of truth, so the account's own trade history is replaced.
2. writes its analysis as Markdown and runs `python scripts/desk.py note --file note.md`; the
   portfolio page shows the latest note in a "Desk note" card.

Nothing here talks to a broker or places orders. Notes live in DESK_NOTES_DIR (default data/desk_notes).
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

_FAR_FUTURE = date(9999, 12, 31)
_QTY_TOL = 1e-6
_MONEY_TOL = 0.01


def _notes_dir() -> Path:
    return Path(os.getenv("DESK_NOTES_DIR", "data/desk_notes"))


# ----------------------------------------------------------------------
# Position sync
# ----------------------------------------------------------------------
def _normalize(positions: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for p in positions:
        symbol = str(p.get("symbol") or "").strip().upper()
        qty = float(p.get("quantity") or 0.0)
        cost = float(p.get("avg_cost") or 0.0)
        if not symbol or qty <= 0:
            continue
        if cost <= 0:
            raise ValueError(f"{symbol}: avg_cost must be > 0")
        out[symbol] = {"quantity": qty, "avg_cost": cost}
    return out


def _differences(current: Dict[str, Dict[str, float]], target: Dict[str, Dict[str, float]],
                 current_cash: float, target_cash: float) -> List[str]:
    diffs: List[str] = []
    for symbol in sorted(set(current) | set(target)):
        a, b = current.get(symbol), target.get(symbol)
        if a is None:
            diffs.append(f"{symbol}: new position {b['quantity']:g} @ {b['avg_cost']:.2f}")
        elif b is None:
            diffs.append(f"{symbol}: no longer held (app had {a['quantity']:g})")
        elif abs(a["quantity"] - b["quantity"]) > _QTY_TOL or abs(a["avg_cost"] - b["avg_cost"]) > _MONEY_TOL:
            diffs.append(f"{symbol}: {a['quantity']:g} @ {a['avg_cost']:.2f} -> {b['quantity']:g} @ {b['avg_cost']:.2f}")
    if abs(current_cash - target_cash) > _MONEY_TOL:
        diffs.append(f"cash: {current_cash:.2f} -> {target_cash:.2f}")
    return diffs


def sync_account(*, account_name: str, positions: List[Dict[str, Any]], cash: float,
                 as_of: Optional[date] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Make `account_name` hold exactly `positions` and `cash` (US market, USD).

    positions: [{"symbol", "quantity", "avg_cost"}]. Creates the account if it doesn't exist.
    Returns {"account_id", "changed", "differences"}.
    """
    from src.services.portfolio_service import PortfolioService

    as_of = as_of or date.today()
    target = _normalize(positions)
    svc = PortfolioService()
    account = next((a for a in svc.list_accounts() if a["name"] == account_name), None)
    if account is None:
        if dry_run:
            return {"account_id": None, "changed": True, "differences": [f"create account {account_name}"]}
        account = svc.create_account(name=account_name, broker="Robinhood", market="us", base_currency="USD")
    account_id = int(account["id"])

    snap = svc.get_portfolio_snapshot(account_id=account_id, as_of=as_of, include_realtime=False, read_only=True)
    acct = (snap.get("accounts") or [{}])[0]
    current = _normalize([{"symbol": p.get("symbol"), "quantity": p.get("quantity"), "avg_cost": p.get("avg_cost")}
                          for p in acct.get("positions") or []])
    diffs = _differences(current, target, float(acct.get("total_cash") or 0.0), float(cash))
    if not diffs or dry_run:
        return {"account_id": account_id, "changed": bool(diffs), "differences": diffs}

    repo = svc.repo
    with repo.portfolio_write_session() as session:
        for row in repo.list_trades_in_session(session=session, account_id=account_id, as_of=_FAR_FUTURE):
            repo.delete_trade_in_session(session=session, trade_id=row.id)
        for row in repo.list_cash_ledger_in_session(session=session, account_id=account_id, as_of=_FAR_FUTURE):
            repo.delete_cash_ledger_in_session(session=session, entry_id=row.id)
        for row in repo.list_corporate_actions_in_session(session=session, account_id=account_id, as_of=_FAR_FUTURE):
            repo.delete_corporate_action_in_session(session=session, action_id=row.id)

        bought = 0.0
        for symbol, p in sorted(target.items()):
            repo.add_trade_in_session(
                session=session, account_id=account_id, trade_uid=None,
                symbol=svc._normalize_symbol_for_storage(symbol), market="us", currency="USD",
                trade_date=as_of, side="buy", quantity=p["quantity"], price=p["avg_cost"],
                fee=0.0, tax=0.0, note="desk sync (broker average cost)", dedup_hash=None,
            )
            bought += p["quantity"] * p["avg_cost"]
        funding = float(cash) + bought
        if abs(funding) > _MONEY_TOL:
            repo.add_cash_ledger_in_session(
                session=session, account_id=account_id, event_date=as_of,
                direction="in" if funding > 0 else "out", amount=abs(funding), currency="USD",
                note="desk sync (net funding)",
            )
    return {"account_id": account_id, "changed": True, "differences": diffs}


# ----------------------------------------------------------------------
# Desk notes
# ----------------------------------------------------------------------
_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def save_note(markdown: str, note_date: Optional[date] = None) -> Path:
    text = (markdown or "").strip()
    if not text:
        raise ValueError("note is empty")
    d = _notes_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{(note_date or date.today()).isoformat()}.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def latest_note() -> Dict[str, Any]:
    d = _notes_dir()
    if not d.is_dir():
        return {"available": False}
    dated = sorted((m.group(1), p) for p in d.iterdir() if (m := _NAME.match(p.name)))
    if not dated:
        return {"available": False}
    day, path = dated[-1]
    return {"available": True, "date": day, "markdown": path.read_text(encoding="utf-8")}
