"""Plugin-based broker factory for order routing."""

from __future__ import annotations

import inspect
from typing import Any, Optional

from app.brokers.plugin_loader import load_broker_class
from app.core.config import get_settings


def _instantiate(cls, **kwargs):
    """Instantiate a broker class, passing only supported kwargs."""
    try:
        sig = inspect.signature(cls.__init__)
        params = sig.parameters
    except (TypeError, ValueError):
        params = {}
    accepted = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if not params or key in params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            accepted[key] = value
    try:
        return cls(**accepted)
    except TypeError:
        return cls()


def get_broker(name: Optional[str] = None, user_id: Optional[str] = None, session: Any = None, **kwargs: Any):
    """Return a broker instance selected by name or application config."""
    if not name:
        try:
            name = get_settings().selected_execution_broker
        except Exception:
            name = "paper"
    cls = load_broker_class(name)
    merged = dict(kwargs)
    if user_id is not None:
        merged.setdefault("user_id", user_id)
    if session is not None:
        merged.setdefault("session", session)
    return _instantiate(cls, **merged)


def create_broker(name: Optional[str] = None, user_id: Optional[str] = None, session: Any = None, **kwargs: Any):
    return get_broker(name=name, user_id=user_id, session=session, **kwargs)


def get_broker_by_name(name: str, **kwargs: Any):
    return get_broker(name=name, **kwargs)


class BrokerFactory:
    """Small object wrapper around the functional factory."""

    def create(self, name: Optional[str] = None, **kwargs: Any):
        return get_broker(name=name, **kwargs)

    def get(self, name: Optional[str] = None, **kwargs: Any):
        return get_broker(name=name, **kwargs)


# Module-level convenience instance.
broker_factory = BrokerFactory()


__all__ = [
    "get_broker",
    "create_broker",
    "get_broker_by_name",
    "BrokerFactory",
    "broker_factory",
]
