"""Scheduler bridge: {"kind": "flow"/"strategy_host"} playbooks dispatch (parent wiring)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix="smtest_bridge_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

import app.db.models.flow_graph  # noqa: F401
import app.db.models.strategy_script  # noqa: F401
from app.db.session import init_db  # noqa: E402
from app.services.scheduler.runner import run_playbook  # noqa: E402

# Direct service calls skip the app lifespan, so create tables explicitly.
asyncio.run(init_db())


def test_flow_bridge_missing_graph_is_honest_error():
    out = asyncio.run(run_playbook({"kind": "flow", "graph_id": "nope", "mode": "dry_run"}, "u1"))
    assert isinstance(out, dict)
    assert out.get("status") == "error"


def test_flow_bridge_missing_graph_id_is_honest_error():
    out = asyncio.run(run_playbook({"kind": "flow"}, "u1"))
    assert isinstance(out, dict)
    assert out.get("status") == "error"


def test_strategy_bridge_missing_script_is_honest_error():
    out = asyncio.run(run_playbook({"kind": "strategy_host", "script_id": "nope"}, "u1"))
    assert isinstance(out, dict)
    assert out.get("status") == "error"


def test_unknown_kind_still_rejected():
    out = asyncio.run(run_playbook({"kind": "nope"}, "u1"))
    assert "error" in out
