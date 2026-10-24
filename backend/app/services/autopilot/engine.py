"""AutopilotEngine — the supervisor that runs the agent squad as a mission.

A mission is an ordered DAG of the 7 agents. The engine persists a
``autopilot_runs`` row plus one ``autopilot_run_nodes`` row per agent phase,
so every mission is auditable and the frontend can render the live trace.

Missions:
- ``day-cycle`` : sentinel → signal → optionstrategy → riskgate → execute →
  selfreview → debrief (full autonomy: protect, hunt, trade).
- ``monitor``   : sentinel → riskgate → execute → selfreview → debrief (only
  protect what you already hold; no new ideas).

The engine itself never changes ``execution_mode``. Orders go through the paper
broker unless the account is LIVE_ENABLED (which the rest of the platform
already honours).
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.autopilot.agents import (
    Proposal,
    debrief_agent,
    execute_agent,
    optionstrategy_agent,
    riskgate_agent,
    selfreview_agent,
    sentinel_agent,
    signal_agent,
)
from app.services.autopilot.config import AutopilotConfig, load_config, save_config
from app.services.autopilot.store import autopilot_store
from app.services.memory.store import memory_store

logger = get_logger("autopilot.engine")


class AutopilotEngine:
    # ------------------------------------------------------------------ #
    # State & configuration
    # ------------------------------------------------------------------ #

    async def state(self, user_id: str) -> dict:
        config = await load_config(user_id)
        review = await memory_store.get(user_id, "autopilot:self_review")
        halt = bool(review and review["value"].get("halt_recommended")) if review else False
        runs = await autopilot_store.list_runs(user_id, limit=1)
        return {
            "enabled": config.enabled,
            "config": config.to_dict(),
            "mode": "PAPER",
            "halt_recommended": halt,
            "last_review": review["value"] if review else None,
            "last_run": runs[0] if runs else None,
        }

    async def save_config(self, user_id: str, config_dict: dict[str, Any]) -> dict:
        config = AutopilotConfig.from_dict(config_dict)
        await save_config(user_id, config)
        return {"saved": True, "config": config.to_dict()}

    async def toggle(self, user_id: str, enabled: bool) -> dict:
        config = await load_config(user_id)
        config.enabled = enabled
        await save_config(user_id, config)
        return {"enabled": enabled, "mode": "PAPER"}

    # ------------------------------------------------------------------ #
    # Missions
    # ------------------------------------------------------------------ #

    async def run(self, user_id: str, *, monitor_only: bool = False) -> dict:
        config = await load_config(user_id)
        mission = "monitor" if monitor_only else "day-cycle"
        run = await autopilot_store.create_run(user_id, mission)
        run_id = run.id
        position = 0
        evidence: dict[str, dict] = {}

        async def record(phase: str, agent_name: str, data: dict) -> None:
            nonlocal position
            position += 1
            await autopilot_store.add_node(
                run_id, position=position, phase=phase, agent=agent_name, status="done", evidence=data
            )

        try:
            # 1. Protect what we already hold.
            sentinel = await sentinel_agent(user_id, config)
            await record("sentinel", "sentinel", sentinel)
            evidence["sentinel"] = sentinel
            proposals = [Proposal(**p) for p in sentinel.get("proposals", [])]

            signal_ev: dict | None = None
            options_ev: dict | None = None

            # 2. Hunt for new ideas (skipped in monitor-only mode).
            if not monitor_only:
                signal_ev = await signal_agent(config)
                await record("signal", "signal", signal_ev)
                evidence["signal"] = signal_ev
                candidates = signal_ev.get("candidates", [])
                for c in candidates[: config.max_new_entries]:
                    if c.get("direction") == "LONG":
                        proposals.append(
                            Proposal(
                                symbol=c["symbol"],
                                side="BUY",
                                action="entry",
                                reason="entry-signal: " + ", ".join(c.get("reasons", []))[:200],
                                qty=max(int(config.entry_qty), 1),
                                detail={"strength": c.get("strength"), "direction": c.get("direction")},
                            )
                        )
                # 3. Turn chain bias into tracked F&O plays.
                if config.option_enabled:
                    options_ev = await optionstrategy_agent(config, [c["symbol"] for c in candidates])
                    await record("optionstrategy", "options", options_ev)
                    evidence["options"] = options_ev

            # 4. Gate every proposal through the risk engine + live state.
            gate = await riskgate_agent(user_id, config, proposals)
            await record("riskgate", "riskgate", gate)
            evidence["gate"] = gate

            # 5. Execute approved actions (paper broker + tracked option legs).
            executes = await execute_agent(
                user_id,
                gate.get("approved", []),
                options_ev.get("plays") if options_ev else None,
            )
            await record("execute", "execute", executes)
            evidence["execute"] = executes

            # 6. Self-analysis: score the mission, write the journal + memory.
            review = await selfreview_agent(
                user_id,
                mission,
                sentinel_evidence=sentinel,
                fills=executes.get("fills", []),
                rejects=executes.get("rejects", []),
                option_tracks=executes.get("option_tracks", []),
            )
            await record("selfreview", "selfreview", review)
            evidence["review"] = review

            # 7. Debrief: compose the human-readable report.
            report = debrief_agent(
                mission=mission,
                run_id=run_id,
                sentinel_evidence=sentinel,
                signal_evidence=signal_ev,
                options_evidence=options_ev,
                gate_evidence=gate,
                execute_evidence=executes,
                review=review,
            )
            await record("debrief", "debrief", {"report": report})

            status = "halted" if review["halt_recommended"] else "completed"
            summary: dict[str, Any] = {
                "mission": mission,
                "status": status,
                "n_fills": len(executes.get("fills", [])),
                "n_rejects": len(executes.get("rejects", [])),
                "n_option_tracks": len(executes.get("option_tracks", [])),
                "n_candidates": len(signal_ev.get("candidates", [])) if signal_ev else 0,
                "n_positions_monitored": len(sentinel.get("monitored", [])),
                "score": review["score"],
                "realised_pnl": review["realised_pnl"],
            }
            await autopilot_store.finish_run(run_id, status=status, summary=summary, report=report)
        except Exception as exc:  # noqa: BLE001
            logger.exception("autopilot mission %s failed", mission)
            await autopilot_store.finish_run(run_id, status="failed", error=str(exc))

        return await autopilot_store.get_run(user_id, run_id)

    async def list_runs(self, user_id: str, limit: int = 20) -> list[dict]:
        return await autopilot_store.list_runs(user_id, limit=limit)

    async def get_run(self, user_id: str, run_id: str) -> dict | None:
        return await autopilot_store.get_run(user_id, run_id)


autopilot_engine = AutopilotEngine()