"""Options analytics suite (Phase 6).

Pure-Python analytics over a **real** option chain.  Nothing in this module
fabricates market data: every function consumes a chain dictionary produced by
the market-data provider and degrades honestly (returns ``None`` / empty
lists) when the provider does not publish the required field (for example
open interest is not available on every free scanner).

The functions are intentionally side-effect free so they can be unit tested
with synthetic chains without touching the network.

Analyses implemented here (OpenAlgo-inspired, re-implemented in StockOS style):

* :func:`max_pain`            -- strike where option writers' payout is minimal.
* :func:`oi_profile`          -- open interest by strike + put/call ratio.
* :func:`oi_change_profile`   -- intraday OI change by strike (when published).
* :func:`iv_smile`            -- volatility smile/skew for one expiry.
* :func:`vol_surface`         -- IV matrix across expiries.
* :func:`gamma_exposure`      -- GEX by strike, zero-gamma and flip strikes.
* :func:`straddle_pnl`        -- PnL curve, breakevens and max profit/loss.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - scipy/numpy are hard deps of the project
    from scipy import stats as _stats
except Exception:  # pragma: no cover
    _stats = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- model

@dataclass
class Leg:
    """A single normalised option contract."""

    strike: float
    ltp: float = 0.0
    iv: float = 0.0
    oi: float = 0.0
    volume: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    oi_change: Optional[float] = None
    lot_size: int = 100
    option_type: str = "CE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strike": self.strike,
            "ltp": self.ltp,
            "iv": self.iv,
            "oi": self.oi,
            "volume": self.volume,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "bid": self.bid,
            "ask": self.ask,
            "oi_change": self.oi_change,
            "lot_size": self.lot_size,
            "option_type": self.option_type,
        }


@dataclass
class NormalizedChain:
    """Provider-agnostic option chain."""

    symbol: str
    spot: float = 0.0
    expiry: Optional[str] = None
    expiries: List[str] = field(default_factory=list)
    calls: List[Leg] = field(default_factory=list)
    puts: List[Leg] = field(default_factory=list)
    provider: Optional[str] = None

    @property
    def strikes(self) -> List[float]:
        return sorted({leg.strike for leg in self.calls} | {leg.strike for leg in self.puts})

    def call_at(self, strike: float) -> Optional[Leg]:
        return _closest(self.calls, strike)

    def put_at(self, strike: float) -> Optional[Leg]:
        return _closest(self.puts, strike)

    def atm_strike(self) -> Optional[float]:
        if not self.spot or not self.strikes:
            return None
        return min(self.strikes, key=lambda k: abs(k - self.spot))

    def total_oi(self) -> float:
        return sum(l.oi for l in self.calls) + sum(l.oi for l in self.puts)


def _closest(legs: Sequence[Leg], strike: float) -> Optional[Leg]:
    if not legs:
        return None
    return min(legs, key=lambda l: abs(l.strike - strike))


def _first_float(row: Dict[str, Any], *names: str) -> Optional[float]:
    for name in names:
        if name not in row:
            continue
        value = row.get(name)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_int(row: Dict[str, Any], *names: str, default: int = 100) -> int:
    for name in names:
        if name not in row:
            continue
        value = row.get(name)
        if value is None or value == "":
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return default


def normalize_leg(row: Dict[str, Any], option_type: str) -> Optional[Leg]:
    """Normalise a provider chain row into a :class:`Leg`.

    Returns ``None`` when the row carries no usable strike.
    """
    if not isinstance(row, dict):
        return None
    strike = _first_float(row, "strike", "Strike", "strike_price", "strikePrice")
    if strike is None:
        return None
    lot_size = _first_int(row, "lot_size", "lotSize", "lotsize", default=100)
    oi_change = _first_float(row, "oi_change", "change_oi", "oiChange", "changeinopeninterest")
    return Leg(
        strike=strike,
        ltp=_first_float(row, "ltp", "price", "last_price", "lastPrice", "close", "premium") or 0.0,
        iv=_first_float(row, "iv", "implied_volatility", "impliedVolatility", "iv_rank") or 0.0,
        oi=_first_float(row, "oi", "open_interest", "openInterest", "oi_value") or 0.0,
        volume=_first_float(row, "volume", "vol", "traded_volume") or 0.0,
        delta=_first_float(row, "delta", "delta_value") or 0.0,
        gamma=_first_float(row, "gamma", "gamma_value") or 0.0,
        theta=_first_float(row, "theta", "theta_value") or 0.0,
        vega=_first_float(row, "vega", "vega_value") or 0.0,
        bid=_first_float(row, "bid", "bid_price", "bidPrice") or 0.0,
        ask=_first_float(row, "ask", "ask_price", "askPrice") or 0.0,
        oi_change=oi_change,
        lot_size=lot_size,
        option_type="CE" if option_type.upper() in {"CE", "CALL", "C"} else "PE",
    )


def normalize_chain(chain: Dict[str, Any], symbol: str = "") -> NormalizedChain:
    """Normalise a provider option chain into :class:`NormalizedChain`."""
    chain = chain or {}
    calls: List[Leg] = []
    puts: List[Leg] = []
    for row in chain.get("calls") or []:
        leg = normalize_leg(row, "CE")
        if leg is not None:
            calls.append(leg)
    for row in chain.get("puts") or []:
        leg = normalize_leg(row, "PE")
        if leg is not None:
            puts.append(leg)

    spot = _first_float(chain, "spot_price", "spot", "underlying_price", "ltp") or 0.0
    expiry = chain.get("expiry")
    expiry_str = str(expiry)[:10] if expiry else None
    expiries = [str(e)[:10] for e in (chain.get("expiries") or []) if e]
    if expiry_str and expiry_str not in expiries:
        expiries.insert(0, expiry_str)

    return NormalizedChain(
        symbol=str(chain.get("symbol") or symbol or "").upper(),
        spot=spot,
        expiry=expiry_str,
        expiries=expiries,
        calls=sorted(calls, key=lambda l: l.strike),
        puts=sorted(puts, key=lambda l: l.strike),
        provider=chain.get("provider"),
    )


# --------------------------------------------------------------------------- max pain

def max_pain(chain: NormalizedChain) -> Optional[float]:
    """Strike at which option writers' total payout is minimal.

    Requires open interest on both sides; returns ``None`` when the provider
    does not publish OI.
    """
    strikes = chain.strikes
    if not strikes:
        return None
    if chain.total_oi() <= 0:
        return None

    best_strike: Optional[float] = None
    best_payout = math.inf
    for k in strikes:
        payout = 0.0
        for leg in chain.calls:
            payout += leg.oi * max(0.0, k - leg.strike)
        for leg in chain.puts:
            payout += leg.oi * max(0.0, leg.strike - k)
        if payout < best_payout:
            best_payout = payout
            best_strike = k
    return best_strike


# --------------------------------------------------------------------------- OI profile

def oi_profile(chain: NormalizedChain) -> Dict[str, Any]:
    """Open interest distribution by strike with put/call ratios."""
    strikes = chain.strikes
    rows: List[Dict[str, Any]] = []
    for k in strikes:
        call_oi = next((l.oi for l in chain.calls if l.strike == k), 0.0)
        put_oi = next((l.oi for l in chain.puts if l.strike == k), 0.0)
        rows.append({
            "strike": k,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "total_oi": call_oi + put_oi,
            "pcr": (put_oi / call_oi) if call_oi else None,
        })

    total_call = sum(r["call_oi"] for r in rows)
    total_put = sum(r["put_oi"] for r in rows)
    # Only report a "max OI strike" when that side actually carries open interest.
    # Picking the first strike of an all-zero side would be a fabricated level.
    call_rows = [r for r in rows if r["call_oi"] > 0]
    put_rows = [r for r in rows if r["put_oi"] > 0]
    max_call_strike = max(call_rows, key=lambda r: r["call_oi"])["strike"] if call_rows else None
    max_put_strike = max(put_rows, key=lambda r: r["put_oi"])["strike"] if put_rows else None

    return {
        "symbol": chain.symbol,
        "expiry": chain.expiry,
        "spot": chain.spot,
        "strikes": strikes,
        "rows": rows,
        "total_call_oi": total_call,
        "total_put_oi": total_put,
        "pcr": (total_put / total_call) if total_call else None,
        "max_call_oi_strike": max_call_strike,
        "max_put_oi_strike": max_put_strike,
        "support": max_put_strike,
        "resistance": max_call_strike,
        "has_oi": chain.total_oi() > 0,
    }


def oi_change_profile(chain: NormalizedChain) -> Dict[str, Any]:
    """Intraday OI change by strike (only when the provider publishes it)."""
    rows: List[Dict[str, Any]] = []
    available = False
    for k in chain.strikes:
        call_leg = next((l for l in chain.calls if l.strike == k), None)
        put_leg = next((l for l in chain.puts if l.strike == k), None)
        call_change = call_leg.oi_change if call_leg else None
        put_change = put_leg.oi_change if put_leg else None
        if call_change is not None or put_change is not None:
            available = True
        rows.append({
            "strike": k,
            "call_oi_change": call_change,
            "put_oi_change": put_change,
        })
    return {
        "symbol": chain.symbol,
        "expiry": chain.expiry,
        "rows": rows,
        "available": available,
        "note": None if available else "Provider does not publish open-interest change.",
    }


# --------------------------------------------------------------------------- IV smile

def _norm_cdf(x: float) -> float:
    if _stats is not None:
        return float(_stats.norm.cdf(x))
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta(spot: float, strike: float, t: float, vol: float, option_type: str) -> float:
    if spot <= 0 or strike <= 0 or t <= 0 or vol <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    if option_type == "CE":
        return _norm_cdf(d1)
    return _norm_cdf(d1) - 1.0


def _implied_gamma(spot: float, strike: float, t: float, vol: float) -> float:
    if spot <= 0 or strike <= 0 or t <= 0 or vol <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    if _stats is not None:
        pdf = float(_stats.norm.pdf(d1))
    else:
        pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return pdf / (spot * vol * math.sqrt(t))


def _time_to_expiry(expiry: Optional[str], reference: Optional[datetime] = None) -> float:
    if not expiry:
        return 0.0
    try:
        exp = datetime.fromisoformat(str(expiry)[:10])
    except ValueError:
        return 0.0
    now = reference or datetime.now()
    days = (exp - now).days
    return max(days, 0) / 365.0


def _leg_delta(leg: Leg, spot: float, t: float) -> float:
    if leg.delta:
        return leg.delta
    if not leg.iv or t <= 0:
        return 0.0
    return _bs_delta(spot, leg.strike, t, leg.iv, leg.option_type)


def _leg_gamma(leg: Leg, spot: float, t: float) -> float:
    if leg.gamma:
        return leg.gamma
    if not leg.iv or t <= 0:
        return 0.0
    return _implied_gamma(spot, leg.strike, t, leg.iv)


def iv_smile(chain: NormalizedChain) -> Dict[str, Any]:
    """Volatility smile for a single expiry.

    ``skew_25d`` is the 25-delta risk reversal (call IV minus put IV).  When the
    provider does not publish Greeks the 25-delta points are approximated with
    0.80x/1.20x ATM proxies and the result is flagged with
    ``delta_source="proxy"``.
    """
    t = _time_to_expiry(chain.expiry)
    points: List[Dict[str, Any]] = []
    for k in chain.strikes:
        call_leg = next((l for l in chain.calls if l.strike == k), None)
        put_leg = next((l for l in chain.puts if l.strike == k), None)
        call_iv = call_leg.iv if call_leg else 0.0
        put_iv = put_leg.iv if put_leg else 0.0
        points.append({
            "strike": k,
            "call_iv": call_iv,
            "put_iv": put_iv,
            "iv": (call_iv + put_iv) / 2.0 if (call_iv and put_iv) else (call_iv or put_iv),
            "call_delta": _leg_delta(call_leg, chain.spot, t) if call_leg else None,
            "put_delta": _leg_delta(put_leg, chain.spot, t) if put_leg else None,
        })

    atm_strike = chain.atm_strike()
    atm_point = next((p for p in points if p["strike"] == atm_strike), None)
    atm_iv = atm_point["iv"] if atm_point else None

    delta_source = "provider"
    call_25 = _find_by_delta(points, "call_delta", 0.25)
    put_25 = _find_by_delta(points, "put_delta", -0.25)
    if call_25 is None or put_25 is None:
        if t <= 0:
            # Expiry is today (or already past): there is no time value left, so
            # the 25-delta points are not meaningful.  Do not fabricate a proxy.
            delta_source = "unavailable"
            call_25 = None
            put_25 = None
        else:
            delta_source = "proxy"
            if atm_strike:
                call_25 = _iv_at_strike(points, atm_strike * 1.2)
                put_25 = _iv_at_strike(points, atm_strike * 0.8)

    skew = None
    if call_25 is not None and put_25 is not None and (call_25 + put_25) > 0:
        skew = (call_25 - put_25) * 100.0

    return {
        "symbol": chain.symbol,
        "expiry": chain.expiry,
        "spot": chain.spot,
        "atm_strike": atm_strike,
        "atm_iv": atm_iv,
        "atm_iv_pct": (atm_iv * 100.0) if atm_iv else None,
        "skew_25d": skew,
        "delta_source": delta_source,
        "points": points,
        "has_iv": any(p["iv"] for p in points),
        "note": (
            "Expiry is today or in the past - 25-delta skew is not computable."
            if delta_source == "unavailable"
            else None
        ),
    }


def _find_by_delta(points: Sequence[Dict[str, Any]], key: str, target: float) -> Optional[float]:
    best: Optional[float] = None
    best_dist = math.inf
    for p in points:
        value = p.get(key)
        if value is None:
            continue
        dist = abs(float(value) - target)
        if dist < best_dist:
            best_dist = dist
            best = p.get("iv") or 0.0
    if best is None or best_dist > 0.15:
        return None
    return best


def _iv_at_strike(points: Sequence[Dict[str, Any]], strike: float) -> Optional[float]:
    if not points:
        return None
    point = min(points, key=lambda p: abs(p["strike"] - strike))
    return point.get("iv") or None


def vol_surface(chains: Sequence[NormalizedChain]) -> Dict[str, Any]:
    """IV surface across expiries.

    ``chains`` holds one normalised chain per expiry.  The result contains a
    strike x expiry IV matrix plus the ATM term structure.
    """
    chains = [c for c in chains if c is not None]
    if not chains:
        return {"expiries": [], "strikes": [], "iv_matrix": [], "atm_term_structure": [], "has_iv": False}

    all_strikes = sorted({s for c in chains for s in c.strikes})
    expiries = [c.expiry for c in chains if c.expiry]

    matrix: List[List[Optional[float]]] = []
    for chain in chains:
        row: List[Optional[float]] = []
        for k in all_strikes:
            point = next((p for p in iv_smile(chain)["points"] if p["strike"] == k), None)
            value = point.get("iv") if point else None
            row.append(value if value else None)
        matrix.append(row)

    term: List[Dict[str, Any]] = []
    for chain in chains:
        smile = iv_smile(chain)
        term.append({
            "expiry": chain.expiry,
            "atm_strike": smile["atm_strike"],
            "atm_iv": smile["atm_iv"],
            "atm_iv_pct": smile["atm_iv_pct"],
            "skew_25d": smile["skew_25d"],
        })

    return {
        "symbol": chains[0].symbol,
        "expiries": expiries,
        "strikes": all_strikes,
        "iv_matrix": matrix,
        "atm_term_structure": term,
        "has_iv": any(v for row in matrix for v in row if v),
    }


# --------------------------------------------------------------------------- GEX

def gamma_exposure(chain: NormalizedChain) -> Dict[str, Any]:
    """Gamma exposure by strike, zero-gamma strike and flip point.

    Convention: a *dealer* that is long calls is short gamma, so call GEX is
    negative and put GEX is positive; the total is the net dealer gamma.
    Exposure uses the contract lot size published by the provider (default 100).
    """
    t = _time_to_expiry(chain.expiry)
    spot = chain.spot
    rows: List[Dict[str, Any]] = []
    for k in chain.strikes:
        call_leg = next((l for l in chain.calls if l.strike == k), None)
        put_leg = next((l for l in chain.puts if l.strike == k), None)

        call_gex = 0.0
        put_gex = 0.0
        if call_leg is not None:
            gamma = _leg_gamma(call_leg, spot, t)
            call_gex = -gamma * call_leg.oi * call_leg.lot_size * spot * spot * 0.01
        if put_leg is not None:
            gamma = _leg_gamma(put_leg, spot, t)
            put_gex = gamma * put_leg.oi * put_leg.lot_size * spot * spot * 0.01

        rows.append({
            "strike": k,
            "call_gex": call_gex,
            "put_gex": put_gex,
            "total_gex": call_gex + put_gex,
            "call_oi": call_leg.oi if call_leg else 0.0,
            "put_oi": put_leg.oi if put_leg else 0.0,
        })

    total_gex = sum(r["total_gex"] for r in rows)
    call_gex = sum(r["call_gex"] for r in rows)
    put_gex = sum(r["put_gex"] for r in rows)

    has_oi = chain.total_oi() > 0
    # Every derived level below is meaningless without open interest - do not
    # present a strike grid artefact as if it were a dealer-hedging level.
    zero_gamma = _zero_gamma_strike(rows) if has_oi else None
    flip = _flip_strike(rows, spot) if has_oi else None
    max_abs_gex_rows = [r for r in rows if abs(r["total_gex"]) > 0]

    return {
        "symbol": chain.symbol,
        "expiry": chain.expiry,
        "spot": spot,
        "rows": rows,
        "total_gex": total_gex,
        "call_gex": call_gex,
        "put_gex": put_gex,
        "zero_gamma_strike": zero_gamma,
        "flip_strike": flip,
        "max_abs_gex_strike": (
            max(max_abs_gex_rows, key=lambda r: abs(r["total_gex"]))["strike"]
            if max_abs_gex_rows
            else None
        ),
        "has_oi": has_oi,
        "note": None if has_oi else "Provider publishes no open interest - gamma exposure levels are unavailable.",
    }


def _zero_gamma_strike(rows: Sequence[Dict[str, Any]]) -> Optional[float]:
    cumulative = 0.0
    previous: Optional[float] = None
    for row in rows:
        cumulative += row["total_gex"]
        if previous is not None and previous == 0 and cumulative != 0:
            return row["strike"]
        if previous is not None and previous * cumulative < 0:
            return row["strike"]
        previous = cumulative
    return None


def _flip_strike(rows: Sequence[Dict[str, Any]], spot: float) -> Optional[float]:
    if not rows:
        return None
    above = [r for r in rows if r["strike"] <= spot]
    below = [r for r in rows if r["strike"] > spot]
    if not above or not below:
        return None
    return above[-1]["strike"]


# --------------------------------------------------------------------------- straddle

def straddle_pnl(
    chain: NormalizedChain,
    strike: Optional[float] = None,
    entry_premium: Optional[float] = None,
    position: str = "long",
    points: int = 41,
    price_range: float = 0.30,
) -> Dict[str, Any]:
    """PnL curve for a long/short straddle at a given strike.

    ``entry_premium`` defaults to the live ATM call + put premium.  The curve is
    evaluated on a synthetic price grid around spot using intrinsic value only
    (the option premium is held constant), which is the standard
    breakeven/ payoff presentation.
    """
    position = position.lower()
    if position not in {"long", "short"}:
        raise ValueError("position must be 'long' or 'short'")

    atm = chain.atm_strike()
    strike = float(strike) if strike is not None else atm
    if strike is None:
        raise ValueError("No strike available for the chain")

    call_leg = chain.call_at(strike)
    put_leg = chain.put_at(strike)

    if entry_premium is None:
        call_premium = call_leg.ltp if call_leg else 0.0
        put_premium = put_leg.ltp if put_leg else 0.0
        entry_premium = call_premium + put_premium
    entry_premium = float(entry_premium)
    # Some providers (and expired/illiquid chains) publish no premium at all.
    # A zero-premium "straddle" has no breakevens and an unbounded payoff, so
    # reporting it as if it were a real position would be misleading.
    has_premium = entry_premium > 0

    spot = chain.spot or strike
    low = max(spot * (1.0 - price_range), 0.01)
    high = spot * (1.0 + price_range)
    step = (high - low) / max(points - 1, 1)

    curve: List[Dict[str, Any]] = []
    for i in range(max(points, 2)):
        price = low + step * i
        intrinsic = abs(price - strike)
        if has_premium:
            pnl = (intrinsic - entry_premium) if position == "long" else (entry_premium - intrinsic)
        else:
            pnl = None
        curve.append({
            "price": round(price, 2),
            "intrinsic": round(intrinsic, 2),
            "pnl": round(pnl, 2) if pnl is not None else None,
        })

    if has_premium:
        breakevens = [strike - entry_premium, strike + entry_premium]
        pnl_values = [p["pnl"] for p in curve]
        max_profit = max(pnl_values)
        max_loss = min(pnl_values)
        max_profit_price = next((p["price"] for p in curve if p["pnl"] == max_profit), None)
        max_loss_price = next((p["price"] for p in curve if p["pnl"] == max_loss), None)
        note = "Payoff curve uses intrinsic value with a constant entry premium."
    else:
        breakevens = []
        max_profit = None
        max_loss = None
        max_profit_price = None
        max_loss_price = None
        note = (
            "This chain publishes no option premium, so entry cost, breakevens and "
            "max profit/loss are unavailable. Only expiry intrinsic value is shown."
        )

    return {
        "symbol": chain.symbol,
        "expiry": chain.expiry,
        "spot": spot,
        "strike": strike,
        "position": position,
        "entry_premium": round(entry_premium, 2),
        "has_premium": has_premium,
        "call_premium": round(call_leg.ltp, 2) if call_leg else None,
        "put_premium": round(put_leg.ltp, 2) if put_leg else None,
        "breakevens": [round(b, 2) for b in breakevens],
        "lower_breakeven": round(breakevens[0], 2) if breakevens else None,
        "upper_breakeven": round(breakevens[1], 2) if breakevens else None,
        "max_profit": round(max_profit, 2) if max_profit is not None else None,
        "max_loss": round(max_loss, 2) if max_loss is not None else None,
        "max_profit_price": max_profit_price,
        "max_loss_price": max_loss_price,
        "curve": curve,
        "note": note,
    }
