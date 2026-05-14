"""Shared approval gate for PR #1 side-effect surfaces.

The approval queue is the canonical SecondBrain guardrail for actions that
write locally, call external services, or change the world. This helper keeps
new integrations honest: if the queue is available, create a pending approval;
if it is not available, block the side effect instead of executing silently.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def queue_side_effect_approval(
    *,
    tool_name: str,
    tier: str,
    summary: str,
    arguments: dict[str, Any],
    requested_by: str = "zero-api",
) -> dict[str, Any]:
    try:
        from app.services.approval_queue_service import get_approval_queue

        row = await get_approval_queue().request(
            tool_name=tool_name,
            tier=tier,
            summary=summary,
            arguments=arguments,
            requested_by=requested_by,
        )
        return {
            "status": "approval_required",
            "approval_id": row.id,
            "tier": row.tier,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "approval_queue_unavailable_blocking_side_effect",
            tool=tool_name,
            tier=tier,
            error=str(exc),
        )
        return {
            "status": "approval_required",
            "approval_id": None,
            "tier": tier,
            "error": "approval queue unavailable",
        }
