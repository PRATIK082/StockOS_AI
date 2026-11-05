"""Per-symbol latest-news fetch for Vibe chat (S7-vibe). Keyless RSS only.

Verified working feeds (probed live, 2026-11-05):
- Yahoo Finance per-symbol RSS — works for US tickers (18 stories for AAPL);
  EMPTY for NSE tickers (200 + 0 entries for RELIANCE/.NS/IN variants), so it
  is tried first and skipped honestly when empty.
- Google News search RSS (``news.google.com/rss/search``) — 37 stories for a
  "Reliance Industries stock" query; primary source for Indian names.
- General market feeds filtered by symbol/company mention: Moneycontrol,
  ET Markets, LiveMint markets, Business Standard markets, Tickertape blog,
  ValueResearchOnline feed (all returned entries on probe).
- Zerodha Pulse has NO public RSS (``/feed`` and ``/rss`` both 404) and is
  therefore NOT fetched — documented here instead of failing silently.

No new dependencies (aiohttp + feedparser are already hard deps). Every
failure degrades to an honest per-source note — headlines are never
fabricated. Global kill-switch: ``STOCKOS_VIBE_NEWS=off``.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote_plus

import aiohttp
import feedparser

from app.core.logging import get_logger

logger = get_logger("vibe.news")

YAHOO_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
GNEWS_URL = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

# General market feeds — kept only when the symbol/company is mentioned.
GENERAL_FEEDS: dict[str, str] = {
    "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "ET Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "LiveMint": "https://www.livemint.com/rss/markets",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
    "Tickertape": "https://www.tickertape.in/blog/feed/",
    "ValueResearchOnline": "https://www.valueresearchonline.com/feed/",
}

_EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def news_enabled() -> bool:
    """Global kill-switch; default ON (user decision S7-vibe)."""
    return (os.environ.get("STOCKOS_VIBE_NEWS") or "on").strip().lower() not in {"off", "0", "no", "false"}


def yahoo_ticker(symbol: str) -> str:
    """Map EXCHANGE:TICKER to a Yahoo Finance ticker (NSE:X → X.NS …)."""
    sym = (symbol or "").strip().upper()
    if ":" in sym:
        ex, bare = sym.split(":", 1)
        return bare + _EXCHANGE_SUFFIX.get(ex, "")
    return sym


def clean_text(html: str, limit: int = 220) -> str:
    """Strip tags/entities from an RSS summary for prompt use."""
    text = _HTML_TAG_RE.sub(" ", html or "")
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def mention_tokens(symbol: str, company: str) -> set[str]:
    """Lowercase tokens that identify this symbol in a general-feed headline."""
    toks: set[str] = set()
    bare = (symbol or "").split(":")[-1].replace(".NS", "").replace(".BO", "")
    if len(bare) >= 3:
        toks.add(bare.lower())
    for word in re.split(r"[^a-z0-9]+", (company or "").lower()):
        if len(word) >= 4:
            toks.add(word)
    return toks


def _entry_to_item(entry: Any, source: str) -> dict[str, str]:
    return {
        "title": _WS_RE.sub(" ", entry.get("title", "") or "").strip()[:180],
        "url": entry.get("link", "") or "",
        "source": source,
        "published": entry.get("published", "") or "",
        "snippet": clean_text(entry.get("summary", "") or entry.get("description", "")),
    }


async def _fetch_text(session: aiohttp.ClientSession, url: str, timeout: int) -> str | None:
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"User-Agent": "Mozilla/5.0"},
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.text()
    except Exception as exc:  # noqa: BLE001 — one dead feed must not break news
        logger.debug("symbol-news fetch failed for %s: %s", url, exc)
        return None


async def fetch_symbol_news(
    symbol: str,
    company: str = "",
    *,
    limit: int = 8,
    per_feed_timeout: int = 8,
) -> dict[str, Any]:
    """Fetch latest headlines for one symbol.

    Returns ``{"items": [...], "notes": {source: status}}`` where each item is
    ``{title, url, source, published, snippet}``. Never raises for feed
    failures — they land in ``notes`` instead.
    """
    items: list[dict[str, str]] = []
    notes: dict[str, str] = {}
    company = company or symbol
    timeout = aiohttp.ClientTimeout(total=per_feed_timeout)

    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as session:
        # 1. Yahoo per-symbol feed (often empty for NSE tickers — honest skip).
        text = await _fetch_text(session, YAHOO_URL.format(ticker=yahoo_ticker(symbol)), per_feed_timeout)
        if text:
            entries = feedparser.parse(text).entries[:4]
            for entry in entries:
                item = _entry_to_item(entry, "Yahoo Finance")
                if item["title"]:
                    items.append(item)
            notes["Yahoo Finance"] = f"ok({len(entries)})" if entries else "empty"
        else:
            notes["Yahoo Finance"] = "failed"

        # 2. Google News by company name — the workhorse for Indian names.
        text = await _fetch_text(
            session, GNEWS_URL.format(query=quote_plus(f"{company} stock")), per_feed_timeout
        )
        if text:
            entries = feedparser.parse(text).entries[:4]
            for entry in entries:
                item = _entry_to_item(entry, entry.get("source", {}).get("title") or "Google News")
                if item["title"]:
                    items.append(item)
            notes["Google News"] = f"ok({len(entries)})" if entries else "empty"
        else:
            notes["Google News"] = "failed"

        # 3. General feeds, kept only on symbol/company mention.
        toks = mention_tokens(symbol, company)

        async def _general(source: str, url: str) -> tuple[str, list[dict[str, str]], str]:
            txt = await _fetch_text(session, url, per_feed_timeout)
            if not txt:
                return source, [], "failed"
            kept: list[dict[str, str]] = []
            for entry in feedparser.parse(txt).entries[:25]:
                hay = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
                if toks and any(t in hay for t in toks):
                    item = _entry_to_item(entry, source)
                    if item["title"]:
                        kept.append(item)
                    if len(kept) >= 2:
                        break
            return source, kept, f"ok({len(kept)})" if kept else "no-mention"

        import asyncio

        for source, kept, note in await asyncio.gather(
            *[_general(s, u) for s, u in GENERAL_FEEDS.items()]
        ):
            items.extend(kept)
            notes[source] = note

    return {"items": items[:limit], "notes": notes}
