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

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, func, select, text, update

from app.db.models import AgentAlertModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


# Stable xact-advisory-lock key guarding the per-day interrupt budget so the
# check-then-mark in decide() can't be split by a concurrent call (TOCTOU).
_INTERRUPT_BUDGET_LOCK_KEY = 778_899_001


def _user_tz() -> tzinfo:
    tz_name = (getattr(get_settings(), "user_timezone", "") or "").strip()
    if not tz_name:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def _now_local() -> datetime:
    """Now in the user's configured timezone (ZERO_USER_TIMEZONE) so the DND
    window and the daily interrupt-budget boundary track the user's real clock,
    not UTC. Falls back to UTC when the tz is unset or invalid."""
    return datetime.now(_user_tz())


class AttentionMiddleware:
    def __init__(self) -> None:
        self._settings = get_settings()

    def _in_dnd_now(self) -> bool:
        now = _now_local()
        start = self._settings.dnd_start_hour
        end = self._settings.dnd_end_hour
        h = now.hour
        # DND spans midnight if start > end (e.g. 22 -> 7).
        if start == end:
            # Fix-109: zero-width window (e.g. 0/0) = "no DND". Without this guard
            # the fall-through `h >= start or h < end` is True for every hour,
            # pinning DND permanently ON and silently queuing every alert.
            return False
        if start < end:
            return start <= h < end
        return h >= start or h < end

    def in_dnd(self) -> bool:
        """Public DND-window check for callers that pre-filter before they
        have a concrete alert_id (e.g. the proactive notifier). Synchronous;
        mirrors the gate ``decide()`` applies per-alert."""
        return self._in_dnd_now()

    async def _count_interrupts_today(self, session: Any) -> int:
        """Count interrupts already marked today, on the CALLER's session so the
        count and the subsequent mark live in one transaction under one advisory
        lock (see ``decide``)."""
        start = _now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(
            select(func.count(AgentAlertModel.id)).where(
                and_(
                    AgentAlertModel.interrupted_user.is_(True),
                    AgentAlertModel.interrupted_at >= start,
                )
            )
        )
        return int(result.scalar() or 0)

    async def interrupts_sent_today(self) -> int:
        async with get_session() as session:
            return await self._count_interrupts_today(session)

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

            # Serialize the budget check + increment so two concurrent decide()
            # calls can't both read sent_today < budget and both mark interrupted
            # (TOCTOU over-spend). The xact-advisory lock auto-releases on
            # commit/rollback; under the serial scheduler contention is ~zero,
            # but this makes the gate correct under any concurrency.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:k)"),
                {"k": _INTERRUPT_BUDGET_LOCK_KEY},
            )

            sent_today = await self._count_interrupts_today(session)
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
