"""Persisted hard-freeze controls for carousel/media/image production."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog
from pydantic import BaseModel, Field

from app.db.models import ServiceConfigModel
from app.infrastructure.database import get_session
from app.infrastructure.exceptions import ContentProductionPausedError

logger = structlog.get_logger(__name__)


CONFIG_KEY = "content_production_control"
DEFAULT_REASON = (
    "Content production hard freeze is enabled by default. Resume from Settings "
    "> Content Production when carousel/media/image development should restart."
)

AFFECTED_JOB_IDS: tuple[str, ...] = (
    "autonomous_content_loop",
    "character_content_generation",
    "character_content_gate",
    "carousel_watchdog",
    "carousel_reaudit",
    "carousel_banned_hook_backfill",
    "character_auto_approval",
    "character_publish_backlog",
    "character_auto_publish",
    "character_auto_research",
    "character_research_retry",
    "character_research_refresh",
    "character_gap_audit",
    "character_hook_audit",
    "character_discovery",
    "character_discovery_refvideos",
    "character_reference_video_processor",
    "character_reference_video_learning",
    "character_image_cleanup",
    "entity_research_deepen",
    "media_auto_research",
    "media_content_generation",
    "media_release_prep",
    "character_release_prep",
    "character_content_learning",
    "brain_content_learn",
    "brain_prompt_breed",
    "brain_prompt_evolve",
)


class ContentProductionPolicy(BaseModel):
    paused: bool = True
    reason: str = DEFAULT_REASON
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_by: str = "system"
    affected_job_ids: List[str] = Field(default_factory=lambda: list(AFFECTED_JOB_IDS))
    previous_job_states: Dict[str, bool] = Field(default_factory=dict)
    last_scheduler_sync_at: Optional[str] = None


class ContentProductionControlService:
    """Owns the persisted content-production hard freeze.

    The policy defaults to paused and is stored in ``service_configs`` so it
    survives API restarts and keeps scheduler/UI state consistent.
    """

    affected_job_ids = AFFECTED_JOB_IDS

    async def get_policy(self) -> ContentProductionPolicy:
        async with get_session() as session:
            row = await session.get(ServiceConfigModel, CONFIG_KEY)
            if row is None:
                policy = ContentProductionPolicy(
                    previous_job_states=await self._default_job_states(),
                )
                session.add(ServiceConfigModel(service_name=CONFIG_KEY, config=policy.model_dump()))
                await session.commit()
                logger.warning("content_production_policy_created", paused=policy.paused)
                return policy

            config = row.config or {}
            policy = ContentProductionPolicy.model_validate({
                **config,
                "affected_job_ids": list(AFFECTED_JOB_IDS),
            })
            # Keep older rows current as the affected job list evolves.
            if config.get("affected_job_ids") != list(AFFECTED_JOB_IDS):
                row.config = policy.model_dump()
                row.updated_at = datetime.now(timezone.utc)
                await session.commit()
            return policy

    async def get_status(self) -> Dict[str, Any]:
        policy = await self.get_policy()
        jobs = await self._scheduler_jobs_snapshot()
        return {
            **policy.model_dump(),
            "affected_jobs": [
                job for job in jobs if str(job.get("id")) in set(AFFECTED_JOB_IDS)
            ],
        }

    async def set_paused(
        self,
        paused: bool,
        *,
        reason: Optional[str] = None,
        restore_previous_jobs: bool = True,
        updated_by: str = "user",
    ) -> Dict[str, Any]:
        policy = await self.get_policy()
        now = datetime.now(timezone.utc).isoformat()
        next_policy = policy.model_copy(deep=True)
        next_policy.paused = bool(paused)
        next_policy.reason = reason or (DEFAULT_REASON if paused else "Content production resumed.")
        next_policy.updated_at = now
        next_policy.updated_by = updated_by
        next_policy.affected_job_ids = list(AFFECTED_JOB_IDS)

        scheduler_result: Dict[str, Any] = {}
        if paused:
            if not policy.paused or not policy.previous_job_states:
                next_policy.previous_job_states = await self._capture_job_states()
            scheduler_result = await self._set_affected_jobs_enabled(False)
            next_policy.last_scheduler_sync_at = datetime.now(timezone.utc).isoformat()
        else:
            desired = self._restore_states_from_policy(policy, restore_previous_jobs)
            scheduler_result = await self._apply_job_state_map(desired)
            next_policy.last_scheduler_sync_at = datetime.now(timezone.utc).isoformat()

        await self._save_policy(next_policy)
        status = await self.get_status()
        status["scheduler_result"] = scheduler_result
        return status

    async def sync_scheduler_with_policy(self) -> Dict[str, Any]:
        policy = await self.get_policy()
        if not policy.paused:
            return {"paused": False, "synced": False, "reason": "content_production_unpaused"}

        next_policy = policy.model_copy(deep=True)
        if not next_policy.previous_job_states:
            next_policy.previous_job_states = await self._capture_job_states()
        result = await self._set_affected_jobs_enabled(False)
        next_policy.last_scheduler_sync_at = datetime.now(timezone.utc).isoformat()
        await self._save_policy(next_policy)
        return {"paused": True, "synced": True, "scheduler_result": result}

    async def is_paused(self) -> bool:
        return bool((await self.get_policy()).paused)

    async def ensure_allowed(self, action: str) -> None:
        policy = await self.get_policy()
        if policy.paused:
            raise ContentProductionPausedError(action=action, reason=policy.reason)

    async def job_blocked(self, job_name: str) -> bool:
        if job_name not in AFFECTED_JOB_IDS:
            return False
        return await self.is_paused()

    async def _save_policy(self, policy: ContentProductionPolicy) -> None:
        async with get_session() as session:
            row = await session.get(ServiceConfigModel, CONFIG_KEY)
            if row is None:
                session.add(ServiceConfigModel(service_name=CONFIG_KEY, config=policy.model_dump()))
            else:
                row.config = policy.model_dump()
                row.updated_at = datetime.now(timezone.utc)
            await session.commit()

    async def _scheduler_jobs_snapshot(self) -> List[Dict[str, Any]]:
        try:
            from app.services.scheduler_service import get_scheduler_service

            return list(get_scheduler_service().get_status().get("jobs") or [])
        except Exception as exc:  # noqa: BLE001
            logger.debug("content_production_scheduler_snapshot_failed", error=str(exc))
            return []

    async def _capture_job_states(self) -> Dict[str, bool]:
        jobs = await self._scheduler_jobs_snapshot()
        by_id = {str(job.get("id")): bool(job.get("enabled")) for job in jobs}
        return {job_id: by_id.get(job_id, True) for job_id in AFFECTED_JOB_IDS}

    def _restore_states_from_policy(
        self,
        policy: ContentProductionPolicy,
        restore_previous_jobs: bool,
    ) -> Dict[str, bool]:
        if restore_previous_jobs and policy.previous_job_states:
            return {
                job_id: bool(policy.previous_job_states.get(job_id, True))
                for job_id in AFFECTED_JOB_IDS
            }
        return {job_id: True for job_id in AFFECTED_JOB_IDS}

    async def _set_affected_jobs_enabled(self, enabled: bool) -> Dict[str, Any]:
        return await self._apply_job_state_map({job_id: enabled for job_id in AFFECTED_JOB_IDS})

    async def _apply_job_state_map(self, states: Dict[str, bool]) -> Dict[str, Any]:
        try:
            from app.services.scheduler_service import get_scheduler_service

            scheduler = get_scheduler_service()
            updated: list[dict[str, Any]] = []
            for enabled in (False, True):
                job_names = [
                    job_id
                    for job_id, desired_enabled in states.items()
                    if bool(desired_enabled) == enabled
                ]
                if not job_names:
                    continue
                result = await scheduler.set_jobs_enabled(job_names, enabled)
                updated.extend(result.get("updated") or [])
                if not result.get("success", False):
                    logger.warning(
                        "content_production_scheduler_apply_partial",
                        enabled=enabled,
                        result=result,
                    )
            return {"success": True, "updated": updated, "count": len(updated)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("content_production_scheduler_apply_failed", error=str(exc))
            return {"success": False, "error": str(exc), "updated": [], "count": 0}

    async def _default_job_states(self) -> Dict[str, bool]:
        jobs = await self._scheduler_jobs_snapshot()
        by_id = {str(job.get("id")): job for job in jobs}
        return {
            job_id: bool(by_id.get(job_id, {}).get("default_enabled", True))
            for job_id in AFFECTED_JOB_IDS
        }


@lru_cache()
def get_content_production_control_service() -> ContentProductionControlService:
    return ContentProductionControlService()


async def ensure_content_production_allowed(action: str) -> None:
    await get_content_production_control_service().ensure_allowed(action)
