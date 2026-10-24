"""Performance tracking metrics for StockOS trading.

Tracks daily/weekly/monthly P&L, win rate, profit factor, drawdown metrics,
and other performance statistics from the autonomous trading agent prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import date, datetime
from collections import defaultdict
import numpy as np


@dataclass
class DailyMetrics:
    """Daily trading metrics for a single trading day."""
    date: date
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    average_profit: float = 0.0
    average_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    expectancy: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_holding_period: float = 0.0

    @property
    def is_profitable(self) -> bool:
        return self.gross_profit > self.gross_loss

    @property
    def profit_factor_calc(self) -> float:
        if self.gross_loss == 0:
            return self.gross_profit if self.gross_profit > 0 else 0.0
        return round(self.gross_profit / self.gross_loss, 4)

    def update_from_trade(self, pnl: float, was_winning: bool, holding_periods: int = 0) -> None:
        """Update metrics from a single trade."""
        self.total_trades += 1

        if was_winning:
            self.winning_trades += 1
            self.gross_profit += pnl
            if pnl > self.largest_win:
                self.largest_win = pnl
        else:
            self.losing_trades += 1
            self.gross_loss += abs(pnl)  # Store as positive
            if abs(pnl) > self.largest_loss:
                self.largest_loss = abs(pnl)

        # Calculate running averages
        if self.winning_trades > 0:
            self.average_profit = round(self.gross_profit / self.winning_trades, 4)
        if self.losing_trades > 0:
            self.average_loss = round(self.gross_loss / self.losing_trades, 4)

        self.win_rate = round(self.winning_trades / self.total_trades * 100, 2) if self.total_trades > 0 else 0.0

        # Expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
        win_rate_dec = self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0
        loss_rate = 1.0 - win_rate_dec
        self.expectancy = round(
            (win_rate_dec * self.average_profit) - (loss_rate * self.average_loss),
            6
        ) if self.total_trades > 0 else 0.0

        # Profit factor
        self.profit_factor = self.profit_factor_calc

        # Average holding period
        if holding_periods > 0:
            self.avg_holding_period = round(
                (self.avg_holding_period * (self.total_trades - 1) + holding_periods) / self.total_trades,
                2
            ) if self.total_trades > 0 else float(holding_periods)


@dataclass
class WeeklyMetrics:
    """Weekly trading metrics."""
    week_start: date
    week_end: date
    daily: list[DailyMetrics] = field(default_factory=list)
    total_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_weekly_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0

    def add_daily(self, daily: DailyMetrics) -> None:
        """Add a day's metrics to the weekly total."""
        self.daily.append(daily)
        self.total_pnl += daily.total_pnl
        self.total_trades += daily.total_trades
        self.winning_trades += daily.winning_trades
        self.losing_trades += daily.losing_trades

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return round(self.winning_trades / self.total_trades * 100, 2)

    @property
    def is_profitable(self) -> bool:
        return self.total_pnl > 0


@dataclass
class PerformanceReport:
    """Composite performance report spanning multiple periods."""
    period_start: date
    period_end: date
    daily: list[DailyMetrics] = field(default_factory=list)
    weekly: list[WeeklyMetrics] = field(default_factory=list)
    total_trades: int = 0
    total_winning: int = 0
    total_losing: int = 0
    total_pnl: float = 0.0
    average_daily_pnl: float = 0.0
    max_drawdown_overall: float = 0.0
    sharpe_ratio_overall: float = 0.0
    profit_factor_overall: float = 0.0
    calmar_ratio: float = 0.0  # annualized return / max drawdown

    @property
    def overall_win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return round(self.total_winning / self.total_trades * 100, 2)

    @property
    def is_profitable(self) -> bool:
        return self.total_pnl > 0

    def calculate_overall(self) -> None:
        """Calculate overall metrics from all daily/weekly data."""
        self.total_trades = sum(d.total_trades for d in self.daily)
        self.total_winning = sum(d.winning_trades for d in self.daily)
        self.total_losing = sum(d.losing_trades for d in self.daily)
        self.total_pnl = sum(d.total_pnl for d in self.daily)
        self.average_daily_pnl = round(self.total_pnl / len(self.daily), 2) if self.daily else 0.0

        # Max drawdown overall (max across all days)
        all_drawdowns = [d.max_drawdown for d in self.daily if d.max_drawdown > 0]
        self.max_drawdown_overall = max(all_drawdowns) if all_drawdowns else 0.0

        # Profit factor overall
        if self.total_losing > 0:
            self.profit_factor_overall = round(self.total_pnl / self.total_losing, 4) if self.total_pnl else 0.0
        else:
            self.profit_factor_overall = 1.0 if self.total_pnl > 0 else 0.0

        # Sharpe ratio (simplified: avg daily / std daily)
        daily_returns = [d.total_pnl for d in self.daily]
        if len(daily_returns) > 1:
            mean_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns)
            if std_ret != 0:
                self.sharpe_ratio_overall = round(mean_ret / std_ret, 4)
            else:
                self.sharpe_ratio_overall = 0.0
        else:
            self.sharpe_ratio_overall = 0.0


@dataclass
class EmergencyTrigger:
    """Record of an emergency protocol trigger."""
    trigger_type: str  # "market_crash", "technical_failure", "unusual_loss"
    timestamp: datetime
    nifty_change_pct: float | None = None
    drawdown_pct: float | None = None
    action_taken: str | None = None
    resolved: bool = False


class PerformanceTracker:
    """Main performance tracking class that accumulates metrics across sessions."""

    def __init__(self):
        self.daily_metrics: Dict[date, DailyMetrics] = {}
        self.emergency_triggers: list[EmergencyTrigger] = []
        self._current_date: date | None = None
        self._daily_trades: list[dict] = []

    def start_new_day(self, trade_date: date | None = None) -> None:
        """Start tracking a new trading day."""
        if trade_date is None:
            trade_date = date.today()
        self._current_date = trade_date
        if trade_date not in self.daily_metrics:
            self.daily_metrics[trade_date] = DailyMetrics(date=trade_date)
        self._daily_trades = []

    def record_trade(self, pnl: float, was_winning: bool, holding_periods: int = 0) -> None:
        """Record a completed trade."""
        if self._current_date is None:
            raise ValueError("No current day tracked - call start_new_day first")

        self._daily_trades.append({
            "pnl": pnl,
            "was_winning": was_winning,
            "holding_periods": holding_periods,
        })
        self.daily_metrics[self._current_date].update_from_trade(pnl, was_winning, holding_periods)

    def trigger_emergency(
        self,
        trigger_type: str,
        nifty_change_pct: float | None = None,
        drawdown_pct: float | None = None,
        action_taken: str | None = None,
    ) -> EmergencyTrigger:
        """Record an emergency protocol trigger."""
        trigger = EmergencyTrigger(
            trigger_type=trigger_type,
            timestamp=datetime.now(),
            nifty_change_pct=nifty_change_pct,
            drawdown_pct=drawdown_pct,
            action_taken=action_taken,
        )
        self.emergency_triggers.append(trigger)
        return trigger

    def get_daily(self, trade_date: date) -> DailyMetrics | None:
        """Get daily metrics for a specific date."""
        return self.daily_metrics.get(trade_date)

    def get_weekly(self, week_start: date) -> WeeklyMetrics | None:
        """Get weekly metrics for a specific week."""
        daily_list = [
            d for d in self.daily_metrics.values()
            if d.date >= week_start and d.date < week_start + __import__("datetime").timedelta(days=7)
        ]
        if not daily_list:
            return None

        weekly = WeeklyMetrics(week_start=week_start, week_end=week_start + __import__("datetime").timedelta(days=6))
        for d in daily_list:
            weekly.add_daily(d)
        return weekly

    def generate_report(self, start_date: date, end_date: date) -> PerformanceReport:
        """Generate a performance report for a date range."""
        daily_in_range = [
            d for d in self.daily_metrics.values()
            if start_date <= d.date <= end_date
        ]

        report = PerformanceReport(
            period_start=start_date,
            period_end=end_date,
            daily=daily_in_range,
        )
        report.calculate_overall()
        return report

    def get_stats_summary(self) -> dict[str, Any]:
        """Get a summary of key statistics."""
        if not self.daily_metrics:
            return {"total_days": 0, "message": "No trading data yet"}

        report = self.generate_report(min(self.daily_metrics.keys()), max(self.daily_metrics.keys()))

        return {
            "total_days": len(self.daily_metrics),
            "total_trades": report.total_trades,
            "total_pnl": round(report.total_pnl, 2),
            "overall_win_rate": report.overall_win_rate,
            "profit_factor": report.profit_factor_overall,
            "max_drawdown": round(report.max_drawdown_overall, 2),
            "sharpe_ratio": report.sharpe_ratio_overall,
            "is_profitable": report.is_profitable,
        }


__all__ = [
    "DailyMetrics",
    "WeeklyMetrics",
    "PerformanceReport",
    "EmergencyTrigger",
    "PerformanceTracker",
    "__all__",
]