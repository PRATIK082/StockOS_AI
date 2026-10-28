"""Margin calculator and synthetic futures (Phase 6).

The numbers produced here are **estimates** built from a transparent leverage
table (the same shape Indian brokers publish in their margin schedules) and
are clearly labelled as such in the API response.  They are meant for
pre-trade planning and for the paper broker's sandbox accounting - not as a
substitute for the broker's own margin statement.

Two entry points:

* :func:`calculate_margin` -- required margin for an equity / futures / options /
  currency order.
* :func:`synthetic_futures` -- cost, breakeven and margin of a synthetic
  futures position built from a call + a put at the same strike.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Leverage used to convert turnover into an initial-margin requirement.
# CNC (delivery) equity is fully funded, hence a 1.0 "leverage".
DEFAULT_LEVERAGE: Dict[str, Dict[str, float]] = {
    "equity": {"MIS": 5.0, "CNC": 1.0, "NRML": 1.0},
    "futures": {"MIS": 12.5, "NRML": 5.0},
    "options": {"MIS": 1.0, "NRML": 1.0},
    "currency": {"MIS": 1.0, "NRML": 1.0},
}

# Share of the total margin treated as SPAN margin (the rest is exposure).
SPAN_SHARE = 0.40

# Worst-case intraday move used to size the exposure margin of a short option.
SHORT_OPTION_EXPOSURE_PCT = 0.125

SEGMENTS = ("equity", "futures", "options", "currency")
PRODUCTS = ("MIS", "CNC", "NRML")


@dataclass
class MarginResult:
    symbol: str
    segment: str
    side: str
    product: str
    quantity: float
    price: float
    turnover: float
    span_margin: float
    exposure_margin: float
    total_margin: float
    margin_pct: float
    leverage: float
    available_margin: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        blocked = self.total_margin
        return {
            "symbol": self.symbol,
            "segment": self.segment,
            "side": self.side,
            "product": self.product,
            "quantity": self.quantity,
            "price": self.price,
            "turnover": round(self.turnover, 2),
            "span_margin": round(self.span_margin, 2),
            "exposure_margin": round(self.exposure_margin, 2),
            "total_margin": round(blocked, 2),
            "margin_pct": round(self.margin_pct, 2),
            "leverage": self.leverage,
            "available_margin": self.available_margin,
            "blocked_margin": round(blocked, 2),
            "remaining_after_trade": (
                round(self.available_margin - blocked, 2)
                if self.available_margin is not None
                else None
            ),
            "notes": self.notes,
            "is_estimate": True,
        }


def _leverage(segment: str, product: str) -> float:
    table = DEFAULT_LEVERAGE.get(segment) or DEFAULT_LEVERAGE["equity"]
    return float(table.get(product, 1.0))


def calculate_margin(
    symbol: str,
    side: str = "BUY",
    quantity: float = 0,
    price: float = 0,
    segment: str = "equity",
    product: str = "MIS",
    lot_size: int = 1,
    available_margin: Optional[float] = None,
    leverage_table: Optional[Dict[str, Dict[str, float]]] = None,
) -> MarginResult:
    """Estimate the margin required for an order.

    ``quantity`` is in *contracts* for futures/options and in *shares* for
    equity.  For futures and options the price is the contract price and the
    lot size is applied automatically.
    """
    segment = (segment or "equity").lower()
    if segment not in SEGMENTS:
        raise ValueError(f"Unknown segment '{segment}'. Use one of {list(SEGMENTS)}")
    product = (product or "MIS").upper()
    if product not in PRODUCTS:
        raise ValueError(f"Unknown product '{product}'. Use one of {list(PRODUCTS)}")
    side = (side or "BUY").upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    quantity = float(quantity or 0)
    price = float(price or 0)
    lot_size = int(lot_size or 1)
    if quantity <= 0:
        raise ValueError("quantity must be greater than 0")
    if price <= 0:
        raise ValueError("price must be greater than 0")

    notes: List[str] = []
    table = leverage_table or DEFAULT_LEVERAGE
    leverage = float((table.get(segment) or {}).get(product, 1.0))

    if segment == "equity":
        turnover = price * quantity
        if product == "CNC":
            total = turnover
            notes.append("Delivery (CNC) orders are fully funded: 100% of turnover is blocked.")
        else:
            total = turnover / leverage
            notes.append(f"Intraday equity margin estimated at {leverage}x leverage.")
        span = total * SPAN_SHARE
        exposure = total - span
    elif segment == "futures":
        notional = price * lot_size * quantity
        turnover = notional
        total = notional / leverage
        notes.append(f"F&O futures margin estimated at {leverage}x leverage of notional.")
        notes.append("Notional includes the contract lot size.")
        span = total * SPAN_SHARE
        exposure = total - span
    elif segment == "options":
        premium = price * lot_size * quantity
        turnover = premium
        if side == "BUY":
            total = premium
            notes.append("Long option: the full premium is blocked.")
            span = 0.0
            exposure = total
        else:
            exposure = price * lot_size * quantity * SHORT_OPTION_EXPOSURE_PCT
            total = premium + exposure
            notes.append(
                "Short option: premium is blocked plus an exposure margin sized at "
                f"{SHORT_OPTION_EXPOSURE_PCT:.1%} of the contract value."
            )
            span = premium
    else:  # currency
        notional = price * lot_size * quantity
        turnover = notional
        total = notional / leverage
        notes.append(f"Currency futures margin estimated at {leverage}x leverage of notional.")
        span = total * SPAN_SHARE
        exposure = total - span

    return MarginResult(
        symbol=str(symbol or "").upper(),
        segment=segment,
        side=side,
        product=product,
        quantity=quantity,
        price=price,
        turnover=turnover,
        span_margin=span,
        exposure_margin=exposure,
        total_margin=total,
        margin_pct=(total / turnover * 100.0) if turnover else 0.0,
        leverage=leverage,
        available_margin=available_margin,
        notes=notes,
    )


@dataclass
class SyntheticFutures:
    symbol: str
    direction: str
    strike: float
    lot_size: int
    quantity: float
    call_premium: float
    put_premium: float
    cost: float
    effective_price: float
    breakeven: float
    total_margin: float
    span_margin: float
    exposure_margin: float
    legs: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "strike": self.strike,
            "lot_size": self.lot_size,
            "quantity": self.quantity,
            "call_premium": round(self.call_premium, 2),
            "put_premium": round(self.put_premium, 2),
            "cost": round(self.cost, 2),
            "effective_price": round(self.effective_price, 2),
            "breakeven": round(self.breakeven, 2),
            "total_margin": round(self.total_margin, 2),
            "span_margin": round(self.span_margin, 2),
            "exposure_margin": round(self.exposure_margin, 2),
            "legs": self.legs,
            "notes": self.notes,
            "is_estimate": True,
        }


def synthetic_futures(
    symbol: str,
    direction: str = "long",
    strike: float = 0,
    quantity: float = 1,
    lot_size: int = 1,
    call_premium: float = 0,
    put_premium: float = 0,
    spot: float = 0,
    available_margin: Optional[float] = None,
) -> SyntheticFutures:
    """Cost / breakeven / margin of a synthetic futures position.

    * **long synthetic** = buy the call + sell the put.
    * **short synthetic** = sell the call + buy the put.
    """
    direction = (direction or "long").lower()
    if direction not in {"long", "short"}:
        raise ValueError("direction must be 'long' or 'short'")
    strike = float(strike or 0)
    if strike <= 0:
        raise ValueError("strike must be greater than 0")
    quantity = float(quantity or 0)
    if quantity <= 0:
        raise ValueError("quantity must be greater than 0")

    call_premium = float(call_premium or 0)
    put_premium = float(put_premium or 0)

    if direction == "long":
        cost = call_premium - put_premium
        effective = strike + cost
        legs = [
            {"option_type": "CE", "side": "BUY", "strike": strike, "premium": call_premium, "quantity": quantity},
            {"option_type": "PE", "side": "SELL", "strike": strike, "premium": put_premium, "quantity": quantity},
        ]
        notes = [
            "Long synthetic = long call + short put; it behaves like a futures long.",
            "The short put leg is what consumes margin.",
        ]
    else:
        cost = put_premium - call_premium
        effective = strike - cost
        legs = [
            {"option_type": "CE", "side": "SELL", "strike": strike, "premium": call_premium, "quantity": quantity},
            {"option_type": "PE", "side": "BUY", "strike": strike, "premium": put_premium, "quantity": quantity},
        ]
        notes = [
            "Short synthetic = short call + long put; it behaves like a futures short.",
            "The short call leg is what consumes margin.",
        ]

    # Margin: the sold leg needs margin, the bought leg only blocks its premium.
    if direction == "long":
        sold_premium = put_premium
        sold_price = spot or strike
        sold_side = "SELL"
    else:
        sold_premium = call_premium
        sold_price = spot or strike
        sold_side = "SELL"

    bought_premium = call_premium if direction == "long" else put_premium
    short_leg = calculate_margin(
        symbol=symbol,
        side=sold_side,
        quantity=quantity,
        price=sold_price,
        segment="options",
        product="NRML",
        lot_size=lot_size,
    )
    long_leg = calculate_margin(
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        price=(call_premium if direction == "long" else put_premium) or sold_price,
        segment="options",
        product="NRML",
        lot_size=lot_size,
    )
    total_margin = short_leg.total_margin + long_leg.total_margin
    span = short_leg.span_margin + long_leg.span_margin
    exposure = short_leg.exposure_margin + long_leg.exposure_margin
    if bought_premium:
        notes.append(f"Long leg premium blocked: {bought_premium * lot_size * quantity:.2f}.")
    if sold_premium:
        notes.append(f"Short leg premium received: {sold_premium * lot_size * quantity:.2f}.")

    return SyntheticFutures(
        symbol=str(symbol or "").upper(),
        direction=direction,
        strike=strike,
        lot_size=int(lot_size or 1),
        quantity=quantity,
        call_premium=call_premium,
        put_premium=put_premium,
        cost=cost,
        effective_price=effective,
        breakeven=effective,
        total_margin=total_margin,
        span_margin=span,
        exposure_margin=exposure,
        legs=legs,
        notes=notes,
    )
