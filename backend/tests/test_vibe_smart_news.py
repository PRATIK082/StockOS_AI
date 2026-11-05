"""Tests for smart Vibe chat: company-name resolution, candidates, news stage.

Resolver + news-parser tests touch no network (local universe, canned RSS).
Engine tests inject a fake market plus a stubbed news fetch. Fakes are local
to this file — pytest does not put sibling test modules on sys.path.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

from app.services.news import symbol_news as news_mod  # noqa: E402
from app.services.vibe import engine as vibe_engine_mod  # noqa: E402
from app.services.vibe import resolve as resolve_mod  # noqa: E402


# --- resolver (pure, local universe) -------------------------------------------------

def test_resolve_reliance_is_strong_exact_ticker() -> None:
    # "Reliance" upper-cased IS the bare ticker RELIANCE → exact match.
    res = resolve_mod.resolve_company("What is the outlook for Reliance?")
    assert res.symbol == "NSE:RELIANCE"
    assert res.method == "strong"
    assert res.company == "Reliance Industries"


def test_resolve_full_name_is_strong() -> None:
    res = resolve_mod.resolve_company("Analyze Reliance Industries please")
    assert res.symbol == "NSE:RELIANCE"
    assert res.method == "strong"


def test_resolve_apple_single_match() -> None:
    res = resolve_mod.resolve_company("Should I hold Apple?")
    assert res.symbol == "NASDAQ:AAPL"
    assert res.method == "strong"


def test_resolve_hdfc_mixed_case_is_ambiguous() -> None:
    # Mixed case dodges the ALL-CAPS fast path → prefix matches on several
    # HDFC listings → ambiguous with candidates.
    res = resolve_mod.resolve_company("Tell me about Hdfc")
    assert res.symbol is not None
    assert res.method == "ambiguous"
    assert len(res.candidates) >= 2


def test_resolve_explicit_ticker_wins() -> None:
    res = resolve_mod.resolve_company("Analyze NSE:TCS vs NSE:INFY")
    assert res.symbol == "NSE:TCS"
    assert res.method == "explicit"


def test_resolve_bare_exchange_code_is_not_a_symbol() -> None:
    res = resolve_mod.resolve_company("Reliance on NSE")
    assert res.symbol == "NSE:RELIANCE"


def test_resolve_gibberish_is_none() -> None:
    res = resolve_mod.resolve_company("what is the weather like today")
    assert res.symbol is None
    assert res.method == "none"


def test_resolve_ignore_skips_false_explicit() -> None:
    res = resolve_mod.resolve_company("HDFC view?", ignore="HDFC")
    assert res.method == "ambiguous"
    assert res.symbol in {c["symbol"] for c in res.candidates}


# --- news helpers (no network) -------------------------------------------------------

def test_yahoo_ticker_mapping() -> None:
    assert news_mod.yahoo_ticker("NSE:RELIANCE") == "RELIANCE.NS"
    assert news_mod.yahoo_ticker("BSE:SENSEX") == "SENSEX.BO"
    assert news_mod.yahoo_ticker("NASDAQ:AAPL") == "AAPL"
    assert news_mod.yahoo_ticker("AAPL") == "AAPL"


def test_news_enabled_flag(monkeypatch) -> None:
    monkeypatch.delenv("STOCKOS_VIBE_NEWS", raising=False)
    assert news_mod.news_enabled() is True
    monkeypatch.setenv("STOCKOS_VIBE_NEWS", "off")
    assert news_mod.news_enabled() is False


_YAHOO_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Yahoo</title>
<item><title>Reliance posts record profit</title><link>https://example.com/1</link>
<pubDate>Mon, 03 Nov 2026 09:00:00 +0000</pubDate><description>Profit jumps 20%.</description></item>
<item><title>Unrelated market note</title><link>https://example.com/2</link>
<pubDate>Mon, 03 Nov 2026 08:00:00 +0000</pubDate><description>General movers.</description></item>
</channel></rss>"""

_GNEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>Reliance Industries hits 52-week high</title><link>https://example.com/3</link>
<pubDate>Mon, 03 Nov 2026 07:00:00 +0000</pubDate><description>Shares rally.</description></item>
</channel></rss>"""

_GENERAL_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>MC</title>
<item><title>Reliance Industries hits 52-week high</title><link>https://example.com/3</link>
<pubDate>Mon, 03 Nov 2026 07:00:00 +0000</pubDate><description>Shares rally.</description></item>
<item><title>Cricket scores update</title><link>https://example.com/4</link>
<pubDate>Mon, 03 Nov 2026 06:00:00 +0000</pubDate><description>Sports.</description></item>
</channel></rss>"""


def test_fetch_symbol_news_canned(monkeypatch) -> None:
    import asyncio

    async def _fake_fetch(session, url, timeout):
        if "feeds.finance.yahoo" in url:
            return _YAHOO_RSS
        if "news.google.com" in url:
            return _GNEWS_RSS
        return _GENERAL_RSS

    monkeypatch.setattr(news_mod, "_fetch_text", _fake_fetch)
    out = asyncio.run(news_mod.fetch_symbol_news("NSE:RELIANCE", "Reliance Industries", limit=8))
    assert out["items"], "expected headlines from canned feeds"
    assert all(i["title"] and i["url"] and i["source"] for i in out["items"])
    # Mention filter must drop the cricket item from general feeds.
    assert not any("Cricket" in i["title"] for i in out["items"])
    assert "Yahoo Finance" in out["notes"]
    assert "Google News" in out["notes"]
    assert len(out["items"]) <= 8


def test_fetch_symbol_news_all_dead(monkeypatch) -> None:
    import asyncio

    async def _dead(session, url, timeout):
        return None

    monkeypatch.setattr(news_mod, "_fetch_text", _dead)
    out = asyncio.run(news_mod.fetch_symbol_news("NSE:RELIANCE", "Reliance Industries"))
    assert out["items"] == []
    assert all(v == "failed" for v in out["notes"].values())


# --- engine integration (fake market + stubbed news) ---------------------------------

def _fake_candles(n: int = 60, base: float = 100.0) -> list[dict]:
    import numpy as np

    rng = np.random.default_rng(7)
    closes = base * np.cumprod(1 + rng.normal(0.0003, 0.015, n))
    return [
        {"ts": f"2025-01-{i % 28 + 1:02d}T00:00:00", "open": float(c),
         "high": float(c * 1.01), "low": float(c * 0.99), "close": float(c),
         "volume": 1_000_000}
        for i, c in enumerate(closes)
    ]


class _FakeMarket:
    async def get_quote(self, symbol: str, provider: str | None = None) -> dict:
        if symbol == "NSE:BOGUS":
            return {}
        return {"symbol": symbol, "price": 123.45, "day_change_pct": 0.012,
                "currency": "INR", "provider": "yahoo"}

    async def get_history_auto(self, symbol: str, *, interval: str = "1d", period: str = "3mo") -> dict:
        return {"symbol": symbol, "interval": interval, "period": period, "candles": _fake_candles()}

    async def get_option_chain(self, symbol: str, *, expiry: str | None = None) -> dict:
        return {"symbol": symbol, "spot_price": 123.45, "calls": [], "puts": []}


class _StrictMarket(_FakeMarket):
    """Fails bare junk tickers like the real service (FakeMarket passes all)."""

    async def get_quote(self, symbol: str, provider: str | None = None) -> dict:
        if symbol in {"HDFC", "NSE:HDFC", "NYSE:HDFC"}:
            return {}
        return await super().get_quote(symbol, provider=provider)


class _FakeSignals:
    async def signals(self, symbol: str) -> dict:
        return {"bias": "CALL", "strategy": "call", "max_pain": 122.0,
                "atm_iv": 0.19, "spot_price": 123.45, "expiry": "2026-08-25"}


def _engine(monkeypatch, market=None):
    async def _chat(messages, **kwargs):
        return "**Verdict** — constructive."

    async def _news(symbol, company="", **kwargs):
        return {
            "items": [
                {"title": "Reliance posts record profit", "url": "https://example.com/1",
                 "source": "Yahoo Finance", "published": "today", "snippet": "Profit jumps."},
                {"title": "Reliance hits high", "url": "https://example.com/3",
                 "source": "Moneycontrol", "published": "today", "snippet": "Rally."},
            ],
            "notes": {"Yahoo Finance": "ok(1)"},
        }

    monkeypatch.setattr(vibe_engine_mod, "gateway", type("G", (), {"chat": _chat})())
    monkeypatch.setattr(vibe_engine_mod.symbol_news, "fetch_symbol_news", _news)
    return vibe_engine_mod.VibeChatEngine(
        market_service=market or _FakeMarket(), prediction=None, signals=_FakeSignals()
    )


def _run(eng, message, **kwargs):
    import asyncio

    async def _collect():
        return [ev async for ev in eng.stream(message, provider="ollama", **kwargs)]

    return asyncio.run(_collect())


def test_company_name_runs_full_pipeline(monkeypatch) -> None:
    eng = _engine(monkeypatch)
    evs = _run(eng, "What is the outlook for Reliance Industries?")
    assert evs[0]["type"] == "plan"
    assert [p["key"] for p in evs[0]["plan"]] == [
        "symbol", "quote", "technical", "options", "prediction", "news", "answer",
    ]
    symbol_stage = next(ev for ev in evs if ev.get("type") == "stage" and ev["key"] == "symbol")
    assert symbol_stage["status"] == "done"
    assert symbol_stage["data"]["symbol"] == "NSE:RELIANCE"
    assert symbol_stage["data"]["method"] == "strong"
    assert not [ev for ev in evs if ev.get("type") == "candidates"]
    news_stage = next(ev for ev in evs if ev.get("type") == "stage" and ev["key"] == "news")
    assert news_stage["status"] == "done"
    assert len(news_stage["data"]["items"]) == 2
    answer = next(ev for ev in evs if ev.get("type") == "answer")
    assert answer["data"]["symbol"] == "NSE:RELIANCE"
    assert any(s.startswith("news:") for s in answer["data"]["sources"])


def test_bare_caps_falls_back_to_name_search(monkeypatch) -> None:
    # "HDFC" matches no quote as a bare ticker → company search → candidates.
    # Equal-score HDFC listings break ties deterministically; the UI chips
    # carry the rest, so assert family membership, not one exact pick.
    eng = _engine(monkeypatch, market=_StrictMarket())
    evs = _run(eng, "Tell me about HDFC")
    symbol_stage = next(ev for ev in evs if ev.get("type") == "stage" and ev["key"] == "symbol")
    assert symbol_stage["status"] == "done"
    assert symbol_stage["data"]["symbol"] in {"NSE:HDFCBANK", "NSE:HDFCLIFE", "NSE:HDFCAMC"}
    cand = next(ev for ev in evs if ev.get("type") == "candidates")
    assert cand["data"]["picked"] == symbol_stage["data"]["symbol"]
    assert len(cand["data"]["candidates"]) >= 2


def test_explicit_ticker_has_no_candidates(monkeypatch) -> None:
    eng = _engine(monkeypatch)
    evs = _run(eng, "Analyze NSE:RELIANCE")
    symbol_stage = next(ev for ev in evs if ev.get("type") == "stage" and ev["key"] == "symbol")
    assert symbol_stage["data"]["method"] == "explicit"
    assert not [ev for ev in evs if ev.get("type") == "candidates"]


def test_news_flag_off_skips_fetch(monkeypatch) -> None:
    eng = _engine(monkeypatch)
    calls: list = []

    async def _counting(symbol, company="", **kwargs):
        calls.append(symbol)
        return {"items": [], "notes": {}}

    monkeypatch.setattr(vibe_engine_mod.symbol_news, "fetch_symbol_news", _counting)
    evs = _run(eng, "Analyze NSE:RELIANCE", news=False)
    news_stage = next(ev for ev in evs if ev.get("type") == "stage" and ev["key"] == "news")
    assert news_stage["status"] == "skipped"
    assert calls == []
    answer = next(ev for ev in evs if ev.get("type") == "answer")
    assert not [s for s in answer["data"]["sources"] if s.startswith("news:")]


def test_news_env_off_skips_fetch(monkeypatch) -> None:
    eng = _engine(monkeypatch)
    monkeypatch.setenv("STOCKOS_VIBE_NEWS", "off")
    evs = _run(eng, "Analyze NSE:RELIANCE")
    news_stage = next(ev for ev in evs if ev.get("type") == "stage" and ev["key"] == "news")
    assert news_stage["status"] == "skipped"
    assert "off" in news_stage["data"]["note"]
