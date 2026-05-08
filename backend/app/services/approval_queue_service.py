"""Approval Queue — gates every write_external or financial tool call.

Phase 3 of the SecondBrain plan (§6 guardrails). Any tool decorated with
`@requires_approval(tier=...)` goes through this queue:

  agent             approval_queue           user (UI or auto)
   │  request(tier)     │                       │
   ├────────────────────►                       │
   │                    │  status=pending ──────►
   │                    │                       │
   │                    ◄──── approve / reject ─┤
   │  result ◄──────────┤                       │
   │                    │                       │

Tier ladder (SecondBrain §6):
    read           — never gated
    write_local    — gated only in DRY_RUN mode
    write_external — always gated
    financial      — always gated, shorter expiry
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import structlog
from sqlalchemy import select, update

from app.db.models import AgentApprovalModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


_TIER_EXPIRY = {
    "read": timedelta(minutes=5),
    "write_local": timedelta(hours=2),
    "write_external": timedelta(hours=6),
    "financial": timedelta(minutes=30),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalQueueService:
    def __init__(self) -> None:
        self._settings = get_settings()

    def _requires_gate(self, tier: str) -> bool:
        """Should this tier pause for human approval?"""
        if tier in ("write_external", "financial"):
            return True
        if tier == "write_local" and getattr(self._settings, "dry_run", False):
            return True
        return False

    async def request(
        self,
        *,
        tool_name: str,
        tier: str,
        summary: str,
        arguments: dict[str, Any],
        requested_by: str,
    ) -> AgentApprovalModel:
        expires_at = _now() + _TIER_EXPIRY.get(tier, timedelta(hours=2))
        row = AgentApprovalModel(
            id=f"ap-{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            tier=tier,
            summary=summary,
            arguments=arguments,
            requested_by=requested_by,
            status="pending",
            expires_at=expires_at,
        )
        async with get_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        logger.info(
            "approval_requested",
            id=row.id,
            tool=tool_name,
            tier=tier,
            requester=requested_by,
        )
        return row

    async def decide(
        self,
        *,
        approval_id: str,
        status: str,
        decided_by: str,
        reason: Optional[str] = None,
    ) -> Optional[AgentApprovalModel]:
        if status not in ("approved", "rejected"):
            raise ValueError(f"invalid decision status: {status!r}")
        async with get_session() as session:
            result = await session.execute(
                update(AgentApprovalModel)
                .where(
                    AgentApprovalModel.id == approval_id,
                    AgentApprovalModel.status == "pending",
                )
                .values(
                    status=status,
                    decided_by=decided_by,
                    decision_reason=reason,
                    decided_at=_now(),
                )
                .returning(AgentApprovalModel)
            )
            row = result.scalar_one_or_none()
            await session.commit()
        if row:
            logger.info("approval_decided", id=approval_id, status=status, decided_by=decided_by)
        return row

    async def list(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[AgentApprovalModel]:
        async with get_session() as session:
            q = select(AgentApprovalModel).order_by(AgentApprovalModel.created_at.desc()).limit(limit)
            if status:
                q = q.where(AgentApprovalModel.status == status)
            result = await session.execute(q)
            return list(result.scalars().all())

    async def get(self, approval_id: str) -> Optional[AgentApprovalModel]:
        async with get_session() as session:
            return await session.get(AgentApprovalModel, approval_id)

    async def expire_stale(self) -> int:
        """Mark pending approvals past their expiry as expired."""
        async with get_session() as session:
            result = await session.execute(
                update(AgentApprovalModel)
                .where(
                    AgentApprovalModel.status == "pending",
                    AgentApprovalModel.expires_at < _now(),
                )
                .values(status="expired", decided_at=_now(), decided_by="system")
                .returning(AgentApprovalModel.id)
            )
            ids = [r[0] for r in result.all()]
            await session.commit()
        if ids:
            logger.info("approvals_expired", count=len(ids), ids=ids[:10])
        return len(ids)

    async def gated_call(
        self,
        *,
        tool_name: str,
        tier: str,
        summary: str,
        arguments: dict[str, Any],
        requested_by: str,
        execute: Callable[[], Awaitable[Any]],
        wait_timeout_seconds: int = 0,
    ) -> dict[str, Any]:
        """Helper: pause, queue, optionally wait for approval, then execute.

        If `wait_timeout_seconds > 0`, polls every 5s for approval and executes
        inline on approve. Otherwise returns immediately with approval_id and
        the caller polls later.
        """
        if not self._requires_gate(tier):
            result = await execute()
            return {"status": "executed_direct", "result": result}

        approval = await self.request(
            tool_name=tool_name,
            tier=tier,
            summary=summary,
            arguments=arguments,
            requested_by=requested_by,
        )
        if wait_timeout_seconds <= 0:
            return {"status": "pending", "approval_id": approval.id}

        deadline = asyncio.get_event_loop().time() + wait_timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(5)
            fresh = await self.get(approval.id)
            if fresh is None:
                return {"status": "missing", "approval_id": approval.id}
            if fresh.status == "approved":
                try:
                    result = await execute()
                    async with get_session() as session:
                        await session.execute(
                            update(AgentApprovalModel)
                            .where(AgentApprovalModel.id == approval.id)
                            .values(executed_at=_now(), status="executed", result={"value": str(result)[:2000]})
                        )
                        await session.commit()
                    return {"status": "executed", "approval_id": approval.id, "result": result}
                except Exception as e:  # noqa: BLE001
                    async with get_session() as session:
                        await session.execute(
                            update(AgentApprovalModel)
                            .where(AgentApprovalModel.id == approval.id)
                            .values(status="failed", error=str(e), executed_at=_now())
                        )
                        await session.commit()
                    return {"status": "failed", "approval_id": approval.id, "error": str(e)}
            if fresh.status in ("rejected", "expired"):
                return {"status": fresh.status, "approval_id": approval.id}
        return {"status": "timeout", "approval_id": approval.id}


_singleton: Optional[ApprovalQueueService] = None


def get_approval_queue() -> ApprovalQueueService:
    global _singleton
    if _singleton is None:
        _singleton = ApprovalQueueService()
    return _singleton
