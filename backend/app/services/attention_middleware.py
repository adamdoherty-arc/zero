"""Attention Middleware — salience + DND + interrupt budget.

SecondBrain Phase 5 §6. Every outbound user-facing alert (Discord push,
desktop notification, Ask Zero proactive message) routes through
`should_interrupt(alert)` first.

Rules:
  - If current local hour in DND window -> never interrupt, always queue.
  - If alert.salience < min_interrupt_salience -> batch into morning digest.
  - If user already received >= max_interrupts_per_day today -> queue.
  - Otherwise, interrupt and mark the alert interrupted_user=true.

This is a pure function on top of agent_alerts. Callers still own the actual
send mechanism (Discord, email, push); this middleware is the decision layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import and_, func, select, update

from app.db.models import AgentAlertModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


def _now_local() -> datetime:
    # We don't yet have a user_timezone config. Use UTC for now; the DND comparison
    # is still useful and easy to override when we wire that in.
    return datetime.now(timezone.utc)


class AttentionMiddleware:
    def __init__(self) -> None:
        self._settings = get_settings()

    def _in_dnd_now(self) -> bool:
        now = _now_local()
        start = self._settings.dnd_start_hour
        end = self._settings.dnd_end_hour
        h = now.hour
        # DND spans midnight if start > end (e.g. 22 -> 7).
        if start < end:
            return start <= h < end
        return h >= start or h < end

    async def interrupts_sent_today(self) -> int:
        start = _now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        async with get_session() as session:
            result = await session.execute(
                select(func.count(AgentAlertModel.id)).where(
                    and_(
                        AgentAlertModel.interrupted_user.is_(True),
                        AgentAlertModel.interrupted_at >= start,
                    )
                )
            )
            return int(result.scalar() or 0)

    async def decide(self, alert_id: str) -> dict[str, Any]:
        """Should this alert interrupt the user now? Returns a decision + rationale."""
        async with get_session() as session:
            alert = await session.get(AgentAlertModel, alert_id)
            if alert is None:
                return {"decision": "missing", "reason": "alert_not_found"}

            if alert.status != "open":
                return {"decision": "skip", "reason": "alert_not_open"}

            if self._in_dnd_now():
                return {"decision": "queue", "reason": "dnd_window"}

            if alert.salience < self._settings.min_interrupt_salience:
                return {
                    "decision": "queue",
                    "reason": f"below_salience_threshold({self._settings.min_interrupt_salience})",
                }

            sent_today = await self.interrupts_sent_today()
            if sent_today >= self._settings.max_interrupts_per_day:
                return {
                    "decision": "queue",
                    "reason": f"interrupt_budget_exhausted({sent_today}/{self._settings.max_interrupts_per_day})",
                }

            # Mark interrupted so the budget counter increments.
            await session.execute(
                update(AgentAlertModel)
                .where(AgentAlertModel.id == alert_id)
                .values(interrupted_user=True, interrupted_at=_now_local())
            )
            await session.commit()

            return {
                "decision": "interrupt",
                "reason": "ok",
                "sent_today": sent_today + 1,
                "alert": {
                    "id": alert.id,
                    "rule": alert.rule,
                    "severity": alert.severity,
                    "summary": alert.summary,
                },
            }

    async def snapshot(self) -> dict[str, Any]:
        return {
            "dnd_now": self._in_dnd_now(),
            "dnd_window": f"{self._settings.dnd_start_hour:02d}:00-{self._settings.dnd_end_hour:02d}:00",
            "interrupts_today": await self.interrupts_sent_today(),
            "budget": self._settings.max_interrupts_per_day,
            "min_interrupt_salience": self._settings.min_interrupt_salience,
        }


_singleton: Optional[AttentionMiddleware] = None


def get_attention_middleware() -> AttentionMiddleware:
    global _singleton
    if _singleton is None:
        _singleton = AttentionMiddleware()
    return _singleton
