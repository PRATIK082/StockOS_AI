"""Options market signals derived from the REAL option chain.

Metrics computed from the live chain (per underlying, nearest expiry by default):
- premium put/call ratio (OI-based PCR is not available from the free TradingView
  feed, so the honest proxy is the theoretical-premium put/call ratio)
- IV skew (OTM puts vs OTM calls — the "fear gauge")
- max pain (pinning level using uniform OI weighting, since real OI is absent)
- ATM / average IV (whether premium is cheap or rich)
- directional bias + a plain-language strategy recommendation per option type.

Nothing here is fabricated: every field comes from the provider chain, and the
fields that need data the feed does not publish (OI/volume) degrade to null.
"""

from __future__ import annotations

from statistics import mean

from app.core.logging import get_logger
from app.services.data.service import MarketDataService, market_data

logger = get_logger("analysis.options_signals")


def _num(value) -> float | None:
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


class OptionsSignalsService:
    """Computes actionable call/put signals from a real options chain."""

    def __init__(self, market_service: MarketDataService | None = None):
        self.market_service = market_service or market_data

    async def signals(self, symbol: str, expiry: str | None = None) -> dict:
        chain = await self.market_service.get_option_chain(symbol, expiry=expiry)
        spot = _num(chain.get("spot_price"))
        calls = [r for r in chain.get("calls", []) if _num(r.get("strike")) is not None]
        puts = [r for r in chain.get("puts", []) if _num(r.get("strike")) is not None]
        expiries = chain.get("expiries") or []
        chosen = chain.get("expiry")

        if not calls and not puts:
            return {
                "symbol": symbol,
                "expiry": chosen,
                "spot_price": spot,
                "max_pain": None,
                "premium_put_call": None,
                "iv_skew": None,
                "atm_iv": None,
                "avg_iv": None,
                "bias": "NEUTRAL",
                "recommendation": "No option legs returned by the data provider.",
                "strategy": "neutral",
            }

        call_rows = [
            {"strike": _num(r["strike"]), "premium": _num(r.get("last")), "iv": _num(r.get("iv"))}
            for r in calls
        ]
        put_rows = [
            {"strike": _num(r["strike"]), "premium": _num(r.get("last")), "iv": _num(r.get("iv"))}
            for r in puts
        ]

        max_pain = self._max_pain(spot, call_rows, put_rows)

        call_premium = sum(r["premium"] for r in call_rows if r["premium"] is not None)
        put_premium = sum(r["premium"] for r in put_rows if r["premium"] is not None)
        premium_ratio = (put_premium / call_premium) if call_premium else None

        # IV metrics use only the liquid ±15% strike window; far-OTM rows carry
        # degenerate IV from the scanner and would skew the reading.
        def _in_window(r: dict) -> bool:
            if spot is None:
                return True
            return 0.85 * spot <= r["strike"] <= 1.15 * spot

        def _sane_iv(r: dict) -> bool:
            return r["iv"] is not None and 0 < r["iv"] <= 3.0

        # IV skew: avg IV of OTM puts (strike < spot) vs OTM calls (strike > spot)
        otm_put_iv = [
            r["iv"] for r in put_rows
            if _in_window(r) and _sane_iv(r) and spot is not None and r["strike"] < spot
        ]
        otm_call_iv = [
            r["iv"] for r in call_rows
            if _in_window(r) and _sane_iv(r) and spot is not None and r["strike"] > spot
        ]
        iv_skew = None
        if otm_put_iv and otm_call_iv:
            iv_skew = round(mean(otm_put_iv) - mean(otm_call_iv), 5)

        # ATM IV = nearest strike to spot
        atm_iv = None
        if spot is not None:
            liquid_calls = [r for r in call_rows if _in_window(r) and _sane_iv(r)]
            liquid_puts = [r for r in put_rows if _in_window(r) and _sane_iv(r)]
            atm_iv_call = min(liquid_calls, key=lambda r: abs(r["strike"] - spot), default=None)
            atm_iv_put = min(liquid_puts, key=lambda r: abs(r["strike"] - spot), default=None)
            atm_ivs = [r["iv"] for r in (atm_iv_call, atm_iv_put) if r is not None]
            if atm_ivs:
                atm_iv = round(mean(atm_ivs), 5)

        all_iv = [
            r["iv"] for r in call_rows + put_rows
            if _in_window(r) and _sane_iv(r)
        ]
        avg_iv = round(mean(all_iv), 5) if all_iv else None

        bias, strategy, recommendation = self._interpret(spot, max_pain, iv_skew, premium_ratio, chosen)

        return {
            "symbol": symbol,
            "expiry": chosen,
            "expiries": expiries,
            "spot_price": spot,
            "max_pain": max_pain,
            "premium_put_call": premium_ratio,
            "iv_skew": iv_skew,
            "atm_iv": atm_iv,
            "avg_iv": avg_iv,
            "bias": bias,
            "strategy": strategy,
            "recommendation": recommendation,
        }

    @staticmethod
    def _max_pain(spot: float | None, call_rows: list[dict], put_rows: list[dict]) -> float | None:
        """Max-pain level (uniform OI weighting — real OI is not in the free feed)."""
        strikes = sorted({r["strike"] for r in call_rows + put_rows})
        if not strikes:
            return None
        call_by_k = {r["strike"]: r for r in call_rows}
        put_by_k = {r["strike"]: r for r in put_rows}
        best_k, best_loss = None, None
        for k in strikes:
            loss = 0.0
            for c in call_rows:
                # call payout at expiry when spot = k
                if k > c["strike"]:
                    loss += k - c["strike"]
            for p in put_rows:
                if k < p["strike"]:
                    loss += p["strike"] - k
            if best_loss is None or loss < best_loss:
                best_loss, best_k = loss, k
        return best_k

    @staticmethod
    def _interpret(spot, max_pain, iv_skew, premium_ratio, expiry) -> tuple[str, str, str]:
        signals: list[str] = []

        pain_bias = 0
        if spot is not None and max_pain is not None and max_pain > 0:
            diff = (max_pain - spot) / spot
            pain_bias = 1 if diff > 0.01 else -1 if diff < -0.01 else 0

        skew_bias = 0
        if iv_skew is not None:
            skew_bias = 1 if iv_skew > 0.02 else -1 if iv_skew < -0.02 else 0  # + = put premium richer

        premium_bias = 0
        if premium_ratio is not None:
            premium_bias = 1 if premium_ratio > 1.1 else -1 if premium_ratio < 0.9 else 0

        # bias: PUT (bearish) when puts are richer / max pain below spot
        put_signals = sum(1 for b in (pain_bias, skew_bias, premium_bias) if b == 1)
        call_signals = sum(1 for b in (pain_bias, skew_bias, premium_bias) if b == -1)

        if put_signals >= 2:
            bias = "PUT"
            strategy = "bearish"
            recommendation = (
                f"Bearish skew for {expiry}: put premium is rich and max pain "
                f"({max_pain}) sits {'below' if max_pain is not None and spot is not None and max_pain < spot else 'near'} spot. "
                "Consider protective/positional PUT buys (PE) or writing OTM calls (CE) to collect premium. "
                "Avoid naked call buying — IV is inflated on the downside."
            )
        elif call_signals >= 2:
            bias = "CALL"
            strategy = "bullish"
            recommendation = (
                f"Bullish skew for {expiry}: call premium is rich, max pain "
                f"({max_pain}) sits above spot. Consider momentum CALL buys (CE) or "
                "selling OTM puts (PE) to collect premium. Watch for a pin toward max pain."
            )
        else:
            bias = "NEUTRAL"
            strategy = "rangebound"
            recommendation = (
                f"Balanced market for {expiry}: no strong call/put skew (max pain {max_pain}). "
                "Prefer spread strategies (bull call spread / bear put spread) and selling "
                "premium at the extremes. Avoid directional naked options."
            )
        return bias, strategy, recommendation


options_signals_service = OptionsSignalsService()
