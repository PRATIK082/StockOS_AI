"""Options view — merge the engine decision with the REAL Indian option chain.

The TradingAgents pipeline reasons about market data, news and fundamentals
but has no concept of listed options. This module closes that gap for the
Trading Desk: for NSE/BSE underlyings it pulls the live TradingView options
snapshot (bias, max pain, IV skew, ATM IV, premium P/C ratio — via
``OptionsSignalsService``) and builds:

- ``alignment`` — whether the engine's rating and the options-market bias
  point the same way (``aligned`` / ``divergent`` / ``neutral``);
- ``suggestion`` — a concrete, real-strike expression (CE around the ATM
  strike for a bullish read, PE for bearish, or a spread note) derived from
  actual chain strikes;
- a markdown ``note`` the UI renders next to the final decision.

Honest degradation: symbols with no chain (US stocks, indexes TradingView
does not list) return ``None`` and the UI simply omits the options section.
No synthetic data ever reaches this layer — only the real chain rows.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.data.service import market_data
from app.services.tradingagents.signal import TradingSignal

logger = get_logger("tradingagents.options")

# Exchanges whose underlyings carry an Indian options chain in TradingView.
_OPTIONS_EXCHANGES = {"NSE", "BSE", "NSEFO", "BSEFO"}


def _num(value: Any) -> float | None:
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _direction_from_rating(rating: str | None) -> str | None:
    """Map a 5-tier rating onto a plain market-side (None = neutral)."""
    rating = (rating or "").strip().title()
    if rating in ("Buy", "Overweight"):
        return "bullish"
    if rating in ("Underweight", "Sell"):
        return "bearish"
    return None


def _direction_from_bias(bias: str | None) -> str | None:
    if bias in ("CALL", "CALL+"):
        return "bullish"
    if bias in ("PUT", "PUT+"):
        return "bearish"
    return None


async def _signals(symbol: str, market_service=None) -> dict | None:
    from app.services.options.signals import OptionsSignalsService

    service = market_service or market_data
    try:
        return await OptionsSignalsService(market_service=service).signals(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.debug("options signals unavailable for %s: %s", symbol, exc)
        return None


async def _chain_strikes(symbol: str, expiry: str | None, market_service=None) -> list[float]:
    """Real strike ladder from the provider chain (best effort)."""
    service = market_service or market_data
    try:
        chain = await service.get_option_chain(symbol, expiry=expiry)
    except Exception as exc:  # noqa: BLE001
        logger.debug("option chain unavailable for %s: %s", symbol, exc)
        return []
    strikes: set[float] = set()
    for side in ("calls", "puts"):
        for row in chain.get(side, []) or []:
            k = _num(row.get("strike"))
            if k is not None:
                strikes.add(k)
    return sorted(strikes)


def _suggestion(spot: float, strikes: list[float], direction: str | None) -> dict[str, Any]:
    """Pick a concrete REAL strike expression for the given direction.

    Uses the listed strikes on each side of spot (no invented levels). For a
    bull/bear view it picks the ATM strike and the first listed OTM strike;
    for a neutral view it notes a defined-risk spread prefers no directional leg.
    """
    if not strikes:
        return {"leg": None, "strike": None, "otm_strike": None, "note": "No strikes listed."}
    atm = min(strikes, key=lambda k: abs(k - spot))
    index = strikes.index(atm)
    above = strikes[index + 1] if index + 1 < len(strikes) else None
    below = strikes[index - 1] if index > 0 else None

    if direction == "bullish":
        return {
            "leg": "call (CE)",
            "strike": atm,
            "otm_strike": above,
            "note": f"Buy/like the {atm} CE, or a bull call spread using {above or atm} as the short leg.",
        }
    if direction == "bearish":
        return {
            "leg": "put (PE)",
            "strike": atm,
            "otm_strike": below,
            "note": f"Buy/like the {atm} PE, or a bear put spread using {below or atm} as the short leg.",
        }
    return {
        "leg": "spread",
        "strike": atm,
        "otm_strike": None,
        "note": f"Neutral verdict — favour defined-risk spreads around {atm} rather than naked calls/puts.",
    }


def build_note(signal: TradingSignal | None, options: dict, suggestion: dict, alignment: str) -> str:
    """Plain markdown the UI can render next to the decision."""
    bias = options.get("bias")
    spot = _num(options.get("spot_price"))

    chunks: list[str] = []
    if spot is not None:
        chunks.append(f"The option chain prices spot at **{spot}**.")
    bits = [
        f"Options bias is **{bias or 'NEUTRAL'}**",
    ]
    if options.get("iv_skew") is not None:
        bits.append(f"IV skew **{options.get('iv_skew')}**")
    if options.get("atm_iv") is not None:
        bits.append(f"ATM IV **{options.get('atm_iv')}**")
    if options.get("premium_put_call") is not None:
        bits.append(f"premium put/call ratio **{options.get('premium_put_call')}**")
    if chunks:
        chunks[0] = chunks[0] + " " + ", ".join(bits) + "."
    else:
        chunks.append(", ".join(bits) + ".")

    if alignment == "aligned":
        chunks.append("The AI verdict and the options market agree on direction.")
    elif alignment == "divergent":
        chunks.append(
            "The AI verdict and the options market DISAGREE on direction — treat the view as in tension."
        )
    else:
        chunks.append("Options flow is mixed; the AI verdict is effectively neutral here.")

    note = suggestion.get("note")
    if note:
        chunks.append(note)
    return "\n\n".join(chunks)


async def build_options_view(
    symbol: str, signal: TradingSignal | None, market_service: Any | None = None
) -> dict[str, Any] | None:
    """Merge: real signals + real strikes + alignment + suggestion, else None."""
    exchange = symbol.split(":", 1)[0] if ":" in symbol else ""
    if exchange not in _OPTIONS_EXCHANGES:
        return None

    sig = await _signals(symbol, market_service)
    if not sig:
        return None
    spot = _num(sig.get("spot_price"))
    if not spot and sig.get("strategy") == "neutral":
        return None

    expiry = sig.get("expiry")
    strikes = await _chain_strikes(symbol, expiry, market_service)
    if not strikes:
        strikes = await _chain_strikes(symbol, None, market_service)

    direction = _direction_from_rating(signal.rating) if signal else None
    options_direction = _direction_from_bias(sig.get("bias"))

    if direction and options_direction:
        alignment = "aligned" if direction == options_direction else "divergent"
    else:
        alignment = "neutral"

    suggestion = _suggestion(spot, strikes, direction) if spot else {}

    return {
        "available": True,
        "expiry": expiry,
        "spot_price": spot,
        "max_pain": _num(sig.get("max_pain")),
        "iv_skew": _num(sig.get("iv_skew")),
        "atm_iv": _num(sig.get("atm_iv")),
        "avg_iv": _num(sig.get("avg_iv")),
        "premium_put_call": _num(sig.get("premium_put_call")),
        "bias": sig.get("bias"),
        "strategy": sig.get("strategy"),
        "recommendation": sig.get("recommendation"),
        "alignment": alignment,
        "suggestion": suggestion,
        "note": build_note(signal, sig, suggestion, alignment),
    }