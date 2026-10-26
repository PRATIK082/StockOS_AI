"""StockOS Central Settings - Pydantic BaseSettings.

Environment variables (all optional, with sensible defaults):

  # Execution mode
  STOCKOS_EXECUTION_MODE=PAPER                # PAPER | REQUIRE_APPROVAL | LIVE_ENABLED

  # Selected brokers / data sources
  STOCKOS_EXECUTION_BROKER=paper              # paper | zerodha | angelone
  STOCKOS_MARKET_DATA_SOURCE=yahoo            # yahoo | nse | zerodha | angelone | tradingview_webhook

  # Risk limits (rupees / percent)
  STOCKOS_MAX_ORDER_RISK_RUPEES=2000          # Max rupee risk per order
  STOCKOS_MAX_DAILY_LOSS_RUPEES=5000          # Max daily loss before halt
  STOCKOS_MAX_OPEN_POSITIONS=20               # Max concurrent open positions
  STOCKOS_MAX_CAPITAL_DEPLOYED_PERCENT=50.0   # % of total capital to deploy
  STOCKOS_MAX_FNO_LOTS=10                     # Max F&O lots per strategy

  # JWT / token settings (for security module compatibility)
  STOCKOS_ACCESS_TOKEN_EXPIRE_MINUTES=30      # Token expiry in minutes
  STOCKOS_JWT_SECRET=super-secret-key-change-me # Secret for JWT signing
  STOCKOS_JWT_ALGORITHM=HS256                  # Algorithm for JWT signing

  # LLM / data provider overrides (per-request or runtime)
  # (individually overridden per API call, not env-global)
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices


class StockOSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STOCKOS_")

    # ------------------------------------------------------------------ #
    # Execution mode
    # ------------------------------------------------------------------ #
    execution_mode: str = "PAPER"  # PAPER | REQUIRE_APPROVAL | LIVE_ENABLED

    @field_validator("execution_mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        allowed = {"PAPER", "REQUIRE_APPROVAL", "LIVE_ENABLED"}
        if v not in allowed:
            raise ValueError(f"execution_mode must be one of {allowed}")
        return v

    # ------------------------------------------------------------------ #
    # Selected brokers / data sources
    # ------------------------------------------------------------------ #
    selected_execution_broker: str = "paper"  # paper | zerodha | angelone
    selected_market_data_source: str = "yahoo"  # yahoo | nse | zerodha | angelone | tradingview_webhook

    # ------------------------------------------------------------------ #
    # Risk limits
    # ------------------------------------------------------------------ #
    max_order_risk_rupees: float = 2000.0
    max_daily_loss_rupees: float = 5000.0
    max_open_positions: int = 20
    max_capital_deployed_percent: float = 50.0
    max_fno_lots: int = 10

    # ------------------------------------------------------------------ #
    # JWT / token settings (for security module compatibility)
    # ------------------------------------------------------------------ #
    access_token_expire_minutes: int = 30
    jwt_secret: str = "super-secret-key-change-me"
    jwt_algorithm: str = "HS256"
    password_pepper: str = ""  # optional application pepper for password hashing
    rate_limit_default_per_minute: int = 120
    rate_limit_auth_per_minute: int = 10    # ------------------------------------------------------------------ #
    # LLM providers (local-first; all optional)
    # ------------------------------------------------------------------ #
    llm_default_provider: str = "ollama"
    llm_default_model: str = ""
    ollama_base_url: str = "http://localhost:11434"
    lmstudio_base_url: str = "http://localhost:1234"
    llamacpp_base_url: str = "http://localhost:8080"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ------------------------------------------------------------------ #
    # Database URL
    # ------------------------------------------------------------------ #
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data.db",
        validation_alias=AliasChoices("DATABASE_URL", "STOCKOS_DATABASE_URL"),
    )

    # ------------------------------------------------------------------ #
    # Environment
    # ------------------------------------------------------------------ #
    environment: str = "development"  # development | production
    debug: bool = True

    # ------------------------------------------------------------------ #
    # Application settings
    # ------------------------------------------------------------------ #
    app_name: str = "StockOS AI"
    app_description: str = "AI operating system for investing"
    app_version: str = "0.1.0"
    api_prefix: str = "/api"

    # ------------------------------------------------------------------ #
    # Derived / internal (not set via env)
    # ------------------------------------------------------------------ #
    _daily_pnl: float = 0.0  # accumulated today (UTC midnight)
    ta_scheduler_enabled: bool = False  # scheduler feature flag

    # ------------------------------------------------------------------ #
    # Configuration integrity
    # ------------------------------------------------------------------ #
    @property
    def is_paper(self) -> bool:
        return self.execution_mode in {"PAPER", "REQUIRE_APPROVAL"}

    @property
    def is_live(self) -> bool:
        return self.execution_mode == "LIVE_ENABLED"

    @property
    def is_approval_required(self) -> bool:
        return self.execution_mode == "REQUIRE_APPROVAL"

    @property
    def broker(self) -> str:
        return self.selected_execution_broker

    @property
    def data_source(self) -> str:
        return self.selected_market_data_source

    def check_daily_loss(self, pnl_rupees: float) -> dict[str, Any]:
        """Return {'allowed': bool, 'new_daily_pnl': float, 'reason': str|None."""
        new_total = self._daily_pnl + pnl_rupees
        if new_total < -self.max_daily_loss_rupees:
            return {
                "allowed": False,
                "new_daily_pnl": self._daily_pnl,
                "reason": f"Daily loss limit would exceed {self.max_daily_loss_rupees} "
                f"(current: {self._daily_pnl:.0f}, proposed: {pnl_rupees:.0f})",
            }
        self._daily_pnl = new_total
        return {"allowed": True, "new_daily_pnl": new_total, "reason": None}

    def can_open_more_positions(self, current_count: int) -> dict[str, Any]:
        if current_count >= self.max_open_positions:
            return {
                "allowed": False,
                "reason": f"Max open positions ({self.max_open_positions}) reached",
            }
        return {"allowed": True, "reason": None}

    def can_deploy_capital(self, capital_pct: float) -> dict[str, Any]:
        deployed = capital_pct + abs(self._daily_pnl) / 100.0  # simplified
        if deployed > self.max_capital_deployed_percent:
            return {
                "allowed": False,
                "reason": f"Capital deployed {deployed:.1f}% exceeds limit "
                f"{self.max_capital_deployed_percent:.1f}%",
            }
        return {"allowed": True, "reason": None}


# Singleton instance - lazy so .env can be loaded after import
_settings: StockOSSettings | None = None
_settings_obj: StockOSSettings | None = None


def get_settings() -> StockOSSettings:
    global _settings, _settings_obj
    if _settings is None:
        _settings = StockOSSettings()
    if _settings_obj is None:
        _settings_obj = _settings
    return _settings_obj  # type: ignore


def reset_settings() -> None:
    global _settings, _settings_obj
    _settings = None
    _settings_obj = None


# Expose `settings` name for `from app.core.config import settings` compatibility
settings = get_settings()
