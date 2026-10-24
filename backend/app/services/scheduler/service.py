"""ScheduledResearchService: IANA-timezone-aware cron scheduling over the
``scheduled_research`` table.

``next_run_at`` is stored as timezone-aware UTC. ``due_tasks`` returns every
enabled schedule whose next run is at or before ``now``; callers (cron loop,
API trigger) use ``mark_run`` to advance the pointer. No absolute wall-clock
dependency: each schedule owns its timezone via ``zoneinfo.ZoneInfo``."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.models.schedule import ScheduledResearch, ScheduledRun
from app.db.session import SessionFactory
from app.services.scheduler.cron import CronError, parse_cron


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScheduledResearchService:
    async def create(
        self,
        user_id: str,
        name: str,
        playbook: dict,
        cron_expr: str,
        timezone_name: str = "UTC",
    ) -> dict:
        tz = self._validate_tz(timezone_name)
        spec = parse_cron(cron_expr)  # raises CronError on bad expression
        now = _utcnow()
        next_run = self._next_in_tz(spec, tz, now)
        async with SessionFactory() as session:
            row = ScheduledResearch(
                user_id=user_id,
                name=name,
                playbook=json.dumps(playbook),
                cron_expr=cron_expr,
                timezone=timezone_name,
                enabled=True,
                next_run_at=next_run,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._row_dict(row)

    async def list(self, user_id: str) -> list[dict]:
        async with SessionFactory() as session:
            rows = (
                await session.execute(
                    select(ScheduledResearch)
                    .where(ScheduledResearch.user_id == user_id)
                    .order_by(ScheduledResearch.created_at.desc())
                )
            ).scalars().all()
        return [self._row_dict(r) for r in rows]

    async def get(self, user_id: str, schedule_id: str) -> dict | None:
        async with SessionFactory() as session:
            row = (
                await session.execute(
                    select(ScheduledResearch).where(
                        ScheduledResearch.id == schedule_id, ScheduledResearch.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
        return self._row_dict(row) if row else None

    async def update(
        self,
        user_id: str,
        schedule_id: str,
        *,
        name: str | None = None,
        playbook: dict | None = None,
        cron_expr: str | None = None,
        timezone_name: str | None = None,
        enabled: bool | None = None,
    ) -> dict | None:
        async with SessionFactory() as session:
            row = (
                await session.execute(
                    select(ScheduledResearch).where(
                        ScheduledResearch.id == schedule_id, ScheduledResearch.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            if name is not None:
                row.name = name
            if playbook is not None:
                row.playbook = json.dumps(playbook)
            if cron_expr is not None:
                parse_cron(cron_expr)
                row.cron_expr = cron_expr
            if timezone_name is not None:
                self._validate_tz(timezone_name)
                row.timezone = timezone_name
            if enabled is not None:
                row.enabled = enabled
            row.next_run_at = self._next_in_tz(parse_cron(row.cron_expr), self._validate_tz(row.timezone), _utcnow())
            await session.commit()
            await session.refresh(row)
        return self._row_dict(row)

    async def delete(self, user_id: str, schedule_id: str) -> bool:
        async with SessionFactory() as session:
            row = (
                await session.execute(
                    select(ScheduledResearch).where(
                        ScheduledResearch.id == schedule_id, ScheduledResearch.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
        return True

    async def due_tasks(self, now: datetime | None = None) -> list[dict]:
        now = now or _utcnow()
        async with SessionFactory() as session:
            rows = (
                await session.execute(
                    select(ScheduledResearch).where(
                        ScheduledResearch.enabled.is_(True),
                        ScheduledResearch.next_run_at.is_not(None),
                        ScheduledResearch.next_run_at <= now,
                    )
                )
            ).scalars().all()
        return [self._row_dict(r) for r in rows]

    async def mark_run(self, schedule_id: str, finished: dict | None = None) -> None:
        """Advance next_run_at after a completed execution and store the run."""
        now = _utcnow()
        async with SessionFactory() as session:
            row = (
                await session.execute(
                    select(ScheduledResearch).where(ScheduledResearch.id == schedule_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            run = ScheduledRun(
                schedule_id=schedule_id,
                status=(finished or {}).get("status", "done"),
                output=json.dumps((finished or {}).get("output", {})),
                started_at=now,
                finished_at=_utcnow(),
            )
            session.add(run)
            next_run = self._next_in_tz(parse_cron(row.cron_expr), self._validate_tz(row.timezone), now)
            row.last_run_at = now
            row.next_run_at = next_run
            await session.commit()

    async def runs(self, user_id: str, schedule_id: str, limit: int = 20) -> list[dict]:
        async with SessionFactory() as session:
            rows = (
                await session.execute(
                    select(ScheduledRun)
                    .join(ScheduledResearch)
                    .where(ScheduledResearch.user_id == user_id, ScheduledRun.schedule_id == schedule_id)
                    .order_by(ScheduledRun.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        out = []
        for r in rows:
            value: object = r.output
            try:
                value = json.loads(r.output)
            except (ValueError, TypeError):
                pass
            out.append(
                {
                    "id": r.id,
                    "schedule_id": r.schedule_id,
                    "status": r.status,
                    "output": value,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out

    @staticmethod
    def _validate_tz(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone '{name}'") from exc

    @staticmethod
    def _next_in_tz(spec, tz: ZoneInfo, now: datetime) -> datetime:
        from app.services.scheduler.cron import next_occurrence

        local_now = now.astimezone(tz)
        return next_occurrence(spec, local_now).replace(tzinfo=tz).astimezone(timezone.utc)

    @staticmethod
    def _row_dict(row: ScheduledResearch) -> dict:
        playbook: object = row.playbook
        try:
            playbook = json.loads(row.playbook)
        except (ValueError, TypeError):
            pass
        return {
            "id": row.id,
            "name": row.name,
            "playbook": playbook,
            "cron_expr": row.cron_expr,
            "timezone": row.timezone,
            "enabled": row.enabled,
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


scheduled_research_service = ScheduledResearchService()
