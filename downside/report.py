"""Turn an Analysis into a Markdown report (full) and a short text summary (for push messages)."""
from __future__ import annotations

from .news import Headline
from .risk import Z80, Z95, Analysis

LATE_LINE = -0.25  # an exit line that only fires after a loss this big gets a warning


def money(x: float, sign: bool = False) -> str:
    s = f"${abs(x):,.0f}"
    if x < 0:
        return "-" + s
    return ("+" + s) if sign else s


def pct(x: float, sign: bool = True) -> str:
    return f"{x:+.1%}" if sign else f"{x:.1%}"


def chance(p: float) -> str:
    if p < 0.005:
        return "<1%"
    if p > 0.995:
        return ">99%"
    return f"{p:.0%}"


def headline_numbers(a: Analysis) -> list[str]:
    pf = a.portfolio
    out = [f"**Book {money(a.book_value)}**"
           + (f" (cash {money(pf.cash)})" if pf.cash else "")
           + f", {money(a.day_change, True)} on the day, {money(a.pnl, True)} against cost "
           f"({pct(a.pnl / a.cost_basis)})."]
    lev = a.exposure / max(a.book_value, 1e-9)
    out.append(f"It moves like **{money(a.exposure)} of stock** ({lev:.2f}x the book, leverage counted). "
               f"Next week, 4 weeks in 5 should land within **±{money(Z80 * a.week_sd)}**; "
               f"a 1-in-40 bad week costs about **{money(Z95 * a.week_sd)}**.")
    return out


def summary(a: Analysis) -> str:
    """A few lines for a phone notification."""
    lines = [f"Deep Fried, {a.portfolio.name}, {a.as_of}"]
    lines += [s.replace("**", "") for s in headline_numbers(a)]
    late = [r for r in a.levels if r.kind == "exit_below" and r.loss_from_cost <= LATE_LINE]
    near = [r for r in a.levels if r.touch >= 0.5]
    for r in near:
        lines.append(f"{r.pos.underlying} {r.level:g} ({r.kind.replace('_', ' ')}): {chance(r.touch)} touch odds this week.")
    for r in late:
        lines.append(f"{r.pos.symbol}: its {r.pos.underlying} {r.level:g} line only fires {pct(r.loss_from_cost)} "
                     "from your cost.")
    worst = next(s for s in a.stress if s.move == -0.20)
    lines.append(f"If everything you own falls 20%: {money(worst.smooth)} smooth, {money(worst.choppy)} choppy.")
    return "\n".join(lines)


def render(a: Analysis, news: dict[str, list[Headline]] | None = None, brief: str | None = None) -> str:
    pf = a.portfolio
    L = [f"# Deep Fried: {pf.name}, close of {a.as_of}", ""]
    L += headline_numbers(a)
    if a.warnings:
        L += ["", "**Data warnings:** " + "; ".join(a.warnings) + "."]

    L += ["", "## If things fall",
          "Every underlying moves the same amount. *Smooth* is a straight-line move; *choppy* is the same move "
          "with a month of forecast volatility along the way, which costs daily-reset funds more.", "",
          "| Everything moves | Smooth path | Choppy path | Book after (smooth) |", "|---|---|---|---|"]
    L += [f"| {pct(s.move)} | {money(s.smooth, True)} | {money(s.choppy, True)} | {money(s.book_after)} |"
          for s in a.stress]

    if a.levels:
        L += ["", "## Your levels",
              "Levels sit on the underlying. The last two columns show what the holding is worth if the "
              "underlying gets there, and how far that is from your cost.", "",
              "| Holding | Level | Distance | Touch this week | Close beyond | Holding at level | From your cost |",
              "|---|---|---|---|---|---|---|"]
        for r in a.levels:
            name = "exit below" if r.kind == "exit_below" else "buy at"
            L.append(f"| {r.pos.symbol} | {r.pos.underlying} {name} {r.level:g} | {pct(r.distance)} | {chance(r.touch)} "
                     f"| {chance(r.close_beyond)} | {r.fund_at_level:,.2f} | {pct(r.loss_from_cost)} |")
        late = [r for r in a.levels if r.kind == "exit_below" and r.loss_from_cost <= LATE_LINE]
        for r in late:
            L.append(f"\n> **{r.pos.symbol}:** the {r.pos.underlying} {r.level:g} line only fires once the holding "
                     f"is {pct(r.loss_from_cost)} from your cost. If that's more than you meant to risk, the line "
                     "is too far away.")

    L += ["", "## Positions", "",
          "| Holding | Tracks | Price | Value | Day | Against cost | To get back to cost |", "|---|---|---|---|---|---|---|"]
    for h in a.holdings:
        p = h.pos
        tracks = f"{p.underlying} {p.leverage:g}x" if p.levered else "itself"
        back = (f"{pct(h.fund_needed)} (about {pct(h.und_needed)} in {p.underlying})" if p.levered
                else pct(h.fund_needed))
        if h.fund_needed <= 0:
            back = "above cost"
        L.append(f"| {p.symbol} | {tracks} | {h.price:,.2f} | {money(h.value)} | {money(h.day, True)} "
                 f"| {money(h.pnl, True)} ({pct(h.pnl_pct)}) | {back} |")

    L += ["", "## How bad it has been",
          "Worst falls in the data window. For leveraged holdings, a daily-reset fund rebuilt from the "
          "underlying's closes (no fees) shows what the same stretch did at that leverage.", "",
          "| Underlying | Since | Worst fall | When | At your leverage | Worst 5 sessions |", "|---|---|---|---|---|---|"]
    for r in a.history:
        at = f"{pct(r.fund_dd)} at {r.pos.leverage:g}x" if r.fund_dd is not None else "n/a (1x)"
        L.append(f"| {r.pos.underlying} | {r.start} | {pct(r.und_dd)} | {r.und_dd_dates[0]} to {r.und_dd_dates[1]} "
                 f"| {at} | {pct(r.worst_week)} |")

    L += ["", "## Next week's ranges", "",
          "| Ticker | Last close | Weekly vol | 80% range | 95% range | Model |", "|---|---|---|---|---|---|"]
    for r in a.ranges:
        L.append(f"| {r.ticker} | {r.last:,.2f} | {r.fc.sd5:.2%} | {r.r80[0]:,.2f} to {r.r80[1]:,.2f} "
                 f"| {r.r95[0]:,.2f} to {r.r95[1]:,.2f} | {r.fc.method} |")
    L.append("\nThe models don't know about earnings dates: ranges run too narrow in a week with a report.")

    recs = [r for r in a.ranges if r.record]
    if recs:
        n = sum(r.record.weeks for r in recs)
        p80 = sum(r.record.in80 * r.record.weeks for r in recs) / n
        p95 = sum(r.record.in95 * r.record.weeks for r in recs) / n
        L += ["", "## Scorecard",
              "The same model replayed over recent weeks, each forecast made only with data from its own day. "
              "An honest 80% range holds about 80% of weeks; much less means the ranges run too narrow.", "",
              "| Ticker | Weeks | Inside 80% range | Inside 95% range | Last 95% miss |", "|---|---|---|---|---|"]
        for r in recs:
            L.append(f"| {r.ticker} | {r.record.weeks} | {r.record.in80:.0%} | {r.record.in95:.0%} "
                     f"| {r.record.last_miss or 'none'} |")
        L.append(f"| **All** | {n} | **{p80:.0%}** | **{p95:.0%}** | |")

    if brief:
        L += ["", "## News brief", brief]
    if news:
        L += ["", "## Headlines (last 48 hours)"]
        for t, items in news.items():
            if items:
                L.append(f"\n**{t}**")
                L += [f"- [{h.title}]({h.link}) ({h.source}, {h.published:%b %-d})" for h in items]

    L += ["", "---", "Numbers come from code, not a language model. Driftless lognormal odds from a calibrated "
          "variance forecast; leveraged funds modeled as daily-reset without fees. Informational only, not "
          "investment advice."]
    return "\n".join(L) + "\n"
