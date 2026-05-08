"""AnalyticsLoop scheduling activity.

Phase 6: writes a placeholder ``engagement_signals`` row at t=0 so the
``character_performance_sync`` scheduler job (already wired in
``scheduler_service.py``) picks it up on the next 6h tick. The scheduler
performs the real polling (every 6h × 48h, daily × 14d, weekly × 60d)
because Temporal cron + a long-running poll is overkill at our cadence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@activity.defn
async def schedule_polls(publish_result: dict[str, Any]) -> None:
    activity.heartbeat({"stage": "analytics_schedule"})

    publish_id = publish_result.get("publish_id")
    generation_id = publish_result.get("generation_id")
    carousel_id = publish_result.get("carousel_id")
    if not (publish_id and generation_id):
        logger.info("analytics_schedule_skipped", reason="no_publish_id")
        return

    try:
        from app.db.models import EngagementSignalModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            session.add(
                EngagementSignalModel(
                    id=uuid.uuid4().hex,
                    generation_id=generation_id,
                    carousel_id=carousel_id or generation_id,
                    publish_id=publish_id,
                    t_offset_h=0,
                    source="schedule_seed",
                    sampled_at=datetime.now(timezone.utc),
                )
            )
            await session.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("analytics_seed_failed", error=str(exc))

    logger.info(
        "carousel_analytics_scheduled",
        generation_id=generation_id,
        publish_id=publish_id,
    )
