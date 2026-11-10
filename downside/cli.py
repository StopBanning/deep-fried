"""downside: build the report for a portfolio, write it to reports/, optionally push it.

  downside --portfolio portfolio.yaml            # fetch bars and news, write reports/<date>.md, print it
  downside --portfolio portfolio.yaml --no-fetch # reuse the cached bars
  downside --notify --quiet                      # CI: portfolio from PORTFOLIO_YAML, push, print nothing private
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import data, llm, news, notify, portfolio, report, risk


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="downside", description=__doc__.splitlines()[0])
    ap.add_argument("--portfolio", help="YAML file (default: the PORTFOLIO_YAML environment variable)")
    ap.add_argument("--no-fetch", action="store_true", help="reuse cached bars")
    ap.add_argument("--no-news", action="store_true", help="skip headlines")
    ap.add_argument("--brief", action="store_true", help="add a Claude-written news brief (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--notify", action="store_true", help="push to the channels configured in the environment")
    ap.add_argument("--quiet", action="store_true", help="don't print the report (use in public CI logs)")
    ap.add_argument("--cache", default="data/bars", help="bar cache folder")
    ap.add_argument("--out", default="reports", help="report folder")
    args = ap.parse_args(argv)

    def say(msg: str) -> None:
        print(msg, file=sys.stderr)

    try:
        pf = portfolio.load(args.portfolio)
        bars = data.load(pf.tickers(), Path(args.cache), fetch=not args.no_fetch)
    except (ValueError, data.DataError, OSError) as e:
        say(f"error: {e}")
        return 1

    analysis = risk.analyze(pf, bars)
    heads = None if args.no_news else news.for_tickers(pf.underlyings())
    text = None
    if args.brief and heads:
        text, note = llm.brief(heads)
        say(f"news brief: {note}")
    md = report.render(analysis, heads, text)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{analysis.as_of}.md"
    path.write_text(md)
    say(f"wrote {path}")
    if not args.quiet:
        print(md)
    if args.notify:
        for line in notify.send_all(report.summary(analysis), md, path.name,
                                    f"Deep Fried {analysis.as_of}") or ["no channels configured"]:
            say(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
