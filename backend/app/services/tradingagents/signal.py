"""Normalised trading signal from a Portfolio Manager decision.

The engine's final decision is a markdown document (``**Rating**: ...``,
``**Executive Summary**: ...``, ``**Investment Thesis**: ...``, optional
``**Price Target**`` / ``**Time Horizon**`` — see
``tradingagents.agents.schemas.render_pm_decision``). This module parses that
document into a machine-readable ``TradingSignal`` used by the Trading Desk
UI, the options merge layer and the simulate actions — without a second LLM
call.

Everything here is deterministic, derived from the real decision text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical 5-tier scale (most-to-least bullish), same as the vendored rating.
RATINGS_5_TIER: tuple[str, ...] = ("Buy", "Overweight", "Hold", "Underweight", "Sell")

# Direction mapping: which side a rating implies.
_RATING_DIRECTION = {
    "Buy": "long",
    "Overweight": "long",
    "Hold": "hold",
    "Underweight": "short",
    "Sell": "short",
}

# Deterministic conviction heuristic: how decisive a rating is.
_CONVICTION_BASE = {
    "Buy": 0.80,
    "Overweight": 0.65,
    "Hold": 0.50,
    "Underweight": 0.65,
    "Sell": 0.80,
}

_RATING_RE = re.compile(r"^\*\*Rating\s*\*\*\s*[:：]\s*(.+)$", re.IGNORECASE)
_KEY_RE = re.compile(r"^\*\*(?P<key>[A-Za-z\s]+?)\s*\*\*\s*[:：]\s*(?P<value>.*)$")

_KNOWN_KEYS = {
    "Executive Summary",
    "Investment Thesis",
    "Price Target",
    "Time Horizon",
}


@dataclass
class TradingSignal:
    """Structured reading of one Portfolio Manager decision."""

    rating: str = "Hold"
    action: str = "Hold"
    direction: str = "hold"
    conviction: float = 0.5
    confidence: float = 0.5
    price_target: float | None = None
    time_horizon: str | None = None
    executive_summary: str = ""
    investment_thesis: str = ""
    raw: str = ""
    parse_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rating": self.rating,
            "action": self.action,
            "direction": self.direction,
            "conviction": self.conviction,
            "confidence": self.confidence,
            "price_target": self.price_target,
            "time_horizon": self.time_horizon,
            "executive_summary": self.executive_summary,
            "investment_thesis": self.investment_thesis,
        }


def _parse_price_target(value: str) -> float | None:
    text = value.strip()
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_trading_signal(final_decision: str, rating_hint: str | None = None) -> TradingSignal:
    """Parse the final decision markdown into a ``TradingSignal``.

    ``rating_hint`` is the 5-tier rating the engine already extracted via the
    vendored ``SignalProcessor`` (``parse_rating``); when absent it is derived
    again from the text so the two readings can never disagree.
    """
    signal = TradingSignal(raw=final_decision or "")
    text = final_decision or ""

    rating: str = ""
    fields: dict[str, str] = {}

    for line in text.splitlines():
        stripped = line.strip().strip("*").strip()
        if not rating:
            m = _RATING_RE.search(line)
            if m:
                candidate = m.group(1).strip().strip("*").strip()
                if candidate in RATINGS_5_TIER:
                    rating = candidate
                    continue
        m = _KEY_RE.match(line.strip())
        if m:
            key = m.group("key").strip()
            if key in _KNOWN_KEYS:
                fields[key] = m.group("value").strip()
                continue

    if not rating:
        for tier in RATINGS_5_TIER:
            if re.search(rf"\b{tier}\b", text, re.IGNORECASE):
                rating = tier
                break
    if not rating:
        rating = rating_hint if rating_hint in RATINGS_5_TIER else "Hold"
        signal.parse_notes.append("Rating inferred from engine hint (bare text missing it).")
    elif rating_hint and rating_hint in RATINGS_5_TIER and rating != rating_hint:
        signal.parse_notes.append(
            f"Engine hint '{rating_hint}' differs from parsed '{rating}'; parsed wins."
        )

    price_target = _parse_price_target(fields.get("Price Target", ""))
    if "Price Target" in fields and price_target is None:
        signal.parse_notes.append("Price Target present but unparseable; omitted.")

    base = _CONVICTION_BASE.get(rating, 0.5)
    conviction = min(1.0, base + (0.05 if price_target is not None else 0.0))

    signal.rating = rating
    signal.action = rating.upper()
    signal.direction = _RATING_DIRECTION.get(rating, "hold")
    signal.price_target = price_target
    signal.time_horizon = fields.get("Time Horizon") or None
    signal.executive_summary = fields.get("Executive Summary", "")
    signal.investment_thesis = fields.get("Investment Thesis", "")
    signal.conviction = conviction
    signal.confidence = conviction
    return signal