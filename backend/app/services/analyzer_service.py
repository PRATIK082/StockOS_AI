"""Compatibility alias for analyzer service."""

from __future__ import annotations

from app.services.analyzer import AnalyzerService, get_analyzer_status, toggle_analyzer_mode, enable_analyzer, disable_analyzer

__all__ = ["AnalyzerService", "get_analyzer_status", "toggle_analyzer_mode", "enable_analyzer", "disable_analyzer"]
