# -*- coding: utf-8 -*-
from datetime import date

import pytest

from src.services import desk_service as desk


def test_notes_latest_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("DESK_NOTES_DIR", str(tmp_path))
    assert desk.latest_note() == {"available": False}
    desk.save_note("# old", date(2026, 11, 6))
    desk.save_note("# new", date(2026, 11, 9))
    (tmp_path / "junk.md").write_text("x")
    note = desk.latest_note()
    assert note["available"] and note["date"] == "2026-11-09" and note["markdown"].strip() == "# new"
    with pytest.raises(ValueError):
        desk.save_note("  ")


def test_differences():
    cur = {"NVDA": {"quantity": 3.5, "avg_cost": 190.0}, "OLD": {"quantity": 1, "avg_cost": 10}}
    tgt = {"NVDA": {"quantity": 4.25, "avg_cost": 180.4}, "NEW": {"quantity": 2, "avg_cost": 5}}
    d = desk._differences(cur, tgt, -55.5, 0.0)
    assert len(d) == 4 and any(x.startswith("cash") for x in d)
    assert desk._differences(tgt, tgt, 0.0, 0.0) == []


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    from src.config import Config
    from src.storage import DatabaseManager

    env = tmp_path / ".env"
    db = tmp_path / "desk.db"
    env.write_text(f"STOCK_LIST=NVDA\nADMIN_AUTH_ENABLED=false\nDATABASE_PATH={db}\n")
    monkeypatch.setenv("ENV_FILE", str(env))
    monkeypatch.setenv("DATABASE_PATH", str(db))
    Config.reset_instance()
    DatabaseManager.reset_instance()
    DatabaseManager.get_instance()
    yield
    DatabaseManager.reset_instance()
    Config.reset_instance()


def test_sync_rebuilds_account_to_match_broker(temp_db):
    from src.services.portfolio_service import PortfolioService

    as_of = date(2026, 11, 9)
    first = desk.sync_account(account_name="Roth", as_of=as_of, cash=-55.5, positions=[
        {"symbol": "NVDA", "quantity": 3.5, "avg_cost": 190.0},
        {"symbol": "OLD", "quantity": 2, "avg_cost": 10.0},
    ])
    assert first["changed"]
    again = desk.sync_account(account_name="Roth", as_of=as_of, cash=-55.5, positions=[
        {"symbol": "NVDA", "quantity": 3.5, "avg_cost": 190.0},
        {"symbol": "OLD", "quantity": 2, "avg_cost": 10.0},
    ])
    assert again == {"account_id": first["account_id"], "changed": False, "differences": []}

    target = [{"symbol": "NVDA", "quantity": 4.25, "avg_cost": 180.4},
              {"symbol": "GGLL", "quantity": 9, "avg_cost": 72.3}]
    assert desk.sync_account(account_name="Roth", as_of=as_of, cash=0.0, positions=target, dry_run=True)["changed"]
    result = desk.sync_account(account_name="Roth", as_of=as_of, cash=0.0, positions=target)
    assert result["changed"] and len(result["differences"]) == 4

    snap = PortfolioService().get_portfolio_snapshot(account_id=result["account_id"], as_of=as_of,
                                                      include_realtime=False, read_only=True)
    acct = snap["accounts"][0]
    held = {p["symbol"]: (round(p["quantity"], 6), round(p["avg_cost"], 2)) for p in acct["positions"]}
    assert held == {"NVDA": (4.25, 180.4), "GGLL": (9.0, 72.3)}
    assert abs(acct["total_cash"]) < 0.01
