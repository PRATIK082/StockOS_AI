"""Emergency protocols for StockOS trading.

Implements the emergency protocols from the autonomous trading agent prompt:
- Market crash (>3% NIFTY down)
- Technical failure (API connection lost > 5 minutes)
- Unusual loss (>5% daily drawdown)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any

from app.services.market_session import MarketSession, MarketHours, get_current_session, is_trading_session
from app.services.performance_tracker import PerformanceTracker, EmergencyTrigger


class EmergencyType(Enum):
    """Types of emergencies that can be triggered."""
    MARKET_CRASH = "market_crash"
    TECHNICAL_FAILURE = "technical_failure"
    UNUSUAL_LOSS = "unusual_loss"


@dataclass
class EmergencyProtocolResult:
    """Result of emergency protocol execution."""
    triggered: bool
    protocol_type: EmergencyType
    actions: list[str]
    capital_reduction_pct: float
    session: MarketSession
    timestamp: datetime


class EmergencyProtocols:
    """Manages emergency protocol triggers and responses."""

    # Thresholds from the prompt
    MARKET_CRASH_THRESHOLD_PCT: float = 3.0    # NIFTY down >3%
    UNUSUAL_LOSS_DRAWDOWN_THRESHOLD_PCT: float = 5.0  # Daily drawdown >5%

    def __init__(self, tracker: PerformanceTracker | None = None):
        self.tracker = tracker or PerformanceTracker()
        self._api_lost_since: datetime | None = None

    def check_market_crash(
        self, nifty_change_pct: float, tracker: PerformanceTracker | None = None
    ) -> EmergencyProtocolResult:
        """Check if NIFTY crash protocol should be triggered.

        Triggered when NIFTY drops more than 3% in a session.
        """
        if nifty_change_pct <= -self.MARKET_CRASH_THRESHOLD_PCT:
            actions = [
                "Immediately square off all long positions",
                "Activate hedging strategies (buy PUT options)",
                "Reduce position sizes by 50%",
                "Switch to defensive sectors (IT, Pharma, FMCG)",
            ]
            return EmergencyProtocolResult(
                triggered=True,
                protocol_type=EmergencyType.MARKET_CRASH,
                actions=actions,
                capital_reduction_pct=50.0,
                session=get_current_session(),
                timestamp=datetime.now(),
            )
        return EmergencyProtocolResult(
            triggered=False,
            protocol_type=EmergencyType.MARKET_CRASH,
            actions=[],
            capital_reduction_pct=0.0,
            session=get_current_session(),
            timestamp=datetime.now(),
        )

    def check_technical_failure(
        self, api_lost_since: datetime | None = None, tracker: PerformanceTracker | None = None
    ) -> EmergencyProtocolResult:
        """Check if technical failure protocol should be triggered.

        Triggered when API connection is lost for more than 5 minutes.
        """
        now = datetime.now()
        lost_since = api_lost_since or self._api_lost_since or now

        # Check if API has been lost for more than 5 minutes
        loss_duration = (now - lost_since).total_seconds() / 60.0  # minutes

        if loss_duration > 5.0:
            actions = [
                "If API connection lost > 5 minutes, close all open positions",
                "Send alert to owner via email/SMS/Telegram",
                "Log error details for post-mortem analysis",
                "Resume trading only after successful reconnection and validation",
            ]
            self._api_lost_since = None  # Reset after handling
            return EmergencyProtocolResult(
                triggered=True,
                protocol_type=EmergencyType.TECHNICAL_FAILURE,
                actions=actions,
                capital_reduction_pct=100.0,  # Fully exit positions
                session=get_current_session(),
                timestamp=datetime.now(),
            )
        return EmergencyProtocolResult(
            triggered=False,
            protocol_type=EmergencyType.TECHNICAL_FAILURE,
            actions=[],
            capital_reduction_pct=0.0,
            session=get_current_session(),
            timestamp=datetime.now(),
        )

    def check_unusual_loss(
        self, drawdown_pct: float, tracker: PerformanceTracker | None = None
    ) -> EmergencyProtocolResult:
        """Check if unusual loss protocol should be triggered.

        Triggered when daily drawdown exceeds 5%.
        """
        if drawdown_pct >= self.UNUSUAL_LOSS_DRAWDOWN_THRESHOLD_PCT:
            actions = [
                "Stop all new trade entries immediately",
                "Review and close existing positions",
                "Analyze root cause (strategy failure, market anomaly, technical issue)",
                "Adjust strategy parameters before resuming",
            ]
            return EmergencyProtocolResult(
                triggered=True,
                protocol_type=EmergencyType.UNUSUAL_LOSS,
                actions=actions,
                capital_reduction_pct=50.0,  # Reduce by 50%
                session=get_current_session(),
                timestamp=datetime.now(),
            )
        return EmergencyProtocolResult(
            triggered=False,
            protocol_type=EmergencyType.UNUSUAL_LOSS,
            actions=[],
            capital_reduction_pct=0.0,
            session=get_current_session(),
            timestamp=datetime.now(),
        )

    def trigger_protocol(
        self,
        trigger_type: EmergencyType,
        **kwargs,
    ) -> EmergencyProtocolResult:
        """Manually trigger an emergency protocol."""
        if trigger_type == EmergencyType.MARKET_CRASH:
            nifty_change = kwargs.get("nifty_change_pct", 0)
            return self.check_market_crash(nifty_change)
        elif trigger_type == EmergencyType.TECHNICAL_FAILURE:
            api_lost = kwargs.get("api_lost_since")
            return self.check_technical_failure(api_lost)
        elif trigger_type == EmergencyType.UNUSUAL_LOSS:
            drawdown = kwargs.get("drawdown_pct", 0)
            return self.check_unusual_loss(drawdown)
        else:
            raise ValueError(f"Unknown emergency type: {trigger_type}")

    def generate_initialization_checklist(self) -> list[str]:
        """Generate the daily initialization checklist from the prompt."""
        return [
            "[ ] Broker API connections active (Zerodha + Angel One)",
            "[ ] Market data streaming correctly",
            "[ ] Sufficient capital available in trading account",
            "[ ] No exchange holidays or trading restrictions",
            "[ ] All strategy parameters loaded",
            "[ ] Risk limits configured correctly",
            "[ ] Emergency stop-loss triggers active",
            "[ ] Logging and monitoring systems operational",
        ]

    def get_daily_checklist(self, trade_date: date | None = None) -> dict[str, bool]:
        """Get the status of the daily initialization checklist."""
        checklist = self.generate_initialization_checklist()
        # Return all items as False by default (to be filled by user/operator)
        return {item: False for item in checklist}

    def record_emergency(self, trigger: EmergencyTrigger) -> None:
        """Record an emergency trigger in the tracker."""
        self.tracker.emergency_triggers.append(trigger)


# Export all public symbols
__all__ = [
    "EmergencyType",
    "EmergencyProtocolResult",
    "EmergencyProtocols",
    "__all__",
]