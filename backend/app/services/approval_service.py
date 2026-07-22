"""Approval service — human-in-the-loop request management."""
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, Any, List, Optional
from uuid import uuid4

from sqlalchemy import select, desc, and_, case, or_, func, update as sql_update
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
            # Fix-128 (ACT-B2): exclude logically-expired-but-unswept rows.
            # auto_expire_check only runs on a schedule, so a `pending` row can
            # sit past its expires_at for up to a full sweep interval. The UI
            # (and any dedup that feeds off this list) must not treat a dead
            # approval as a live gate. Mirrors approval_queue_service.list()'s
            # Fix-123 (A2) expiry filter on the pending bucket.
            now = datetime.now(timezone.utc)
            stmt = (
                select(ApprovalRequestModel)
                .where(
                    ApprovalRequestModel.status == "pending",
                    or_(
                        ApprovalRequestModel.expires_at.is_(None),
                        ApprovalRequestModel.expires_at >= now,
                    ),
                )
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
        # Atomic claim (Fix-116): UPDATE ... WHERE status='pending' so two
        # concurrent decisions (UI double-submit, or an approve racing the
        # hourly expiry job) cannot both pass a stale "pending" read and
        # double-write the decision/audit fields. Mirrors the correct
        # approval_queue_service.decide. Returns None when the row was already
        # claimed by the winning caller.
        # Fix-128 (ACT-B1): an "approve" must not green-light a logically-
        # expired request. auto_expire_check() only runs on a schedule, so a
        # pending-but-expired row can survive up to a full sweep interval;
        # without this guard a human (or polling caller) could mark it approved,
        # producing a phantom approval a downstream gated waiter would execute.
        # Rejecting an expired request stays allowed (it is already effectively
        # denied). Exact mirror of approval_queue_service.decide's Fix-123 (A1).
        now = datetime.now(timezone.utc)
        predicates = [
            ApprovalRequestModel.id == request_id,
            ApprovalRequestModel.status == "pending",
        ]
        if status == "approved":
            predicates.append(
                or_(
                    ApprovalRequestModel.expires_at.is_(None),
                    ApprovalRequestModel.expires_at >= now,
                )
            )
        async with get_session() as session:
            result = await session.execute(
                sql_update(ApprovalRequestModel)
                .where(*predicates)
                .values(
                    status=status,
                    decision_by=decision_by,
                    decision_reason=reason,
                    decided_at=now,
                )
                .returning(ApprovalRequestModel.id)
            )
            claimed = result.scalar_one_or_none()
            await session.commit()
        if claimed is None:
            if status == "approved":
                logger.info("approval_approve_refused_expired", id=request_id)
            return None
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
                # auto_action_on_expiry holds an ACTION verb ("reject"/"approve");
                # normalize to the canonical status taxonomy that get_stats()
                # and list filters bucket on (rejected/approved/expired).
                action = (row.auto_action_on_expiry or "").strip().lower()
                # SECURITY (Fix-116): an approval gate MUST fail-safe on timeout.
                # Never auto-APPROVE on expiry — that would let an unattended
                # write_external / financial request execute with no human in
                # the loop. Only an explicit "reject" is honored; everything
                # else (including a mistakenly-configured "approve") collapses
                # to the inert "expired" state.
                target_status = {
                    "reject": "rejected",
                    "rejected": "rejected",
                }.get(action, "expired")
                # Fix-119 (ACT-2): use a guarded UPDATE ... WHERE status='pending'
                # (mirroring _decide's atomic claim) instead of mutating the ORM
                # object loaded above. The old path committed status='expired' via
                # an UPDATE-by-PK with NO status re-check, so a user approve()/
                # reject() that committed between this SELECT and its commit was
                # silently clobbered back to 'expired' and its decision_by
                # overwritten to 'auto_expire', destroying the human decision +
                # audit record. The guard lets a concurrent decision win.
                result = await session.execute(
                    sql_update(ApprovalRequestModel)
                    .where(
                        ApprovalRequestModel.id == row.id,
                        ApprovalRequestModel.status == "pending",
                    )
                    .values(
                        status=target_status,
                        decision_by="auto_expire",
                        decision_reason="Expired without decision",
                        decided_at=now,
                    )
                    .returning(ApprovalRequestModel.id)
                )
                if result.scalar_one_or_none() is not None:
                    expired_count += 1
        if expired_count:
            logger.info("approvals_expired", count=expired_count)
        return expired_count

    async def get_stats(self) -> Dict[str, Any]:
        async with get_session() as session:
            # A-2 (supervise zero 6a8c5562): this bucketed on the raw DB status
            # string with no expiry predicate, while list_pending() (above) got
            # the Fix-128 filter. auto_expire_check only runs hourly and the
            # default TTL is 24h, so the two disagreed for up to a full sweep:
            # OrchestratorPage renders this `pending` count in a tile directly
            # above the usePendingApprovals() list, so the badge could read
            # "3 Pending" over a list showing 1. One trust boundary, one
            # definition of pending — logically-expired rows count as expired.
            # Bucket on the EFFECTIVE status rather than the stored one, in the
            # same single group_by — a logically-expired `pending` row counts as
            # expired here exactly as it does in list_pending(), with no extra
            # round trip and no second definition of "pending" to drift.
            now = datetime.now(timezone.utc)
            _effective_status = case(
                (
                    and_(
                        ApprovalRequestModel.status == "pending",
                        ApprovalRequestModel.expires_at.isnot(None),
                        ApprovalRequestModel.expires_at < now,
                    ),
                    "expired",
                ),
                else_=ApprovalRequestModel.status,
            )
            stmt = select(
                _effective_status.label("status"),
                func.count().label("count"),
            ).group_by(_effective_status)
            rows = (await session.execute(stmt)).all()
            by_status: Dict[str, int] = {}
            for r in rows:
                by_status[r.status] = by_status.get(r.status, 0) + r.count

            # Calculate average decision time for decided requests
            avg_hours = 0.0
            # A-4 (supervise zero 6a8c5562): auto_expire_check stamps decided_at
            # (with decision_by="auto_expire") on requests nobody ever looked at,
            # and this average filtered on decided_at alone. Every ignored
            # request therefore contributed its ENTIRE TTL — 24h by default — so
            # the "Avg Decision" tile measured neglect rather than human
            # responsiveness, and inflated the more the queue was ignored.
            decided_stmt = select(
                func.avg(
                    func.extract('epoch', ApprovalRequestModel.decided_at) -
                    func.extract('epoch', ApprovalRequestModel.created_at)
                ).label("avg_seconds")
            ).where(
                ApprovalRequestModel.decided_at.isnot(None),
                or_(
                    ApprovalRequestModel.decision_by.is_(None),
                    ApprovalRequestModel.decision_by != "auto_expire",
                ),
            )
            avg_row = (await session.execute(decided_stmt)).scalar()
            if avg_row:
                avg_hours = round(avg_row / 3600, 1)

            return {
                "total": sum(by_status.values()),
                "by_status": by_status,
                # A-2: reports the same "pending" the pending LIST reports —
                # by_status is already bucketed on effective status above.
                "pending": by_status.get("pending", 0),
                "approved": by_status.get("approved", 0),
                "rejected": by_status.get("rejected", 0),
                "expired": by_status.get("expired", 0),
                "avg_decision_time_hours": avg_hours,
            }

    @staticmethod
    def effective_status(row) -> str:
        """Status as of NOW: a `pending` row past expires_at reads as expired
        even before the hourly auto_expire sweep flips the column."""
        status = row.status
        if status == "pending" and row.expires_at is not None:
            exp = row.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return "expired"
        return status

    def _to_dict(self, row) -> Dict[str, Any]:
        return {
            "id": row.id,
            "request_type": row.request_type,
            "title": row.title,
            "description": row.description,
            "context_data": row.context_data,
            "initiated_by": row.initiated_by,
            "route": row.route,
            # ACT-1 (supervise ee392aa1): list_all()/get_request() echoed the raw
            # status column, so a pending-but-expired row (before the hourly sweep)
            # rendered as actionable and then dead-ended in _decide's approve guard.
            # Mirror get_stats()/list_pending()'s effective-status definition here
            # so every read path agrees on one meaning of "pending".
            "status": self.effective_status(row),
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
