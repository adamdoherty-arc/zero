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
from sqlalchemy import and_, or_, select, update

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

    def _requires_gate(
        self,
        tier: str,
        *,
        salience: Optional[float] = None,
        dnd: bool = False,
    ) -> bool:
        """Should this tier pause for human approval?

        Fix-94: implement the documented approval ladder (vault constitution /
        supervisor profile constraint):
          read           -> auto
          write_local     -> auto IF salience >= min_interrupt_salience AND not DND
          write_external  -> always interrupt
          financial       -> always interrupt (routes to ADA)
        DRY_RUN still gates write_local unconditionally. ``salience=None`` means
        the caller didn't score it -> treated as high-enough so legacy callers
        keep auto-executing write_local; only an explicit low score (or DND)
        gates it.

        A-3 (supervise zero 6a8c5562): this used to end in a bare
        ``return False``, so ANY tier outside the four canonical strings —
        "Financial", "write-external", a future "payment", or a caller typo —
        fell through to "no gate needed" and ``gated_call`` executed the side
        effect with no approval row at all. ``tier`` is a free-form String(20)
        supplied by callers, and this module already anticipates unknown tiers
        elsewhere (``_TIER_EXPIRY.get(tier, ...)``). A trust boundary must
        default-DENY, so the terminal case is now "gate it" and only ``read``
        is explicitly ungated.
        """
        if tier == "read":
            return False
        if tier in ("write_external", "financial"):
            return True
        if tier == "write_local":
            if getattr(self._settings, "dry_run", False):
                return True
            if dnd:
                return True
            if salience is not None:
                threshold = float(
                    getattr(self._settings, "min_interrupt_salience", 0.6)
                )
                if salience < threshold:
                    return True
            return False
        logger.warning("approval_unknown_tier_gated", tier=tier)
        return True

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
        # Fix-123 (A1): an "approve" must not green-light a logically-expired
        # request. expire_stale() only runs hourly, so a financial approval
        # (30-min TTL) can sit pending-but-expired for up to ~59 min; without
        # this guard a human (or polling caller) could mark it approved,
        # producing a phantom approval the gated_call waiter would then execute —
        # defeating the whole point of the shorter financial expiry. Rejecting an
        # expired request stays allowed (it's already effectively denied).
        predicates = [
            AgentApprovalModel.id == approval_id,
            AgentApprovalModel.status == "pending",
        ]
        if status == "approved":
            predicates.append(
                or_(
                    AgentApprovalModel.expires_at.is_(None),
                    AgentApprovalModel.expires_at >= _now(),
                )
            )
        async with get_session() as session:
            result = await session.execute(
                update(AgentApprovalModel)
                .where(*predicates)
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
        elif status == "approved":
            logger.info(
                "approval_decide_noop",
                id=approval_id,
                note="not pending or already expired; approve refused",
            )
        return row

    async def list(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[AgentApprovalModel]:
        async with get_session() as session:
            q = select(AgentApprovalModel).order_by(AgentApprovalModel.created_at.desc()).limit(limit)
            # ACT-4: `expired` is a DERIVED bucket (see the elif below), so it must
            # not also be constrained by the literal column value — that AND would
            # re-exclude exactly the pending-but-past-expiry rows we want.
            if status and status != "expired":
                q = q.where(AgentApprovalModel.status == status)
            # Fix-123 (A2): a row that is `pending` but past expires_at is
            # logically dead — expire_stale() just hasn't swept it yet (hourly).
            # Returning it from the pending list made dedup callers
            # (_pending_task_approval_exists) treat a stale, never-actioned
            # approval as a live gate, leaving the task BLOCKED with a dead
            # approval reference for up to ~59 min, and surfaced stale rows as
            # actionable in the UI. Exclude expired-but-unswept from `pending`.
            if status == "pending":
                q = q.where(
                    or_(
                        AgentApprovalModel.expires_at.is_(None),
                        AgentApprovalModel.expires_at >= _now(),
                    )
                )
            # ACT-4 (supervise fc9c5829): Fix-123 (A2) correctly removed
            # pending-but-past-expiry rows from the `pending` bucket, but nothing
            # put them in the `expired` bucket — that filter matched only the
            # literal DB status, which expire_stale() sets on an HOURLY cron. So
            # for up to ~59 min a dead approval appeared on NEITHER filtered tab
            # (visible only in the unfiltered list, where effective_status() finally
            # reports it as expired). Mirror the derivation here.
            elif status == "expired":
                q = q.where(
                    or_(
                        AgentApprovalModel.status == "expired",
                        and_(
                            AgentApprovalModel.status == "pending",
                            AgentApprovalModel.expires_at.is_not(None),
                            AgentApprovalModel.expires_at < _now(),
                        ),
                    )
                )
            result = await session.execute(q)
            return list(result.scalars().all())

    async def get(self, approval_id: str) -> Optional[AgentApprovalModel]:
        async with get_session() as session:
            return await session.get(AgentApprovalModel, approval_id)

    @staticmethod
    def effective_status(row: AgentApprovalModel) -> str:
        """The row's status as of NOW, not as of the last sweep.

        A-1 (supervise zero 6a8c5562): expire_stale() only runs hourly, so a
        row can sit past expires_at with status still literally "pending".
        Fix-123 excluded those from the pending LIST, but the guard was nested
        inside ``if status == "pending"`` — so the unfiltered list (the UI's
        "all" tab) and get() still reported them as pending. The frontend gates
        its Approve/Reject buttons on ``status === 'pending'``, so a dead
        approval rendered as actionable; clicking Approve then hit decide(),
        whose own expiry predicate refused it, surfacing as a 404. Deriving the
        status here gives every read path one answer.
        """
        if row.status == "pending" and row.expires_at is not None:
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < _now():
                return "expired"
        return row.status

    # ACT-3: an approval claimed for execution should never outlive this window.
    # gated_call's longest sanctioned wait is wait_timeout_seconds, and execute()
    # is a single tool call — an hour is far beyond any legitimate run.
    _EXECUTING_STALE_AFTER = timedelta(hours=1)

    async def expire_stale(self) -> int:
        """Mark pending approvals past their expiry as expired.

        ACT-3 (supervise fc9c5829): also reaps rows stranded in "executing".
        gated_call claims a row (status="executing") before awaiting execute();
        if that process dies — hard crash, container restart, SIGKILL — between
        the claim and the result write, no code path could ever move the row
        again (decide() and this sweep both required "pending"). Those rows are
        terminal-failed here so the queue cannot silently accumulate dead gates.
        """
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

            stuck_cutoff = _now() - self._EXECUTING_STALE_AFTER
            stuck_result = await session.execute(
                update(AgentApprovalModel)
                .where(
                    AgentApprovalModel.status == "executing",
                    AgentApprovalModel.decided_at < stuck_cutoff,
                )
                .values(
                    status="failed",
                    error="stranded in executing (process died mid-execution); reaped by expire_stale",
                    executed_at=_now(),
                )
                .returning(AgentApprovalModel.id)
            )
            stuck_ids = [r[0] for r in stuck_result.all()]
            await session.commit()
        if ids:
            logger.info("approvals_expired", count=len(ids), ids=ids[:10])
        if stuck_ids:
            logger.warning("approvals_executing_reaped", count=len(stuck_ids), ids=stuck_ids[:10])
        return len(ids) + len(stuck_ids)

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
        salience: Optional[float] = None,
        dnd: bool = False,
    ) -> dict[str, Any]:
        """Helper: pause, queue, optionally wait for approval, then execute.

        If `wait_timeout_seconds > 0`, polls every 5s for approval and executes
        inline on approve. Otherwise returns immediately with approval_id and
        the caller polls later.

        Fix-94: pass `salience` (and `dnd`) to gate write_local actions per the
        documented ladder — low-salience or DND write_local queues for approval
        instead of auto-executing.
        """
        if not self._requires_gate(tier, salience=salience, dnd=dnd):
            # ACT-6 (supervise fc9c5829): the ungated path wrote no row and logged
            # nothing, while request() always logs "approval_requested". For the
            # auto tiers (read, and write_local above the salience threshold — the
            # common case under the ladder) that meant a tool could execute with
            # zero trace of tool_name/arguments/requester anywhere; if execute()
            # then raised, the exception surfaced with no record the call ever
            # happened. The audit trail must cover auto-approved actions too.
            logger.info(
                "approval_auto_executed",
                tool=tool_name,
                tier=tier,
                requested_by=requested_by,
                salience=salience,
                dnd=dnd,
                summary=summary[:200],
            )
            try:
                result = await execute()
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "approval_auto_execute_failed",
                    tool=tool_name,
                    tier=tier,
                    requested_by=requested_by,
                    error=str(e),
                )
                raise
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
                # Atomically claim the approval BEFORE executing so two waiters
                # (or a retried gated_call) can never double-fire the side
                # effect. The claim is its own tx and is released before the
                # execute() await — never hold a session across the call.
                async with get_session() as session:
                    claim = await session.execute(
                        update(AgentApprovalModel)
                        .where(AgentApprovalModel.id == approval.id)
                        .where(AgentApprovalModel.status == "approved")
                        .values(status="executing")
                        .returning(AgentApprovalModel.id)
                    )
                    claimed = claim.scalar_one_or_none()
                    await session.commit()
                if claimed is None:
                    # Lost the race; another waiter is executing it. Re-poll for
                    # the terminal state instead of executing a second time.
                    continue
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
                # ACT-3 (supervise fc9c5829): this caught only `Exception`, so an
                # `asyncio.CancelledError` — a BaseException since 3.8, raised on
                # every task cancellation and on shutdown — skipped the failure
                # write entirely and left the row stranded in the "executing" state
                # claimed at the top of this block. Nothing could then move it:
                # decide() requires status=="pending" and expire_stale() only swept
                # "pending", so the row was a permanent dead end needing manual DB
                # surgery. Record the terminal state on cancellation too, then let
                # the cancellation propagate (never swallow it).
                except asyncio.CancelledError:
                    try:
                        async with get_session() as session:
                            await session.execute(
                                update(AgentApprovalModel)
                                .where(AgentApprovalModel.id == approval.id)
                                .values(
                                    status="failed",
                                    error="cancelled during execution",
                                    executed_at=_now(),
                                )
                            )
                            await session.commit()
                    except Exception as write_err:  # noqa: BLE001
                        logger.error(
                            "approval_cancel_write_failed",
                            id=approval.id,
                            error=str(write_err),
                        )
                    logger.warning("approval_execution_cancelled", id=approval.id)
                    raise
                except Exception as e:  # noqa: BLE001
                    async with get_session() as session:
                        await session.execute(
                            update(AgentApprovalModel)
                            .where(AgentApprovalModel.id == approval.id)
                            .values(status="failed", error=str(e), executed_at=_now())
                        )
                        await session.commit()
                    return {"status": "failed", "approval_id": approval.id, "error": str(e)}
            if fresh.status in ("executed", "failed"):
                # Completed by a concurrent waiter — return the recorded outcome
                # rather than spinning to timeout.
                return {"status": fresh.status, "approval_id": approval.id, "result": getattr(fresh, "result", None)}
            if fresh.status in ("rejected", "expired"):
                return {"status": fresh.status, "approval_id": approval.id}
        return {"status": "timeout", "approval_id": approval.id}


_singleton: Optional[ApprovalQueueService] = None


def get_approval_queue() -> ApprovalQueueService:
    global _singleton
    if _singleton is None:
        _singleton = ApprovalQueueService()
    return _singleton
