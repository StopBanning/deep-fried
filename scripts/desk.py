#!/usr/bin/env python3
"""Desk mode CLI: sync an account to broker positions, or save today's desk note.

  python scripts/desk.py sync --file positions.json [--dry-run]
      positions.json: {"account": "Brokerage", "cash": 250, "positions": [{"symbol": "NVDA", "quantity": 6, "avg_cost": 195}]}
  python scripts/desk.py note --file note.md [--date 2026-11-09]

See src/services/desk_service.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--file", required=True)
    s.add_argument("--dry-run", action="store_true")
    n = sub.add_parser("note")
    n.add_argument("--file", required=True)
    n.add_argument("--date")
    args = ap.parse_args()

    import os
    os.chdir(ROOT)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    from src.services import desk_service

    if args.cmd == "sync":
        spec = json.loads(Path(args.file).read_text())
        result = desk_service.sync_account(
            account_name=spec.get("account") or "Desk", positions=spec.get("positions") or [],
            cash=float(spec.get("cash") or 0.0), dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
    else:
        path = desk_service.save_note(Path(args.file).read_text(encoding="utf-8"),
                                      date.fromisoformat(args.date) if args.date else None)
        print(f"saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
