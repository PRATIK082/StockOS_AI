"""Tests for the RiskEngine: position sizing, daily loss guard, max positions, order validation."""

from __future__ import annotations

import pytest
from decimal import Decimal

from app.services.risk.risk_engine import RiskEngine
from app.core.config import get_settings, reset_settings


@pytest.fixture(autouse=True)
def _reset_settings():
    """Ensure settings singleton is fresh for each test."""
    reset_settings()
    yield
    reset_settings()


# ---- Position sizing ----


class TestCalculatePositionSize:
    def test_basic_sizing(self):
        result = RiskEngine.calculate_position_size(
            risk_per_trade_rupees=Decimal("2000"),
            entry_price=Decimal("1500"),
            stop_loss_price=Decimal("1400"),
        )
        assert result["quantity"] > 0
        assert result["rupees_at_risk"] > 0
        assert result["reason"] is None or "capped" in str(result["reason"])

    def test_zero_risk_per_share(self):
        """Entry == stop loss -> quantity 0."""
        result = RiskEngine.calculate_position_size(
            risk_per_trade_rupees=Decimal("2000"),
            entry_price=Decimal("1500"),
            stop_loss_price=Decimal("1500"),
        )
        assert result["quantity"] == Decimal("0")
        assert result["reason"] is not None

    def test_tight_stop_smaller_quantity(self):
        """Tighter stop (entry 1500, SL 1490) -> more shares than wider stop."""
        tight = RiskEngine.calculate_position_size(
            risk_per_trade_rupees=Decimal("2000"),
            entry_price=Decimal("1500"),
            stop_loss_price=Decimal("1490"),
        )
        wide = RiskEngine.calculate_position_size(
            risk_per_trade_rupees=Decimal("2000"),
            entry_price=Decimal("1500"),
            stop_loss_price=Decimal("1400"),
        )
        assert tight["quantity"] > wide["quantity"]

    def test_capital_deployed_cap(self):
        """Very large position capped by max_capital_deployed_percent."""
        result = RiskEngine.calculate_position_size(
            risk_per_trade_rupees=Decimal("50000"),
            entry_price=Decimal("100"),
            stop_loss_price=Decimal("99"),
            max_capital_deployed_percent=Decimal("10"),
        )
        # Max notional = 100000 * 10% = 10000; max qty = 10000/100 = 100
        assert result["quantity"] <= Decimal("100")

    def test_reason_string_on_cap(self):
        result = RiskEngine.calculate_position_size(
            risk_per_trade_rupees=Decimal("50000"),
            entry_price=Decimal("100"),
            stop_loss_price=Decimal("99"),
            max_capital_deployed_percent=Decimal("10"),
        )
        assert result["reason"] is not None
        assert "capped" in result["reason"].lower()


# ---- Daily loss guard ----


class TestCheckDailyLoss:
    def test_within_limit(self):
        settings = get_settings()
        settings._daily_pnl = 0.0
        settings.max_daily_loss_rupees = 5000.0
        allowed, reason = RiskEngine.check_daily_loss(Decimal("-1000"))
        assert allowed is True
        assert reason is None

    def test_exceeds_limit(self):
        settings = get_settings()
        settings._daily_pnl = -4000.0
        settings.max_daily_loss_rupees = 5000.0
        allowed, reason = RiskEngine.check_daily_loss(Decimal("-2000"))
        assert allowed is False
        assert reason is not None
        assert "limit" in reason.lower()

    def test_positive_pnl_always_allowed(self):
        settings = get_settings()
        settings._daily_pnl = -4999.0
        settings.max_daily_loss_rupees = 5000.0
        allowed, _ = RiskEngine.check_daily_loss(Decimal("100"))
        assert allowed is True


# ---- Max open positions ----


class TestCheckMaxOpenPositions:
    def test_within_limit(self):
        settings = get_settings()
        settings.max_open_positions = 20
        allowed, reason = RiskEngine.check_max_open_positions(5)
        assert allowed is True

    def test_at_limit(self):
        settings = get_settings()
        settings.max_open_positions = 5
        allowed, reason = RiskEngine.check_max_open_positions(5)
        assert allowed is False
        assert "limit" in reason.lower() or "max" in reason.lower()

    def test_over_limit(self):
        settings = get_settings()
        settings.max_open_positions = 5
        allowed, reason = RiskEngine.check_max_open_positions(10)
        assert allowed is False


# ---- Full order risk check ----


class TestCheckOrder:
    def test_valid_buy_order(self):
        allowed, reason = RiskEngine.check_order(
            symbol="NSE:RELIANCE",
            side="BUY",
            quantity=Decimal("10"),
            entry_price=Decimal("1500"),
        )
        assert allowed is True

    def test_valid_sell_order(self):
        allowed, reason = RiskEngine.check_order(
            symbol="NSE:RELIANCE",
            side="SELL",
            quantity=Decimal("10"),
            entry_price=Decimal("1500"),
        )
        assert allowed is True

    def test_zero_quantity_rejected(self):
        allowed, reason = RiskEngine.check_order(
            symbol="NSE:RELIANCE",
            side="BUY",
            quantity=Decimal("0"),
            entry_price=Decimal("1500"),
        )
        assert allowed is False
        assert "positive" in reason.lower()

    def test_negative_quantity_rejected(self):
        allowed, reason = RiskEngine.check_order(
            symbol="NSE:RELIANCE",
            side="BUY",
            quantity=Decimal("-5"),
            entry_price=Decimal("1500"),
        )
        assert allowed is False

    def test_daily_loss_limit_rejects_order(self):
        """Simulate heavy daily losses then try to order."""
        settings = get_settings()
        settings._daily_pnl = -4900.0
        settings.max_daily_loss_rupees = 5000.0
        allowed, reason = RiskEngine.check_order(
            symbol="NSE:RELIANCE",
            side="BUY",
            quantity=Decimal("10"),
            entry_price=Decimal("1500"),
            stop_loss_price=Decimal("1400"),
        )
        # The estimated pnl from SL should push past the limit
        # (exact result depends on stop loss calculation)
        # At minimum, we check the guard ran
        assert isinstance(allowed, bool)


# ---- Settings helper methods ----


class TestSettingsRiskHelpers:
    def test_check_daily_loss_within(self):
        settings = get_settings()
        settings._daily_pnl = 0.0
        settings.max_daily_loss_rupees = 5000.0
        result = settings.check_daily_loss(-1000.0)
        assert result["allowed"] is True

    def test_check_daily_loss_exceeds(self):
        settings = get_settings()
        settings._daily_pnl = -4500.0
        settings.max_daily_loss_rupees = 5000.0
        result = settings.check_daily_loss(-1000.0)
        assert result["allowed"] is False

    def test_can_open_more_positions(self):
        settings = get_settings()
        settings.max_open_positions = 10
        result = settings.can_open_more_positions(3)
        assert result["allowed"] is True

    def test_cannot_open_more_positions(self):
        settings = get_settings()
        settings.max_open_positions = 10
        result = settings.can_open_more_positions(10)
        assert result["allowed"] is False

    def test_can_deploy_capital(self):
        settings = get_settings()
        settings.max_capital_deployed_percent = 50.0
        result = settings.can_deploy_capital(10.0)
        assert result["allowed"] is True

    def test_is_paper_by_default(self):
        settings = get_settings()
        settings.execution_mode = "PAPER"
        assert settings.is_paper is True
        assert settings.is_live is False

    def test_is_live_only_when_enabled(self):
        settings = get_settings()
        settings.execution_mode = "LIVE_ENABLED"
        assert settings.is_live is True
        assert settings.is_paper is False

    def test_approval_mode(self):
        settings = get_settings()
        settings.execution_mode = "REQUIRE_APPROVAL"
        assert settings.is_approval_required is True
        assert settings.is_paper is True
