import numpy as np
import pandas as pd
import pytest

from downside import levered as LV
from downside import llm, portfolio, report, risk, vol
from downside.data import check

from .conftest import gbm_bars


# --- leveraged funds ---------------------------------------------------------------------------

def test_multiplier_smooth_path():
    assert LV.multiplier(-0.20, 2) == pytest.approx(0.64)
    assert LV.multiplier(-0.20, 1) == pytest.approx(0.80)
    assert LV.multiplier(0.10, 3) == pytest.approx(1.331)


def test_multiplier_choppy_path_costs_more():
    assert LV.multiplier(-0.2, 2, v=0.01) < LV.multiplier(-0.2, 2)
    assert LV.multiplier(-0.2, 1, v=0.01) == pytest.approx(LV.multiplier(-0.2, 1))  # no drag at 1x
    assert LV.multiplier(-0.2, -3, v=0.01) < LV.multiplier(-0.2, -3)                # inverse funds decay too


def test_inverse_round_trip():
    for L in (2, 3, -2):
        for v in (0.0, 0.004):
            R = LV.underlying_move_for(LV.multiplier(-0.15, L, v), L, v)
            assert R == pytest.approx(-0.15)


def test_synthetic_matches_daily_leverage():
    close = pd.Series([100, 110, 99, 99], index=pd.bdate_range("2026-01-01", periods=4))
    fund = LV.synthetic(close, 2)
    # +10% -> +20%, then -10% -> -20%: 1.2 * 0.8, and a flat day changes nothing.
    assert fund.values == pytest.approx([1.0, 1.2, 0.96, 0.96])


def test_max_drawdown():
    s = pd.Series([1, 2, 1, 1.5, 0.5, 3], index=pd.bdate_range("2026-01-01", periods=6))
    dd, peak, trough = LV.max_drawdown(s)
    assert dd == pytest.approx(-0.75)
    assert (peak, trough) == (s.index[1], s.index[4])


def test_resolve_registry_and_override():
    assert LV.resolve("tqqq") == ("QQQ", 3)
    assert LV.resolve("MSFT") == ("MSFT", 1)
    assert LV.resolve("XYZU", "xyz", 2) == ("XYZ", 2)


# --- volatility --------------------------------------------------------------------------------

def test_forecast_recovers_true_volatility():
    for seed, sigma in ((11, 0.01), (12, 0.025)):
        fc = vol.forecast(gbm_bars(seed, n=1000, sigma_daily=sigma))
        assert fc.method == "HAR-PK"
        assert fc.weeks == vol.K_WEEKS
        assert fc.sd5 == pytest.approx(sigma * np.sqrt(5), rel=0.25)


def test_short_history_falls_back():
    fc = vol.forecast(gbm_bars(13, n=300, sigma_daily=0.02))
    assert fc.method.startswith("EWMA")
    assert fc.sd5 == pytest.approx(0.02 * np.sqrt(5), rel=0.35)


# --- portfolio ---------------------------------------------------------------------------------

def test_parse_resolves_leverage(raw_portfolio):
    pf = portfolio.parse(raw_portfolio)
    tq = next(p for p in pf.positions if p.symbol == "TQQQ")
    assert (tq.underlying, tq.leverage, tq.exit_below) == ("QQQ", 3, 600)
    assert pf.tickers() == ["GGLL", "GOOGL", "NVDA", "QQQ", "SPY", "TQQQ"]


@pytest.mark.parametrize("bad", [{"positions": []}, {"positions": [{"symbol": "X", "shares": 0, "avg_cost": 1}]},
                                 {"positions": [{"symbol": "X"}]}])
def test_parse_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        portfolio.parse(bad)


# --- analysis ----------------------------------------------------------------------------------

def test_analysis_numbers(bars, raw_portfolio):
    pf = portfolio.parse(raw_portfolio)
    a = risk.analyze(pf, bars)

    positions_value = sum(p.shares * bars.close(p.symbol) for p in pf.positions)
    assert a.book_value == pytest.approx(positions_value + 100)
    assert a.exposure == pytest.approx(sum(h.value * h.pos.leverage for h in a.holdings))

    # An exit line on the underlying, translated to the fund on a smooth path.
    row = next(r for r in a.levels if r.pos.symbol == "TQQQ")
    tq_price, qqq = bars.close("TQQQ"), bars.close("QQQ")
    assert row.fund_at_level == pytest.approx(tq_price * (600 / qqq) ** 3)
    assert row.loss_from_cost == pytest.approx(row.fund_at_level / 60 - 1)
    assert 0 <= row.close_beyond <= row.touch <= 1

    # Stress: losses grow with the move, choppy is worse than smooth on the way down.
    down = [s for s in a.stress if s.move < 0]
    assert all(x.smooth > y.smooth for x, y in zip(down, down[1:]))
    assert all(s.choppy <= s.smooth for s in down)
    s20 = next(s for s in a.stress if s.move == -0.20)
    expected = sum(h.value * (LV.multiplier(-0.2, h.pos.leverage) - 1) for h in a.holdings)
    assert s20.smooth == pytest.approx(expected)

    # Recovery: a 2x fund down 36% needs the underlying back about 25%.
    for h in a.holdings:
        if h.pos.levered and h.fund_needed > 0:
            assert LV.multiplier(h.und_needed, h.pos.leverage) == pytest.approx(1 + h.fund_needed)

    assert {r.ticker for r in a.ranges} == {"NVDA", "QQQ", "GOOGL", "SPY"}
    assert all(r.r95[0] < r.r80[0] < r.last < r.r80[1] < r.r95[1] for r in a.ranges)
    assert a.week_sd > 0


def test_report_renders(bars, raw_portfolio):
    a = risk.analyze(portfolio.parse(raw_portfolio), bars)
    md = report.render(a)
    for section in ("## If things fall", "## Your levels", "## Positions", "## How bad it has been",
                    "## Next week's ranges", "not investment advice"):
        assert section in md
    s = report.summary(a)
    assert "falls 20%" in s and len(s) < 1900


# --- data checks and the news guard ---------------------------------------------------------------

def test_check_flags_bad_bars():
    df = gbm_bars(21, n=100)
    df.iloc[-1, df.columns.get_loc("close")] = -1
    problems, _ = check({"BAD": df}, df.index[-1].date())
    assert problems and "BAD" in problems[0]


def test_check_flags_stale_bars():
    df = gbm_bars(22, n=100, end="2026-09-01")
    problems, _ = check({"OLD": df}, pd.Timestamp("2026-11-06").date())
    assert any("latest bar" in p for p in problems)


def test_unsupported_numbers():
    src = "NVDA: Nvidia falls 9% as chip index drops 12.3% (Reuters)"
    assert llm.unsupported_numbers("Nvidia fell 9% and chips 12.3%.", src) == []
    assert llm.unsupported_numbers("Nvidia could fall to 150.", src) == ["150"]


# --- implied volatility and the scorecard --------------------------------------------------------

def test_implied_forecast_uses_the_index():
    df = gbm_bars(31, n=1000, sigma_daily=0.015)
    iv = pd.Series(0.015 * np.sqrt(252) * 100, index=df.index)  # an implied vol that matches the truth
    fc = vol.forecast(df, iv, "VIX")
    assert fc.method == "Implied (VIX)"
    assert fc.sd5 == pytest.approx(0.015 * np.sqrt(5), rel=0.2)


def test_implied_missing_falls_back_to_har():
    df = gbm_bars(32, n=1000)
    assert vol.forecast(df, None).method == "HAR-PK"
    stale = pd.Series([20.0], index=[df.index[100]])  # ffilled, but k still computable
    assert vol.forecast(df, stale, "VIX").method == "Implied (VIX)"


def test_track_record_is_calibrated_on_gbm():
    df = gbm_bars(33, n=1500, sigma_daily=0.02)
    rec = vol.track_record(df, weeks=150)
    assert rec.weeks >= 100
    assert 0.68 <= rec.in80 <= 0.92
    assert rec.in95 >= 0.88


def test_scorecard_in_report(bars, raw_portfolio):
    md = report.render(risk.analyze(portfolio.parse(raw_portfolio), bars))
    assert "## Scorecard" in md and "| **All** |" in md
