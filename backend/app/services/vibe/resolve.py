"""Company-name → EXCHANGE:TICKER resolution for Vibe chat (S7-vibe).

The old detector (``app.services.agents.chat._detect_symbol``) only matches
literal ``EXCHANGE:TICKER`` tokens or ALL-CAPS words, so *"What is the outlook
for Reliance?"* resolved to nothing. This module layers company-name search on
top of the existing local stock database
(``app.services.data.universe_expanded.search_symbols`` — no network, no new
dependencies):

- explicit ``EXCHANGE:TICKER`` in the message still wins (handled first),
- otherwise candidate phrases (quoted text, Title-Case runs) are searched and
  scored: exact symbol > exact name > prefix > token-overlap, with an exchange
  hint boost (NSE/BSE/India → india, NYSE/NASDAQ/US → us),
- one strong match auto-resolves; several close matches return ``ambiguous``
  with up to 5 candidates so the UI can ask ("Did you mean …?") while the
  pipeline still analyses the top pick.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.agents.chat import _detect_symbol
from app.services.data.universe_expanded import search_symbols

# Bare exchange codes are never tradeable symbols on their own ("NSE" matched
# as an ALL-CAPS token must not short-circuit company-name search).
_EXCHANGE_CODES = frozenset({"NSE", "BSE", "NYSE", "NASDAQ", "AMEX", "NSEFO", "BSEFO"})

# Words that are never company names on their own.
_STOPWORDS = frozenset(
    """
    what how should is are was were do does did can could would will shall
    analyze analyse explain tell give show find get outlook technical view
    prediction forecast hold buy sell today tomorrow week month year stock
    stocks share shares market markets price target buyback dividend bonus
    split ipo nfo nav mf sip expect overbought oversold bullish bearish
    the a an of for on in to from with about vs versus and or
    """.split()
)

_QUOTED_RE = re.compile(r'"([^"]{2,60})"')
_TITLE_RUN_RE = re.compile(r"\b([A-Z][a-zA-Z&.\-]{1,30}(?:\s+[A-Z][a-zA-Z&.\-]{1,30}){0,3})\b")
_INDIA_HINT_RE = re.compile(r"\b(nse|bse|india|indian|sensex|nifty)\b", re.IGNORECASE)
_US_HINT_RE = re.compile(r"\b(nyse|nasdaq|nasdaq100|us stocks?|american|wall\s?street|s&p)\b", re.IGNORECASE)


@dataclass
class Resolution:
    """Outcome of resolving a chat message to a tradeable symbol."""

    symbol: str | None  # canonical EXCHANGE:TICKER top pick (unverified quote)
    candidates: list[dict] = field(default_factory=list)  # [{symbol, name, market}]
    method: str = "none"  # explicit | strong | ambiguous | none
    query: str = ""  # the phrase that produced the match
    company: str = ""  # display company name (for news queries)


def extract_phrases(message: str) -> list[str]:
    """Candidate company phrases: quoted text first, then Title-Case runs."""
    phrases: list[str] = []
    for m in _QUOTED_RE.finditer(message or ""):
        phrases.append(m.group(1).strip())
    for m in _TITLE_RUN_RE.finditer(message or ""):
        run = m.group(1).strip()
        words = [w for w in run.split() if w.lower() not in _STOPWORDS and len(w) > 1]
        if words:
            phrases.append(" ".join(words))
    # De-dupe preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out[:8]


def detect_market_hint(message: str) -> str | None:
    """Return 'india' | 'us' when the message names a market, else None."""
    text = message or ""
    if _INDIA_HINT_RE.search(text):
        return "india"
    if _US_HINT_RE.search(text):
        return "us"
    return None


def _score(symbol: str, name: str, market: str, query: str, hint: str | None) -> float:
    """Score one universe hit against a query phrase (higher = better)."""
    q = query.strip().lower()
    bare = symbol.split(":")[-1].upper()
    nm = (name or "").strip().lower()
    if not q or len(q) < 2:
        return 0.0
    score = 0.0
    if bare == q.upper():
        score = 100.0
    elif nm == q:
        score = 95.0
    elif len(q) >= 3 and bare.startswith(q.upper()):
        score = 70.0
    elif nm.startswith(q):
        score = 65.0
    else:
        qtokens = [t for t in re.split(r"[^a-z0-9]+", q) if len(t) >= 2 and t not in _STOPWORDS]
        ntokens = set(re.split(r"[^a-z0-9]+", nm))
        overlap = sum(1 for t in qtokens if t in ntokens)
        if qtokens and overlap == len(qtokens):
            score = 45.0 + 4.0 * overlap
        elif q in nm:
            score = 35.0
        elif q.upper() in bare:
            score = 25.0
        else:
            return 0.0
    if hint and market == hint:
        score += 15.0
    if symbol.endswith(".BO"):
        score -= 5.0  # prefer the NSE listing when both match
    elif ":NIFTY" in symbol or ":BANKNIFTY" in symbol or ":SENSEX" in symbol:
        score += 2.0
    return score


def resolve_company(message: str, *, limit: int = 5, ignore: str | None = None) -> Resolution:
    """Resolve a free-text message to a symbol via company-name search.

    Never touches the network — pure local-universe scoring. Quote
    verification happens later in the engine (``_resolve_symbol``).

    ``ignore`` skips one false-positive explicit token (e.g. a bare "HDFC"
    that matched no quote), and bare exchange codes ("NSE") are never treated
    as explicit symbols.
    """
    explicit = _detect_symbol(message or "")
    if explicit and explicit != (ignore or "") and explicit not in _EXCHANGE_CODES:
        return Resolution(symbol=explicit, candidates=[], method="explicit", query=explicit, company="")

    hint = detect_market_hint(message or "")
    best: dict[str, tuple[float, str, str, str, str]] = {}  # symbol -> (score, query, name, market, tiebreak)
    for phrase in extract_phrases(message):
        try:
            hits = search_symbols(phrase, limit=8)
        except Exception:  # noqa: BLE001 — universe must never break chat
            continue
        for info in hits:
            sym = info.symbol
            if ":" not in sym:
                continue  # canonical EXCHANGE:TICKER form only
            score = _score(sym, info.name, info.market, phrase, hint)
            if score <= 0:
                continue
            tiebreak = f"{len(sym.split(':')[-1]):03d}{sym}"
            prev = best.get(sym)
            key = (score, phrase, info.name, info.market, tiebreak)
            if prev is None or (score, tiebreak) > (prev[0], prev[4]):
                best[sym] = (score, phrase, info.name, info.market, tiebreak)

    if not best:
        return Resolution(symbol=None, method="none")

    ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[1][4]))
    (top_sym, (top_score, top_query, top_name, top_market, _)), *rest = ranked
    second_score = rest[0][1][0] if rest else 0.0
    candidates = [
        {"symbol": sym, "name": name, "market": market}
        for sym, (_, _, name, market, _) in ranked[:limit]
    ]
    if top_score >= 75.0 and (top_score - second_score) >= 15.0:
        method = "strong"
    elif len(ranked) == 1 and top_score >= 50.0:
        method = "strong"  # single credible match — auto-run it
    elif top_score >= 30.0:
        method = "ambiguous"  # top pick runs; UI offers the rest as chips
    else:
        return Resolution(symbol=None, method="none")
    return Resolution(
        symbol=top_sym,
        candidates=candidates,
        method=method,
        query=top_query,
        company=top_name or top_sym,
    )
