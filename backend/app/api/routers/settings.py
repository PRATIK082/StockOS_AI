"""Settings API router for StockOS.

Provides runtime update for the trading settings
(execution mode, broker selection, risk limits, data source).

All endpoints return the *Python-aligned* values (not raw DB strings)
via the :func:`app.core.config.get_settings` bridge.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, confloat, conint

from app.core.config import get_settings

router = APIRouter(tags=["settings"], prefix="/v1/settings")


# ------------------------------------------------------------------------- #
# Pydantic schemas for request/response bodies
# ------------------------------------------------------------------------- #


class SettingsUpdate(BaseModel):
    """Partial update of trading settings.

    Only provided fields are updated; all other fields keep their current
    values.  Secrets / API keys are *never* accepted here.
    """
    execution_mode: str | None = Field(None, description="PAPER | REQUIRE_APPROVAL | LIVE_ENABLED")
    selected_execution_broker: str | None = Field(
        None, description="paper | zerodha | angelone"
    )
    selected_market_data_source: str | None = Field(
        None, description="yahoo | nse | zerodha | angelone | tradingview_webhook"
    )
    max_order_risk_rupees: confloat(gt=0) | None = Field(
        None, ge=1, description="Max rupee risk per order"
    )
    max_daily_loss_rupees: confloat(gt=0) | None = Field(
        None, ge=1, description="Max daily loss before auto-halt"
    )
    max_open_positions: conint(gt=0) | None = Field(
        None, ge=1, le=200, description="Max concurrent open positions"
    )
    max_capital_deployed_percent: confloat(gt=0, le=100) | None = Field(
        None, ge=1, le=100, description="% of total capital to deploy at once"
    )
    max_fno_lots: conint(gt=0) | None = Field(
        None, ge=1, le=100, description="Max F&O lots per strategy"
    )
    analyzer_mode: bool | None = Field(None, description="Enable analyzer (sandbox) mode")


class SettingsResponse(BaseModel):
    """Full settings response - Python-aligned types."""
    execution_mode: str
    selected_execution_broker: str
    selected_market_data_source: str
    max_order_risk_rupees: float
    max_daily_loss_rupees: float
    max_open_positions: int
    max_capital_deployed_percent: float
    max_fno_lots: int
    analyzer_mode: bool = False
    daily_pnl_rupees: float  # accumulated today (UTC)


# ------------------------------------------------------------------------- #
# Routes
# ------------------------------------------------------------------------- #


@router.get("/", response_model=SettingsResponse)
def get_settings_endpoint():
    """Return current trading settings (Python-aligned types)."""
    d = get_settings()
    return SettingsResponse(
        execution_mode=d.execution_mode,
        selected_execution_broker=d.broker,
        selected_market_data_source=d.data_source,
        max_order_risk_rupees=d.max_order_risk_rupees,
        max_daily_loss_rupees=d.max_daily_loss_rupees,
        max_open_positions=d.max_open_positions,
        max_capital_deployed_percent=d.max_capital_deployed_percent,
        max_fno_lots=d.max_fno_lots,
        analyzer_mode=d.analyzer_mode,
        daily_pnl_rupees=d._daily_pnl,  # noqa: protected-access
    )


@router.patch("/", response_model=SettingsResponse)
def update_settings(payload: SettingsUpdate):
    """Partial update of trading settings.

    Only fields explicitly provided are updated.  The in-memory
    :func:`app.core.config.get_settings` singleton is refreshed immediately.
    """
    settings = get_settings()

    if payload.execution_mode is not None:
        settings.execution_mode = payload.execution_mode
    if payload.selected_execution_broker is not None:
        settings.selected_execution_broker = payload.selected_execution_broker
    if payload.selected_market_data_source is not None:
        settings.selected_market_data_source = payload.selected_market_data_source
    if payload.max_order_risk_rupees is not None:
        settings.max_order_risk_rupees = payload.max_order_risk_rupees
    if payload.max_daily_loss_rupees is not None:
        settings.max_daily_loss_rupees = payload.max_daily_loss_rupees
    if payload.max_open_positions is not None:
        settings.max_open_positions = payload.max_open_positions
    if payload.max_capital_deployed_percent is not None:
        settings.max_capital_deployed_percent = payload.max_capital_deployed_percent
    if payload.max_fno_lots is not None:
        settings.max_fno_lots = payload.max_fno_lots
    if payload.analyzer_mode is not None:
        settings.analyzer_mode = payload.analyzer_mode

    d = get_settings()
    return SettingsResponse(
        execution_mode=d.execution_mode,
        selected_execution_broker=d.broker,
        selected_market_data_source=d.data_source,
        max_order_risk_rupees=d.max_order_risk_rupees,
        max_daily_loss_rupees=d.max_daily_loss_rupees,
        max_open_positions=d.max_open_positions,
        max_capital_deployed_percent=d.max_capital_deployed_percent,
        max_fno_lots=d.max_fno_lots,
        analyzer_mode=d.analyzer_mode,
        daily_pnl_rupees=d._daily_pnl,  # noqa: protected-access
    )
