"""Risk management framework for StockOS trading.

Implements the risk rules from the autonomous trading agent prompt:
- Position sizing: Kelly Criterion with 2% safety margin per trade
- Stop-loss rules: intraday (0.5-1%), F&O (premium-based), positional (5-8%)
- Portfolio limits: 50% capital deployed, 25% sector, 30% F&O, 20% cash reserve
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class PositionSizingMethod(Enum):
    KELLY = "kelly"
    FIXED_PERCENT = "fixed_percent"
    VOLATILITY_ADJUSTED = "volatility_adjusted"


@dataclass
class PositionSizingResult:
    """Result of position size calculation."""
    quantity: float
    notional: float
    risk_amount: float
    risk_pct_of_capital: float


@dataclass
class RiskLimits:
    """Portfolio-level risk limits."""
    max_capital_deployed_pct: float = 50.0      # Maximum % of total capital to deploy
    max_sector_exposure_pct: float = 25.0     # Maximum % in single sector
    max_fo_exposure_pct: float = 30.0       # Maximum % in F&O
    min_cash_reserve_pct: float = 20.0      # Minimum cash always maintained
    max_positions: int = 20                 # Maximum concurrent positions


@dataclass
class TradeRiskContext:
    """Context for a single trade decision."""
    total_capital: float
    available_capital: float  # capital available after reserves
    sector: str | None = None
    is_fo: bool = False
    current_exposure_pct: float = 0.0
    sector_current_exposure_pct: float = 0.0
    fo_current_exposure_pct: float = 0.0


def kelly_position_size(
    win_probability: float,
    win_loss_ratio: float,
    total_capital: float,
    risk_pct: float = 2.0,
) -> PositionSizingResult:
    """Calculate position size using Kelly Criterion with safety margin.

    Kelly formula: f = (p - q/r) where:
    - p = win probability
    - q = loss probability = 1 - p
    - r = win/loss ratio (average win / average loss)

    Safety margin: multiply by 0.5 (half-Kelly) to reduce risk.
    """
    if win_probability <= 0 or win_probability >= 1:
        raise ValueError("win_probability must be between 0 and 1")

    if win_loss_ratio <= 0:
        raise ValueError("win_loss_ratio must be positive")

    # Full Kelly: f = (p - (1-p) / r) / 1
    # Half-Kelly for safety
    full_kelly = (win_probability - (1 - win_probability) / win_loss_ratio) / 1.0
    safe_kelly = max(0, full_kelly) * 0.5  # Apply 50% safety margin

    risk_amount = total_capital * (risk_pct / 100.0)
    position_pct = min(safe_kelly, risk_pct / 100.0)

    quantity = risk_amount / position_pct if position_pct > 0 else 0.0
    notional = quantity  # Will be multiplied by entry price at call site
    risk_pct_of_capital = position_pct * 100.0

    return PositionSizingResult(
        quantity=quantity,
        notional=notional,
        risk_amount=risk_amount,
        risk_pct_of_capital=risk_pct_of_capital,
    )


def fixed_percent_position_size(
    total_capital: float,
    risk_pct: float = 2.0,
    capital_deployed_pct: float = 50.0,
) -> PositionSizingResult:
    """Fixed percentage position sizing.

    Risk a fixed % of total capital per trade, but never deploy more than
    capital_deployed_pct% of total capital across all positions.
    """
    risk_amount = total_capital * (risk_pct / 100.0)
    max_deployed = total_capital * (capital_deployed_pct / 100.0)
    # Use the lesser of risk-based or deployment-based sizing
    position_pct = min(risk_pct / 100.0, capital_deployed_pct / 100.0)

    quantity = risk_amount / position_pct if position_pct > 0 else 0.0
    notional = quantity

    return PositionSizingResult(
        quantity=quantity,
        notional=notional,
        risk_amount=risk_amount,
        risk_pct_of_capital=risk_pct,
    )


def calculate_stop_loss(
    entry_price: float,
    stop_pct: float,
    side: str = "long",
) -> float:
    """Calculate stop-loss price based on side and percentage.

    Args:
        entry_price: Entry price of the trade
        stop_pct: Stop-loss percentage (e.g., 0.5 for 0.5%)
        side: "long" or "short"

    Returns:
        Stop-loss price
    """
    if side == "long":
        return entry_price * (1 - stop_pct / 100.0)
    elif side == "short":
        return entry_price * (1 + stop_pct / 100.0)
    else:
        raise ValueError("side must be 'long' or 'short'")


def check_portfolio_limits(
    context: TradeRiskContext,
    position_notional: float,
    is_fo: bool = False,
    sector: str | None = None,
    sector_exposure_current: float = 0.0,
    fo_exposure_current: float = 0.0,
) -> dict[str, Any]:
    """Check if a trade violates portfolio risk limits.

    Returns a dict with:
    - allowed: bool
    - reason: str | None (explanation if not allowed)
    - adjusted_notional: float (position size adjusted if needed)
    """
    max_deployed = context.available_capital * (RiskLimits().max_capital_deployed_pct / 100.0)
    max_fo = context.available_capital * (RiskLimits().max_fo_exposure_pct / 100.0)
    min_cash_pct = RiskLimits().min_cash_reserve_pct / 100.0
    max_sector = context.available_capital * (RiskLimits().max_sector_exposure_pct / 100.0)

    # Check if we have enough available capital
    potential_new_exposure = context.current_exposure_pct + (position_notional / context.available_capital * 100.0 if context.available_capital > 0 else 0)

    # Check capital deployment limit
    if potential_new_exposure > RiskLimits().max_capital_deployed_pct:
        # Calculate adjusted size that fits limits
        allowed_pct = RiskLimits().max_capital_deployed_pct - context.current_exposure_pct
        adjusted_notional = context.available_capital * (allowed_pct / 100.0)
        return {
            "allowed": False,
            "reason": f"Would exceed capital deployment limit of {RiskLimits().max_capital_deployed_pct}%",
            "adjusted_notional": adjusted_notional,
        }

    # Check F&O exposure limit
    if is_fo and (fo_exposure_current + position_notional / context.available_capital * 100.0 > RiskLimits().max_fo_exposure_pct):
        allowed_pct = RiskLimits().max_fo_exposure_pct - fo_exposure_current
        adjusted_notional = context.available_capital * (allowed_pct / 100.0)
        return {
            "allowed": False,
            "reason": f"Would exceed F&O exposure limit of {RiskLimits().max_fo_exposure_pct}%",
            "adjusted_notional": adjusted_notional,
        }

    # Check sector exposure limit
    if sector and (sector_exposure_current + position_notional / context.available_capital * 100.0 > RiskLimits().max_sector_exposure_pct):
        allowed_pct = RiskLimits().max_sector_exposure_pct - sector_exposure_current
        adjusted_notional = context.available_capital * (allowed_pct / 100.0)
        return {
            "allowed": False,
            "reason": f"Would exceed sector exposure limit of {RiskLimits().max_sector_exposure_pct}%",
            "adjusted_notional": adjusted_notional,
        }

    # Check minimum cash reserve
    if potential_new_exposure + min_cash_pct * 100 > 100.0:
        allowed_pct = 100.0 - min_cash_pct * 100.0 - context.current_exposure_pct
        adjusted_notional = context.available_capital * (allowed_pct / 100.0)
        return {
            "allowed": False,
            "reason": f"Would violate minimum cash reserve of {RiskLimits().min_cash_reserve_pct}%",
            "adjusted_notional": adjusted_notional,
        }

    return {
        "allowed": True,
        "reason": None,
        "adjusted_notional": position_notional,
    }


def apply_trailing_stop(
    entry_price: float,
    current_price: float,
    initial_stop_pct: float = 1.0,
    trail_pct: float = 0.5,
    side: str = "long",
) -> dict[str, Any]:
    """Calculate trailing stop parameters.

    Activate trailing stop after initial profit, trail by specified percentage.
    """
    # Check if we've hit the initial profit target to activate trailing
    profit_pct = (current_price - entry_price) / entry_price * 100.0 if entry_price != 0 else 0.0

    activated = profit_pct >= initial_stop_pct

    if not activated:
        return {
            "trailing_stop": None,
            "activated": False,
            "profit_pct": round(profit_pct, 2),
        }

    # Calculate trailing stop price
    if side == "long":
        trailing_stop = current_price * (1 - trail_pct / 100.0)
    else:
        trailing_stop = current_price * (1 + trail_pct / 100.0)

    return {
        "trailing_stop": round(trailing_stop, 2),
        "activated": True,
        "profit_pct": round(profit_pct, 2),
        "initial_stop_pct": initial_stop_pct,
        "trail_pct": trail_pct,
    }


# Export all public symbols
__all__ = [
    "PositionSizingMethod",
    "PositionSizingResult",
    "RiskLimits",
    "TradeRiskContext",
    "kelly_position_size",
    "fixed_percent_position_size",
    "calculate_stop_loss",
    "check_portfolio_limits",
    "apply_trailing_stop",
    "__all__",
]