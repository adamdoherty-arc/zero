"""Loop registry service — CRUD + due-time math for the cross-project loop framework.

Source of truth for which loops exist, how often they run, and what their
current variant + last result is. Read-heavy from the /api/loops surface;
write-heavy from the scheduler tick.

Cron evaluation is delegated to the `croniter` package which APScheduler
already pulls in transitively. We compute next_due_at lazily — when the
scheduler tick wakes up, it asks the registry "what's due in the next 5
minutes?" and the registry answers by walking enabled rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

import structlog
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    LoopModel,
    LoopRunModel,
    LoopVariantModel,
)
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_cron_time(cron_expr: str, *, after: Optional[datetime] = None) -> Optional[datetime]:
    """Compute the next fire time for a 5-field cron expression.

    Uses APScheduler's CronTrigger (already a project dep) so we don't pull
    in another cron parser. Returns None for sentinel values like 'manual'
    that indicate the loop should never auto-fire.
    """
    expr = (cron_expr or "").strip()
    if not expr or expr.lower() in {"manual", "off", "disabled", "none"}:
        return None
    base = after or _utcnow()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    try:
        trigger = CronTrigger.from_crontab(expr, timezone=timezone.utc)
        # APScheduler returns the next run time strictly AFTER `previous_fire_time`.
        return trigger.get_next_fire_time(None, base)
    except (ValueError, KeyError) as exc:
        logger.warning("loop.cron_invalid", cron=expr, error=str(exc))
        return None


class LoopRegistryService:
    """All registry reads and writes go through this service."""

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def list_loops(
        self,
        *,
        owner_project: Optional[str] = None,
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        async with get_session() as session:
            stmt = select(LoopModel).order_by(LoopModel.next_due_at.asc().nullslast(), LoopModel.id.asc())
            if owner_project:
                stmt = stmt.where(LoopModel.owner_project == owner_project)
            if enabled_only:
                stmt = stmt.where(LoopModel.enabled.is_(True))
            rows = (await session.execute(stmt)).scalars().all()
            return [self._serialize_loop(r) for r in rows]

    async def get_loop(self, loop_id: int) -> Optional[dict[str, Any]]:
        async with get_session() as session:
            row = await session.get(LoopModel, loop_id)
            return self._serialize_loop(row) if row else None

    async def get_loop_by_name(self, name: str) -> Optional[dict[str, Any]]:
        async with get_session() as session:
            stmt = select(LoopModel).where(LoopModel.name == name).limit(1)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return self._serialize_loop(row) if row else None

    async def list_runs(
        self,
        loop_id: int,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with get_session() as session:
            stmt = (
                select(LoopRunModel)
                .where(LoopRunModel.loop_id == loop_id)
                .order_by(LoopRunModel.started_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._serialize_run(r) for r in rows]

    async def get_run(self, run_id: int) -> Optional[dict[str, Any]]:
        async with get_session() as session:
            row = await session.get(LoopRunModel, run_id)
            if not row:
                return None
            payload = self._serialize_run(row)
            loop = await session.get(LoopModel, row.loop_id)
            if loop:
                payload["loop_name"] = loop.name
                payload["skill_name"] = loop.skill_name
                payload["owner_project"] = loop.owner_project
            return payload

    async def list_variants(self, loop_id: int) -> list[dict[str, Any]]:
        async with get_session() as session:
            stmt = (
                select(LoopVariantModel)
                .where(LoopVariantModel.loop_id == loop_id)
                .order_by(LoopVariantModel.created_at.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._serialize_variant(r) for r in rows]

    async def next_due_loops(
        self,
        *,
        within_seconds: int = 300,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Loops whose next_due_at is now-or-soon and which are enabled."""
        cutoff = _utcnow() + timedelta(seconds=within_seconds)
        async with get_session() as session:
            stmt = (
                select(LoopModel)
                .where(LoopModel.enabled.is_(True))
                .where(LoopModel.next_due_at.is_not(None))
                .where(LoopModel.next_due_at <= cutoff)
                .order_by(LoopModel.next_due_at.asc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._serialize_loop(r) for r in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def upsert_loop(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create or update a loop registry row by `name`."""
        name = payload["name"]
        async with get_session() as session:
            stmt = select(LoopModel).where(LoopModel.name == name).limit(1)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                row = LoopModel(
                    name=name,
                    owner_project=payload["owner_project"],
                    runner_kind=payload["runner_kind"],
                    runner_target=payload["runner_target"],
                    cron=payload.get("cron", "manual"),
                    enabled=payload.get("enabled", False),
                    sandbox_required=payload.get("sandbox_required", False),
                    judge_tier=payload.get("judge_tier", "local"),
                    auto_promote_enabled=payload.get("auto_promote_enabled", True),
                    daily_token_budget=payload.get("daily_token_budget", 200000),
                    daily_run_cap=payload.get("daily_run_cap", 48),
                    wall_clock_budget_s=payload.get("wall_clock_budget_s", 600),
                    description=payload.get("description"),
                    skill_name=payload.get("skill_name"),
                )
                row.next_due_at = _next_cron_time(row.cron) if row.enabled else None
                session.add(row)
                await session.commit()
                await session.refresh(row)
                logger.info("loop.created", name=name, owner=row.owner_project)
                return self._serialize_loop(row)

            for field in (
                "owner_project", "runner_kind", "runner_target", "cron",
                "enabled", "sandbox_required", "judge_tier",
                "auto_promote_enabled", "daily_token_budget",
                "daily_run_cap", "wall_clock_budget_s", "description",
                "skill_name",
            ):
                if field in payload:
                    setattr(existing, field, payload[field])
            if existing.enabled and existing.cron:
                existing.next_due_at = _next_cron_time(existing.cron)
            else:
                existing.next_due_at = None
            await session.commit()
            await session.refresh(existing)
            logger.info("loop.updated", name=name, enabled=existing.enabled)
            return self._serialize_loop(existing)

    async def set_enabled(self, loop_id: int, enabled: bool) -> Optional[dict[str, Any]]:
        async with get_session() as session:
            row = await session.get(LoopModel, loop_id)
            if not row:
                return None
            row.enabled = enabled
            row.next_due_at = _next_cron_time(row.cron) if enabled else None
            await session.commit()
            await session.refresh(row)
            logger.info("loop.set_enabled", loop_id=loop_id, enabled=enabled)
            return self._serialize_loop(row)

    async def reschedule(self, loop_id: int) -> None:
        """Recompute next_due_at after a successful run."""
        async with get_session() as session:
            row = await session.get(LoopModel, loop_id)
            if not row or not row.enabled:
                return
            row.next_due_at = _next_cron_time(row.cron)
            await session.commit()

    async def mark_run_started(
        self,
        loop_id: int,
        *,
        runner_kind: str,
        runner_id: Optional[str] = None,
        variant_id: Optional[int] = None,
    ) -> int:
        async with get_session() as session:
            run = LoopRunModel(
                loop_id=loop_id,
                variant_id=variant_id,
                runner_kind=runner_kind,
                runner_id=runner_id,
                status="running",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            await session.execute(
                update(LoopModel)
                .where(LoopModel.id == loop_id)
                .values(last_run_id=run.id, last_run_at=run.started_at)
            )
            await session.commit()
            return run.id

    async def mark_run_completed(
        self,
        run_id: int,
        *,
        status: str,
        judge_score: Optional[float] = None,
        judge_notes: Optional[str] = None,
        vault_path: Optional[str] = None,
        cost_tokens: Optional[int] = None,
        output: Optional[str] = None,
        error: Optional[str] = None,
        legion_run_id: Optional[int] = None,
        run_metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        async with get_session() as session:
            row = await session.get(LoopRunModel, run_id)
            if not row:
                return None
            now = _utcnow()
            row.ended_at = now
            row.status = status
            if row.started_at:
                started = row.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                row.duration_s = max(0.0, (now - started).total_seconds())
            if judge_score is not None:
                row.judge_score = judge_score
            if judge_notes is not None:
                row.judge_notes = judge_notes
            if vault_path is not None:
                row.vault_path = vault_path
            if cost_tokens is not None:
                row.cost_tokens = cost_tokens
            if output is not None:
                row.output = output
            if error is not None:
                row.error = error
            if legion_run_id is not None:
                row.legion_run_id = legion_run_id
            if run_metadata is not None:
                row.run_metadata = run_metadata
            await session.commit()
            await session.refresh(row)
            return self._serialize_run(row)

    # ------------------------------------------------------------------
    # Serializers
    # ------------------------------------------------------------------

    def _serialize_loop(self, row: LoopModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "owner_project": row.owner_project,
            "runner_kind": row.runner_kind,
            "runner_target": row.runner_target,
            "cron": row.cron,
            "enabled": row.enabled,
            "sandbox_required": row.sandbox_required,
            "judge_tier": row.judge_tier,
            "auto_promote_enabled": row.auto_promote_enabled,
            "current_variant_id": row.current_variant_id,
            "baseline_score": row.baseline_score,
            "consecutive_regressions": row.consecutive_regressions,
            "daily_token_budget": row.daily_token_budget,
            "daily_run_cap": row.daily_run_cap,
            "wall_clock_budget_s": row.wall_clock_budget_s,
            "last_run_id": row.last_run_id,
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "next_due_at": row.next_due_at.isoformat() if row.next_due_at else None,
            "description": row.description,
            "skill_name": row.skill_name,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _serialize_run(self, row: LoopRunModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "loop_id": row.loop_id,
            "variant_id": row.variant_id,
            "runner_kind": row.runner_kind,
            "runner_id": row.runner_id,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "duration_s": row.duration_s,
            "status": row.status,
            "judge_score": row.judge_score,
            "judge_notes": row.judge_notes,
            "vault_path": row.vault_path,
            "legion_run_id": row.legion_run_id,
            "cost_tokens": row.cost_tokens,
            "error": row.error,
            "output": row.output,
            "metadata": row.run_metadata or {},
        }

    def _serialize_variant(self, row: LoopVariantModel) -> dict[str, Any]:
        avg_score = (row.total_score / row.runs_count) if row.runs_count else None
        success_rate = (row.successes / row.runs_count) if row.runs_count else None
        return {
            "id": row.id,
            "loop_id": row.loop_id,
            "parent_id": row.parent_id,
            "variant_label": row.variant_label,
            "payload_kind": row.payload_kind,
            "payload": row.payload,
            "is_active": row.is_active,
            "is_canary": row.is_canary,
            "canary_traffic_pct": row.canary_traffic_pct,
            "runs_count": row.runs_count,
            "successes": row.successes,
            "total_score": row.total_score,
            "avg_score": avg_score,
            "success_rate": success_rate,
            "retired_at": row.retired_at.isoformat() if row.retired_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


@lru_cache(maxsize=1)
def get_loop_registry() -> LoopRegistryService:
    return LoopRegistryService()
