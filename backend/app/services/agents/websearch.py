"""Web search for the agent runtime (P5-c, opt-in).

Flag: ``STOCKOS_AGENT_WEBSEARCH`` — ``off`` (default) or ``duckduckgo``.

DuckDuckGo needs no API key and no new dependency (uses ``httpx``, already
required). The lite-HTML parser is intentionally tolerant: several patterns
are tried and an unrecognized layout yields an honest empty result with a
note — never fabricated snippets.
"""

from __future__ import annotations

import html as html_lib
import os
import re
from dataclasses import asdict, dataclass

from app.core.logging import get_logger

logger = get_logger("agent.websearch")

TIMEOUT_S = 10.0
MAX_RESULTS = 5
QUERY_CAP = 300

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockOS/1.0"}

# <a rel="nofollow" href="URL">Title</a> ... <td class="result-snippet">Snippet</td>
_LINK_RE = re.compile(
    r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)
_SNIPPET_RE = re.compile(
    r'class="result-snippet"[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")


class WebSearchDisabledError(RuntimeError):
    pass


def websearch_backend() -> str:
    return (os.environ.get("STOCKOS_AGENT_WEBSEARCH") or "off").strip().lower()


def websearch_enabled() -> bool:
    return websearch_backend() == "duckduckgo"


@dataclass
class WebHit:
    title: str
    url: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(raw: str) -> str:
    return html_lib.unescape(_TAG_RE.sub("", raw)).strip()


def parse_lite_html(page: str) -> list[WebHit]:
    """Parse DDG lite HTML into hits. Unknown layout -> [] (never fabricated)."""
    hits: list[WebHit] = []
    links = list(_LINK_RE.finditer(page))
    snippets = [_clean(s) for s in _SNIPPET_RE.findall(page)]
    # Snippets align positionally with links in the lite layout; if counts
    # mismatch, keep links with empty snippets rather than misassigning.
    aligned = len(snippets) == len(links)
    for i, m in enumerate(links):
        url, title = m.group(1).strip(), _clean(m.group(2))
        if not url.startswith("http") or "duckduckgo.com" in url or not title:
            continue
        snippet = snippets[i] if (aligned and i < len(snippets)) else ""
        hits.append(WebHit(title=title[:200], url=url[:500], snippet=snippet[:500]))
        if len(hits) >= MAX_RESULTS:
            break
    return hits


def search(query: str) -> dict:
    """Live DDG search. Raises WebSearchDisabledError / RuntimeError (honest)."""
    if not websearch_enabled():
        raise WebSearchDisabledError(
            "Web search is disabled. Set STOCKOS_AGENT_WEBSEARCH=duckduckgo to enable."
        )
    query = (query or "").strip()[:QUERY_CAP]
    if not query:
        raise ValueError("query must be non-empty.")
    import httpx  # local import: keeps module importable without httpx in theory

    try:
        resp = httpx.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            headers=_UA,
            timeout=TIMEOUT_S,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - surfaced honestly to caller
        raise RuntimeError(f"Web search request failed: {exc}") from exc
    hits = parse_lite_html(resp.text)
    note = ""
    if not hits:
        note = "No parseable results (layout changed or no results). Try rephrasing."
    return {"query": query, "results": [h.to_dict() for h in hits], "note": note}
