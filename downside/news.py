"""Recent headlines per ticker from Google News RSS (no API key). Headlines and links only: no scraping."""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .data import AGENT

RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
# Filing-bot and quote-page titles that carry no news.
JUNK = re.compile(r"shares (?:of .+ )?(?:bought|acquired|sold|purchased) by|stake in .+ (?:by|raised|lowered|cut)"
                  r"|\b(?:call|put) \([A-Z0-9]+\)|stock price, news, quote|interactive stock chart"
                  r"|how much \$\d+ invested", re.I)


@dataclass
class Headline:
    ticker: str
    title: str
    source: str
    link: str
    published: datetime


def headlines(ticker: str, hours: int = 48, limit: int = 4) -> list[Headline]:
    url = RSS.format(q=urllib.parse.quote(f"{ticker} stock when:{max(1, hours // 24)}d"))
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            root = ET.fromstring(r.read())
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out, seen = [], set()
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        key = title.lower()[:80]
        if when < cutoff or key in seen or JUNK.search(title):
            continue
        seen.add(key)
        out.append(Headline(ticker, title, source, item.findtext("link") or "", when))
    out.sort(key=lambda h: h.published, reverse=True)
    return out[:limit]


def for_tickers(tickers: list[str], hours: int = 48, limit: int = 4) -> dict[str, list[Headline]]:
    out = {}
    for i, t in enumerate(tickers):
        if i:
            time.sleep(0.5)
        out[t] = headlines(t, hours, limit)
    return out
