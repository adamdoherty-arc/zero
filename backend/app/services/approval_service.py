"""Approval service — human-in-the-loop request management."""
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, Any, List, Optional
from uuid import uuid4

from sqlalchemy import select, desc, and_, func
import structlog

from app.db.models import ApprovalRequestModel
from app.infrastructure.database import get_session

logger = structlog.get_logger()


def _ulid() -> str:
    ts = int(time.time() * 1000)
    return f"{ts:013x}-{uuid4().hex[:12]}"


class ApprovalService:
    async def create_approval_request(
        self, request_type: str, title: str,
        description: Optional[str] = None,
        context_data: Optional[dict] = None,
        initiated_by: str = "system",
        route: Optional[str] = None,
        expires_in_hours: int = 24,
        auto_action_on_expiry: str = "reject",
    ) -> Dict[str, Any]:
        req_id = _ulid()
        async with get_session() as session:
            row = ApprovalRequestModel(
                id=req_id,
                request_type=request_type,
                title=title,
                description=description,
                context_data=context_data,
                initiated_by=initiated_by,
                route=route,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
                auto_action_on_expiry=auto_action_on_expiry,
            )
            session.add(row)
        logger.info("approval_request_created", id=req_id, type=request_type, title=title)
        return await self.get_request(req_id)

    async def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        async with get_session() as session:
            row = (await session.execute(
                select(ApprovalRequestModel).where(ApprovalRequestModel.id == request_id)
            )).scalar_one_or_none()
            return self._to_dict(row) if row else None

    async def list_pending(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with get_session() as session:
            stmt = (
                select(ApprovalRequestModel)
                .where(ApprovalRequestModel.status == "pending")
                .order_by(desc(ApprovalRequestModel.created_at))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._to_dict(r) for r in rows]

    async def list_all(self, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        async with get_session() as session:
            conditions = []
            if status:
                conditions.append(ApprovalRequestModel.status == status)
            where = and_(*conditions) if conditions else True
            total = (await session.execute(
                select(func.count()).select_from(ApprovalRequestModel).where(where)
            )).scalar() or 0
            stmt = (
                select(ApprovalRequestModel)
                .where(where)
                .order_by(desc(ApprovalRequestModel.created_at))
                .offset(offset).limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return {"items": [self._to_dict(r) for r in rows], "total": total}

    async def approve(self, request_id: str, decision_by: str = "user", reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return await self._decide(request_id, "approved", decision_by, reason)

    async def reject(self, request_id: str, decision_by: str = "user", reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return await self._decide(request_id, "rejected", decision_by, reason)

    async def _decide(self, request_id: str, status: str, decision_by: str, reason: Optional[str]) -> Optional[Dict[str, Any]]:
        async with get_session() as session:
            row = (await session.execute(
                select(ApprovalRequestModel).where(ApprovalRequestModel.id == request_id)
            )).scalar_one_or_none()
            if not row or row.status != "pending":
                return None
            row.status = status
            row.decision_by = decision_by
            row.decision_reason = reason
            row.decided_at = datetime.now(timezone.utc)
        logger.info("approval_decided", id=request_id, status=status, by=decision_by)
        return await self.get_request(request_id)

    async def auto_expire_check(self) -> int:
        """Expire pending requests past their expiry time. Returns count expired."""
        now = datetime.now(timezone.utc)
        expired_count = 0
        async with get_session() as session:
            stmt = (
                select(ApprovalRequestModel)
                .where(and_(
                    ApprovalRequestModel.status == "pending",
                    ApprovalRequestModel.expires_at <= now,
                ))
            )
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                row.status = row.auto_action_on_expiry or "rejected"
                row.decision_by = "auto_expire"
                row.decision_reason = "Expired without decision"
                row.decided_at = now
                expired_count += 1
        if expired_count:
            logger.info("approvals_expired", count=expired_count)
        return expired_count

    async def get_stats(self) -> Dict[str, Any]:
        async with get_session() as session:
            stmt = select(
                ApprovalRequestModel.status,
                func.count().label("count"),
            ).group_by(ApprovalRequestModel.status)
            rows = (await session.execute(stmt)).all()
            by_status = {r.status: r.count for r in rows}

            # Calculate average decision time for decided requests
            avg_hours = 0.0
            decided_stmt = select(
                func.avg(
                    func.extract('epoch', ApprovalRequestModel.decided_at) -
                    func.extract('epoch', ApprovalRequestModel.created_at)
                ).label("avg_seconds")
            ).where(ApprovalRequestModel.decided_at.isnot(None))
            avg_row = (await session.execute(decided_stmt)).scalar()
            if avg_row:
                avg_hours = round(avg_row / 3600, 1)

            return {
                "total": sum(by_status.values()),
                "by_status": by_status,
                "pending": by_status.get("pending", 0),
                "approved": by_status.get("approved", 0),
                "rejected": by_status.get("rejected", 0),
                "expired": by_status.get("expired", 0),
                "avg_decision_time_hours": avg_hours,
            }

    def _to_dict(self, row) -> Dict[str, Any]:
        return {
            "id": row.id,
            "request_type": row.request_type,
            "title": row.title,
            "description": row.description,
            "context_data": row.context_data,
            "initiated_by": row.initiated_by,
            "route": row.route,
            "status": row.status,
            "decision_by": row.decision_by,
            "decision_reason": row.decision_reason,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "auto_action_on_expiry": row.auto_action_on_expiry,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


@lru_cache()
def get_approval_service() -> ApprovalService:
    return ApprovalService()
