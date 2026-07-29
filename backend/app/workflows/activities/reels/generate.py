"""Reel generation activity — wraps the orchestrator (quote→MP4) durably.

Phase 1 runs the whole generation as one activity (publishing is gated
separately by the workflow's human-review signal). Phase 4 can decompose this
into per-stage activities without changing the workflow signature.
"""

from __future__ import annotations

from typing import Any

import structlog
from temporalio import activity

from app.models.reel import ReelWorkflowInput

logger = structlog.get_logger(__name__)


@activity.defn
async def run_reel_generation(payload: ReelWorkflowInput) -> dict[str, Any]:
    """Generate the reel up to AWAITING_REVIEW (never auto-publishes here —
    the workflow owns the publish gate)."""
    activity.heartbeat({"stage": "generate"})
    from app.services.reels import reel_orchestrator

    info = activity.info()
    # Force auto_publish off — the workflow decides when to publish.
    gated = payload.model_copy(update={"auto_publish": False})
    result = await reel_orchestrator.generate_reel(
        gated, generation_id=info.workflow_id.replace("reel-", "") or None,
        workflow_id=info.workflow_id,
    )
    logger.info("reel_generation_activity_done", generation_id=result.generation_id,
                status=result.status, video_url=result.video_url)
    return result.model_dump(mode="json")
