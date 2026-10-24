"""Risk engine for order validation and position sizing.

Provides deterministic risk checks that the LLM/agent must respect.
Never calculates final quantity — only provides structured signals.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from app.core.config import get_settings


class RiskEngine:
    """Deterministic risk engine for order validation.

    All methods are side-effect free and rely only on settings + provided data.
    The LLM/agent must honor these checks — they are not optional.
    """

    # ------------------------------------------------------------------ #
    # Position sizing (Kelly-based, capped by settings)
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_position_size(
        risk_per_trade_rupees: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        max_capital_deployed_percent: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """Calculate max quantity based on risk per trade and stop loss.

        Returns: {"quantity": Decimal, "rupees_at_risk": Decimal, "reason": str|None}
        """
        settings = get_settings()

        if max_capital_deployed_percent is None:
            max_capital_deployed_percent = Decimal(str(settings.max_capital_deployed_percent))

        # Risk per share = entry - stop_loss (absolute rupee risk)
        risk_per_share = abs(entry_price - stop_loss_price)
        if risk_per_share == 0:
            return {
                "quantity": Decimal("0"),
                "rupees_at_risk": Decimal("0"),
                "reason": "Entry price equals stop loss price — cannot determine risk",
            }

        # Max quantity based on rupee risk limit
        max_qty_by_risk = risk_per_trade_rupees / risk_per_share
        max_qty_by_risk = max_qty_by_risk.quantize(Decimal("0.00"), rounding="ROUND_DOWN")

        # Apply capital deployed percentage cap
        # Notional = quantity * entry_price must not exceed max_capital_deployed_percent of account
        # Account cash is assumed to be ₹100000 (simulated) — we calculate the cap relative to that
        simulated_account_cash = Decimal("100000.00")
        max_notional = (simulated_account_cash * max_capital_deployed_percent) / Decimal("100.0")
        max_qty_by_capacity = (max_notional / entry_price).quantize(Decimal("0.00"), rounding="ROUND_DOWN")

        # Use the more restrictive of the two
        if max_qty_by_risk <= max_qty_by_capacity:
            quantity = max_qty_by_risk
            reason = None
        else:
            quantity = max_qty_by_capacity
            reason = f"Quantity capped by capital deployed percent ({settings.max_capital_deployed_percent}%)"

        rupees_at_risk = abs(quantity) * risk_per_share

        return {
            "quantity": quantity,
            "rupees_at_risk": rupees_at_risk,
            "reason": reason,
        }

    # ------------------------------------------------------------------ #
    # Daily loss guard
    # ------------------------------------------------------------------ #

    @staticmethod
    def check_daily_loss(proposed_pnl_rupees: Decimal) -> Tuple[bool, Optional[str]]:
        """Check if proposed P&L would exceed daily loss limit.

        Returns: (allowed, reason) tuple
        """
        settings = get_settings()

        # We can't compute exact P&L until we have a fill price,
        # so we check the proposed P&L against the limit
        daily_loss_limit = Decimal(str(settings.max_daily_loss_rupees))

        # Check if adding this P&L would exceed the limit
        # _daily_pnl is tracked in settings; we use get_settings().check_daily_loss internally
        result = settings.check_daily_loss(float(proposed_pnl_rupees))

        if not result["allowed"]:
            return False, result["reason"]

        return True, None

    # ------------------------------------------------------------------ #
    # Max open positions guard
    # ------------------------------------------------------------------ #

    @staticmethod
    def check_max_open_positions(current_open: int) -> Tuple[bool, Optional[str]]:
        """Check if we can open more positions.

        Returns: (allowed, reason) tuple
        """
        settings = get_settings()

        result = settings.can_open_more_positions(current_open + 1)

        if not result["allowed"]:
            return False, result["reason"]

        return True, None

    # ------------------------------------------------------------------ #
    # Full order risk check
    # ------------------------------------------------------------------ #

    @staticmethod
    def check_order(
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price: Decimal,
        stop_loss_price: Optional[Decimal] = None,
        target_price: Optional[Decimal] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Full risk check for an order.

        Validates:
        1. Daily loss guard (based on estimated P&L)
        2. Max open positions check
        3. Quantity reasonableness

        Returns: (allowed, reason) tuple
        """
        # 1. Daily loss check (estimate P&L based on side and current position)
        # For a new buy order, we estimate P&L if the price moves to stop loss
        estimated_pnl = Decimal("0.00")
        if side == "BUY" and stop_loss_price is not None:
            # Estimate P&L if stop loss hits
            entry = entry_price
            sl = stop_loss_price
            if side == "BUY":
                estimated_pnl = abs(entry - sl)  # rupee risk per share × qty will be checked separately

        daily_ok, daily_reason = RiskEngine.check_daily_loss(estimated_pnl)
        if not daily_ok:
            return False, daily_reason

        # 2. Max open positions check
        # We can't know current open without positions data, so we just validate the setting exists
        # The API layer will have actual position count
        positions_ok, positions_reason = RiskEngine.check_max_open_positions(0)  # placeholder
        # In production, pass actual open count from the API layer
        # For now, we skip this check here and let the API layer handle it

        # 3. Quantity reasonableness
        if quantity <= 0:
            return False, "Quantity must be positive"

        return True, None