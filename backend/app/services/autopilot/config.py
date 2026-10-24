"""Autopilot configuration (per-user, memory-backed kind="autopilot").

The supervisor reads a merged config: hard defaults, overlaid with the user's
persisted choices. Config lives in the memory store so no new table is needed
and the whole payload round-trips as JSON through the existing surface.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.memory.store import memory_store

CONFIG_KEY = "autopilot:config"
CONFIG_KIND = "autopilot"

DEFAULT_SCANNERS = ["momentum", "swing_candidates", "options_candidates"]
SCANNER_CHOICES = [
    "breakout",
    "breakdown",
    "momentum",
    "volume_spike",
    "52_week_high",
    "52_week_low",
    "gap_up",
    "gap_down",
    "strong_fundamentals",
    "value_picks",
    "growth_stocks",
    "quality_stocks",
    "swing_candidates",
    "intraday_candidates",
    "options_candidates",
]


class AutopilotConfig(BaseModel):
    """Tunables the autopilot runs with. All are safe paper defaults."""

    enabled: bool = False
    market: str = "india"  # india | us
    scanners: list[str] = Field(default_factory=lambda: list(DEFAULT_SCANNERS))
    watchlist: list[str] = Field(default_factory=list)  # extra symbols to research/trade
    max_new_entries: int = 3
    entry_qty: int = 1

    take_profit_pct: float = 5.0
    stop_loss_pct: float = -3.0
    trail_enabled: bool = True
    trail_drop_pct: float = 1.0  # sell when pnl has dropped this much from its peak

    option_enabled: bool = True
    option_max_plays: int = 2
    option_lots: int = 1  # each play auto-tracks this many lots as an OptionPosition

    use_llm: bool = False  # reserved for the opt-in LLM debrief slice (Slice 6)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AutopilotConfig":
        cleaned = {k: v for k, v in (data or {}).items() if k in cls.model_fields}
        base = cls()
        return cls(**{**base.model_dump(), **cleaned})

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


async def load_config(user_id: str) -> AutopilotConfig:
    row = await memory_store.get(user_id, CONFIG_KEY)
    return AutopilotConfig.from_dict(row.get("value") if row else None)


async def save_config(user_id: str, config: AutopilotConfig) -> dict[str, Any]:
    return await memory_store.set(
        user_id,
        CONFIG_KEY,
        config.to_dict(),
        kind=CONFIG_KIND,
        scope="state",
    )