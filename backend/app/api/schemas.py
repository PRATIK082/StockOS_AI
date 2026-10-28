"""Shared Pydantic schemas for API request/response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


# --- Auth ---------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    identifier: str  # email or username
    password: str
    totp_code: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class TOTPSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    enabled: bool = False


class TOTPVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


# --- Market --------------------------------------------------------------------


class QuoteResponse(BaseModel):
    symbol: str
    name: str | None = None
    price: float | None = None
    previous_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    currency: str | None = None
    day_change_pct: float | None = None
    market_cap: float | None = None
    sector: str | None = None
    provider: str | None = None


class HistoryResponse(BaseModel):
    symbol: str
    interval: str
    period: str
    provider: str | None = None
    candles: list[dict[str, Any]]


class FundamentalsResponse(BaseModel):
    symbol: str
    provider: str | None = None
    base: dict = {}


# --- Watchlist -----------------------------------------------------------------


class WatchlistCreate(BaseModel):
    name: str = "Default"


class WatchlistUpdate(BaseModel):
    symbol: str
    # action: "add" | "remove"
    action: str = "add"


# --- Portfolio -----------------------------------------------------------------


class HoldingCreate(BaseModel):
    symbol: str
    quantity: str = Field(min_length=1)
    average_cost: str = Field(min_length=1)


# --- Options -------------------------------------------------------------------


class OptionPositionCreate(BaseModel):
    symbol: str
    option_type: str = Field(pattern="^(CALL|PUT|CE|PE)$")
    strike: float
    expiry: str = Field(min_length=1)  # ISO date (YYYY-MM-DD)
    quantity: float = 1
    premium: float = 0


# --- Order Management ----------------------------------------------------------


class OrderPreviewRequest(BaseModel):
    symbol: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)


class OrderSubmitRequest(BaseModel):
    symbol: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)
    price: float | None = None
    order_type: Literal["MARKET", "LIMIT"] | None = None


class OrderResponse(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: int
    price: float
    status: str
    estimated_fill: float | None = None
    risk_notes: dict | None = None


# --- Research / Chat -----------------------------------------------------------


class ResearchRequest(BaseModel):
    symbol: str
    provider: str | None = None
    intent: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None


class DeepAnalysisRequest(BaseModel):
    """Multi-symbol "Ask AI" deep analysis: any symbols + any question, all on real data."""
    symbols: list[str] = Field(min_length=1, max_length=5)
    question: str = Field(min_length=1, max_length=2000)
    include: list[str] = Field(
        default_factory=lambda: ["quote", "technical", "options", "prediction"]
    )
    provider: str | None = None
    stream: bool = True


# --- Trading Desk --------------------------------------------------------------


class TradingAnalyzeRequest(BaseModel):
    symbol: str = Field(min_length=1)
    provider: str | None = None
    deep_model: str | None = None
    quick_model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    llm_max_retries: int | None = None
    max_debate_rounds: int | None = None
    max_risk_rounds: int | None = None
    trade_date: str | None = None
    option_type: Literal["CE", "PE", "CALL", "PUT"] | None = None
    option_strike: float | None = None
    option_expiry: str | None = None


class TradingCredentialCreate(BaseModel):
    provider: str = Field(min_length=2)
    api_key: str = ""
    base_url: str | None = None
    deep_model: str | None = None
    quick_model: str | None = None
    is_default: bool = False


class TradingSimulateRequest(BaseModel):
    quantity: float = Field(default=1, gt=0)
    average_cost: float | None = Field(default=None, gt=0)


# --- Predictions ---------------------------------------------------------------


class PredictionHistoryCreate(BaseModel):
    symbol: str
    timeframe: str = "1W"
    payload: dict[str, Any]