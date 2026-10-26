"""Analyzer mode service (sandbox / paper-live simulation)."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings


class AnalyzerService:
    def __init__(self, user_id: Any = None, broker: Any = None):
        self.user_id = user_id
        self.broker = broker

    @staticmethod
    def is_enabled() -> bool:
        return bool(get_settings().analyzer_mode)

    @staticmethod
    def status() -> dict:
        s = get_settings()
        return {
            "analyzer_mode": bool(s.analyzer_mode),
            "sandbox_capital": float(s.analyzer_sandbox_capital),
            "margin_percent": float(s.analyzer_margin_percent),
            "square_off_time": s.analyzer_square_off_time,
            "session_reset_time": s.analyzer_session_reset_time,
        }

    @staticmethod
    def enable() -> bool:
        get_settings().analyzer_mode = True
        return True

    @staticmethod
    def disable() -> bool:
        get_settings().analyzer_mode = False
        return False

    @staticmethod
    def toggle(enabled: bool | None = None) -> bool:
        s = get_settings()
        if enabled is None:
            enabled = not bool(s.analyzer_mode)
        s.analyzer_mode = bool(enabled)
        return bool(s.analyzer_mode)

    def enable_for_broker(self, broker: Any) -> None:
        if broker is not None:
            broker.analyzer_mode = True

    def disable_for_broker(self, broker: Any) -> None:
        if broker is not None:
            broker.analyzer_mode = False


def get_analyzer_status() -> dict:
    return AnalyzerService.status()


def toggle_analyzer_mode(enabled: bool | None = None) -> bool:
    return AnalyzerService.toggle(enabled)


def enable_analyzer() -> bool:
    return AnalyzerService.enable()


def disable_analyzer() -> bool:
    return AnalyzerService.disable()
