"""Optional: a short news brief from the headlines, written by Claude, checked before it is shown.

The model only ever sees headlines. It is told not to give prices, levels or advice, and its output is
rejected if it contains any number that isn't in those headlines. Every number in the report comes
from code. Needs `pip install anthropic` and an ANTHROPIC_API_KEY; without them the report skips it.
"""
from __future__ import annotations

import os
import re

from .news import Headline

MODEL = os.environ.get("DOWNSIDE_MODEL", "claude-opus-5-5")
SYSTEM = (
    "You summarize market headlines for someone who holds these stocks. Write 3 to 5 plain sentences on "
    "what the headlines say is moving these names and why. Use only what the headlines say. Do not give "
    "price targets, levels, forecasts or advice, and do not add numbers that are not in the headlines. "
    "If the headlines say nothing notable, say so in one sentence."
)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def unsupported_numbers(text: str, source: str) -> list[str]:
    """Numbers in text that don't appear anywhere in source (commas ignored)."""
    have = {n.replace(",", "") for n in NUMBER.findall(source)}
    return [n for n in NUMBER.findall(text) if n.replace(",", "") not in have]


def brief(news: dict[str, list[Headline]]) -> tuple[str | None, str]:
    """(brief or None, a one-line note on what happened)."""
    lines = [f"{h.ticker}: {h.title} ({h.source})" for items in news.values() for h in items]
    if not lines:
        return None, "no headlines"
    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None, "no ANTHROPIC_API_KEY"
    source = "\n".join(lines)
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[{"role": "user", "content": "Headlines:\n" + source}],
        )
    except anthropic.RateLimitError:
        return None, "rate limited"
    except anthropic.APIStatusError as e:
        return None, f"API error {e.status_code}"
    except anthropic.APIConnectionError:
        return None, "network error"
    if response.stop_reason == "refusal":
        return None, "model declined"
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        return None, "empty reply"
    bad = unsupported_numbers(text, source)
    if bad:
        return None, f"rejected: numbers not in the headlines ({', '.join(bad[:3])})"
    return text, "ok"
