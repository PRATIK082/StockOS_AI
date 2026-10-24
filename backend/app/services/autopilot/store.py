"""Persistence for autopilot runs and per-agent node traces.

Stateless service: every call opens its own short session via SessionFactory,
mirroring ``app/services/memory/store.py``. Full mission telemetry lives in
``autopilot_runs`` / ``autopilot_run_nodes``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db.models import AutopilotRun, AutopilotRunNode
from app.db.session import SessionFactory


class AutopilotStore:
    async def create_run(
        self, user_id: str, mission: str, started_at: datetime | None = None
    ) -> AutopilotRun:
        run = AutopilotRun(
            user_id=user_id,
            mission=mission,
            status="running",
            started_at=started_at or datetime.utcnow(),
        )
        async with SessionFactory() as session:
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return run

    async def add_node(
        self,
        run_id: str,
        *,
        position: int,
        phase: str,
        agent: str,
        status: str = "done",
        evidence: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AutopilotRunNode:
        node = AutopilotRunNode(
            run_id=run_id,
            position=position,
            phase=phase,
            agent=agent,
            status=status,
            evidence_json=json.dumps(evidence) if evidence is not None else None,
            error=error,
        )
        async with SessionFactory() as session:
            session.add(node)
            await session.commit()
            await session.refresh(node)
            return node

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: dict[str, Any] | None = None,
        report: str | None = None,
        error: str | None = None,
    ) -> AutopilotRun:
        async with SessionFactory() as session:
            run = await session.get(AutopilotRun, run_id)
            if run is None:
                raise ValueError(f"AutopilotRun {run_id} not found")
            run.status = status
            run.summary_json = json.dumps(summary) if summary is not None else None
            run.report = report
            run.error = error
            run.finished_at = datetime.utcnow()
            await session.commit()
            return run

    async def get_run(self, user_id: str, run_id: str) -> dict | None:
        async with SessionFactory() as session:
            run = await session.get(AutopilotRun, run_id)
            if run is None or run.user_id != user_id:
                return None
            nodes = (
                await session.scalars(
                    select(AutopilotRunNode)
                    .where(AutopilotRunNode.run_id == run.id)
                    .order_by(AutopilotRunNode.position.asc())
                )
            ).all()
        return self._run_dict(run, nodes)

    async def list_runs(self, user_id: str, limit: int = 20) -> list[dict]:
        async with SessionFactory() as session:
            runs = (
                await session.scalars(
                    select(AutopilotRun)
                    .where(AutopilotRun.user_id == user_id)
                    .order_by(AutopilotRun.started_at.desc())
                    .limit(limit)
                )
            ).all()
        return [
            {
                "id": r.id,
                "mission": r.mission,
                "status": r.status,
                "error": r.error,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "summary": None,
                "node_count": 0,
            }
            for r in runs
        ]

    @staticmethod
    def _run_dict(run: AutopilotRun, nodes: list[AutopilotRunNode]) -> dict:
        node_rows = []
        for n in nodes:
            evidence: Any = n.evidence_json
            if evidence:
                try:
                    evidence = json.loads(evidence)
                except (ValueError, TypeError):
                    evidence = None
            node_rows.append(
                {
                    "id": n.id,
                    "position": n.position,
                    "phase": n.phase,
                    "agent": n.agent,
                    "status": n.status,
                    "evidence": evidence,
                    "error": n.error,
                }
            )
        summary: Any = run.summary_json
        if summary:
            try:
                summary = json.loads(summary)
            except (ValueError, TypeError):
                summary = None
        return {
            "id": run.id,
            "mission": run.mission,
            "status": run.status,
            "error": run.error,
            "summary": summary,
            "report": run.report,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "nodes": node_rows,
        }


autopilot_store = AutopilotStore()