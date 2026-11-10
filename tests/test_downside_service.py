# -*- coding: utf-8 -*-
"""Downside block: snapshot -> Deep Fried engine -> JSON, offline with synthetic bars."""

import os
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.services import downside_service as DS

try:
    from downside.data import Bars
except ImportError:  # pragma: no cover
    Bars = None


def _bars(seed, n=1000, sigma=0.02, start=100.0):
    rng = np.random.default_rng(seed)
    steps = 40
    z = rng.standard_normal((n, steps)) * sigma / np.sqrt(steps)
    path = start * np.exp(np.cumsum(z.ravel())).reshape(n, steps)
    opens = np.concatenate([[start], path[:-1, -1]])
    return pd.DataFrame({"open": opens, "high": np.maximum(path.max(1), opens), "low": np.minimum(path.min(1), opens),
                         "close": path[:, -1], "volume": 1e6},
                        index=pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n, name="date"))


def _snapshot():
    return {"currency": "USD", "total_cash": 100.0, "accounts": [
        {"account_id": 1, "positions": [
            {"symbol": "NVDA", "market": "us", "quantity": 3, "avg_cost": 200},
            {"symbol": "GGLL", "market": "us", "quantity": 10, "avg_cost": 80},
            {"symbol": "600519", "market": "cn", "quantity": 1, "avg_cost": 1500},
        ]},
        {"account_id": 2, "positions": [{"symbol": "NVDA", "market": "us", "quantity": 1, "avg_cost": 180}]},
    ]}


@unittest.skipIf(Bars is None, "downside engine not importable")
class DownsideServiceTest(unittest.TestCase):
    def test_aggregates_us_positions_and_skips_others(self):
        positions, skipped = DS._aggregate_positions(_snapshot())
        nvda = next(p for p in positions if p["symbol"] == "NVDA")
        self.assertEqual(nvda["shares"], 4)
        self.assertAlmostEqual(nvda["avg_cost"], 195.0)
        self.assertEqual(skipped, ["600519"])

    def test_parse_levels(self):
        lv = DS._parse_levels("AVGO:exit_below:290, nvda:buy_at:200, junk, TSM:sell:1")
        self.assertEqual(lv, {"AVGO": {"exit_below": 290.0}, "NVDA": {"buy_at": 200.0}})

    @patch.dict(os.environ, {"DOWNSIDE_ENABLED": "true", "DOWNSIDE_LEVELS": "GOOGL:exit_below:90", "DOWNSIDE_WATCH": ""})
    def test_build_block(self):
        frames = {"NVDA": _bars(1, start=180, sigma=0.03), "GOOGL": _bars(2, start=100, sigma=0.018)}
        r = frames["GOOGL"].close.pct_change().fillna(0.0)
        c = 50 * np.cumprod(1 + 2 * r)
        frames["GGLL"] = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6},
                                      index=frames["GOOGL"].index)
        with patch.object(DS, "_load_bars", return_value=Bars(frames, "test")):
            block = DS.build_downside(_snapshot())
        self.assertTrue(block["available"], block)
        self.assertEqual(block["skipped"], ["600519"])
        ggll = next(h for h in block["holdings"] if h["symbol"] == "GGLL")
        self.assertEqual((ggll["underlying"], ggll["leverage"]), ("GOOGL", 2.0))
        self.assertEqual(len(block["stress"]), 6)
        self.assertEqual(block["levels"][0]["underlying"], "GOOGL")
        self.assertIsNotNone(block["scorecard"])
        self.assertGreater(block["exposure"], block["book_value"] - 100)

    @patch.dict(os.environ, {"DOWNSIDE_ENABLED": "true"})
    def test_fail_open(self):
        with patch.object(DS, "_load_bars", side_effect=RuntimeError("network down")):
            block = DS.build_downside(_snapshot())
        self.assertFalse(block["available"])
        self.assertIn("network down", block["reason"])

    def test_disabled(self):
        with patch.dict(os.environ, {"DOWNSIDE_ENABLED": "false"}):
            self.assertEqual(DS.build_downside(_snapshot())["reason"], "disabled")

    def test_leverage_prompt_note(self):
        self.assertIn("2x fund on **GOOGL**", DS.leverage_prompt_note("ggll"))
        self.assertEqual(DS.leverage_prompt_note("MSFT"), "")

    @patch.dict(os.environ, {"DOWNSIDE_ENABLED": "true"})
    def test_stock_risk_lines(self):
        frames = {"GOOGL": _bars(2, start=100, sigma=0.018)}
        r = frames["GOOGL"].close.pct_change().fillna(0.0)
        c = 50 * np.cumprod(1 + 2 * r)
        frames["GGLL"] = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6},
                                      index=frames["GOOGL"].index)
        with patch.object(DS, "_load_bars", return_value=Bars(frames, "test")):
            text = "\n".join(DS.stock_risk_lines("GGLL"))
        self.assertIn("Downside check", text)
        self.assertIn("2x fund on GOOGL", text)
        self.assertIn("Scorecard", text)
        self.assertEqual(DS.stock_risk_lines("600519"), [])

    @patch.dict(os.environ, {"DOWNSIDE_ENABLED": "true"})
    def test_stock_risk_lines_fail_open(self):
        with patch.object(DS, "_load_bars", side_effect=RuntimeError("down")):
            self.assertEqual(DS.stock_risk_lines("NVDA"), [])


if __name__ == "__main__":
    unittest.main()


def test_last_close_reads_cached_bars(tmp_path, monkeypatch):
    import datetime as dt
    import pandas as pd
    from src.services import downside_service as svc

    idx = pd.to_datetime(["2026-11-05", "2026-11-06"])
    pd.DataFrame({"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [100.0, 101.5], "volume": [1, 1]},
                 index=idx).rename_axis("date").to_csv(tmp_path / "NVDA.csv")
    (tmp_path / "manifest.json").write_text('{"fetched": "2026-11-06T19:00", "tickers": ["NVDA"]}')
    monkeypatch.setattr(svc, "_CACHE_DIR", tmp_path)
    monkeypatch.setenv("DOWNSIDE_ENABLED", "true")

    import downside.data as D
    monkeypatch.setattr(D, "check", lambda frames, today: ([], []))
    assert svc.last_close("NVDA", dt.date(2026, 11, 8)) == (101.5, dt.date(2026, 11, 6))
    assert svc.last_close("NVDA", dt.date(2026, 11, 5)) == (100.0, dt.date(2026, 11, 5))
    assert svc.last_close("600519", dt.date(2026, 11, 8)) is None  # not a US code


def test_last_close_off_when_disabled(monkeypatch):
    import datetime as dt
    from src.services import downside_service as svc

    monkeypatch.setenv("DOWNSIDE_ENABLED", "false")
    assert svc.last_close("NVDA", dt.date(2026, 11, 8)) is None
