"""Broker plugin loader (OpenAlgo-inspired, adapted to StockOS).

Plugins live under ``app/brokers/plugins/<name>/plugin.json``.  The loader reads
metadata lazily and only imports the concrete broker module when requested, so
adding a new broker does not require changing core code.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List

PLUGINS_DIR = Path(__file__).resolve().parent / "plugins"


def list_plugin_names() -> List[str]:
    if not PLUGINS_DIR.exists():
        return []
    return sorted(p.parent.name for p in PLUGINS_DIR.glob("*/plugin.json"))


def load_plugin_metadata(name: str) -> Dict[str, Any]:
    path = PLUGINS_DIR / name / "plugin.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown broker plugin: {name}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("name", name)
    return data


def list_plugins() -> List[Dict[str, Any]]:
    return [load_plugin_metadata(name) for name in list_plugin_names()]


def load_broker_class(name: str):
    """Lazily import and return the concrete broker class for a plugin."""
    meta = load_plugin_metadata(name)
    module_name = meta.get("module")
    class_name = meta.get("class")
    if not module_name or not class_name:
        raise ValueError(f"Plugin {name} missing module/class metadata")
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"Broker class {class_name} not found in {module_name}")
    return cls


def plugin_supports(name: str, capability: str) -> bool:
    meta = load_plugin_metadata(name)
    return capability in (meta.get("capabilities") or [])
