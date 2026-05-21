"""In-process async pub/sub for live notifications.

Decouples publishers (schedulers, routers, services) from subscribers
(the WebSocket router under /api/notifications/ws, the host_agent's
Windows-toast subscriber). The bus is intentionally tiny: a set of
asyncio.Queue subscribers and a publish() that drops into each.

Enhancement-11 (2026-05-21): published events are also persisted to the
``notification_events`` table so ``recent()`` reads survive zero-api
restarts. The in-memory ring buffer stays as the fast path; the DB is
the system of record beyond the last 50 events / process boot.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, AsyncIterator

import structlog

logger = structlog.get_logger(__name__)

_QUEUE_MAXSIZE = 64


class NotificationBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._recent: list[dict[str, Any]] = []
        self._recent_limit = 50

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def publish(self, event: dict[str, Any]) -> int:
        """Fan out a single event to every subscriber. Returns delivered count.

        Drops events for any subscriber whose queue is full so a slow
        consumer cannot back-pressure the publisher chain. Also persists
        the event to the ``notification_events`` table; failures there
        are non-fatal -- the bus must keep flowing even if the DB blips.
        """
        if "ts" not in event:
            event = {**event, "ts": datetime.now(timezone.utc).isoformat()}
        delivered = 0
        async with self._lock:
            self._recent.append(event)
            if len(self._recent) > self._recent_limit:
                self._recent = self._recent[-self._recent_limit :]
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                logger.debug(
                    "notification_bus_subscriber_full",
                    event_type=event.get("type"),
                )
        # Fire-and-forget persistence so a slow / blocked DB does not
        # back-pressure the publisher chain.
        asyncio.create_task(self._persist(event))
        logger.debug(
            "notification_bus_publish",
            event_type=event.get("type"),
            subscriber_count=len(subs),
            delivered=delivered,
        )
        return delivered

    async def _persist(self, event: dict[str, Any]) -> None:
        try:
            from app.db.models import NotificationEventModel
            from app.infrastructure.database import get_session

            ev_type = str(event.get("type") or "notice")[:120]
            source = event.get("source")
            source_str = str(source)[:120] if source else None
            # Strip type+source out of payload to avoid double-storage.
            payload = {k: v for k, v in event.items() if k not in {"type", "source"}}
            async with get_session() as session:
                row = NotificationEventModel(
                    type=ev_type,
                    source=source_str,
                    payload=payload,
                )
                session.add(row)
        except Exception as exc:  # noqa: BLE001
            logger.debug("notification_persist_failed", error=str(exc))

    async def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent N events, blending the in-memory ring
        buffer with the persisted DB tail when the ring isn't full.

        After a restart the ring is empty -- we fall through to the DB
        so the steward + dashboard still see the last hour of activity.
        """
        capped = max(1, min(limit, self._recent_limit))
        async with self._lock:
            in_memory = list(self._recent[-capped:])
        if len(in_memory) >= capped:
            return in_memory
        # Fill the gap from DB. Reads are cheap and only fire on cold
        # boot or when a subscriber asks for more than 50 events.
        try:
            from sqlalchemy import select
            from app.db.models import NotificationEventModel
            from app.infrastructure.database import get_session

            async with get_session() as session:
                rows = (
                    await session.execute(
                        select(NotificationEventModel)
                        .order_by(NotificationEventModel.created_at.desc())
                        .limit(capped)
                    )
                ).scalars().all()
        except Exception as exc:  # noqa: BLE001
            logger.debug("notification_recent_db_fallback_failed", error=str(exc))
            return in_memory
        # Build events newest-first and dedupe vs in_memory by ts to keep
        # ordering stable even when both sources overlap.
        events: list[dict[str, Any]] = []
        seen_ts: set[str] = {e.get("ts", "") for e in in_memory}
        for row in rows:
            ts = row.created_at.astimezone(timezone.utc).isoformat() if row.created_at else ""
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            events.append({
                "type": row.type,
                "source": row.source,
                "ts": ts,
                **(row.payload or {}),
            })
        # Newest-first from DB, oldest-first from memory -> reverse DB so caller
        # sees a single chronological tail.
        events.reverse()
        return (events + in_memory)[-capped:]

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Async iterator for callers that prefer not to hold the queue."""
        q = await self.subscribe()
        try:
            while True:
                yield await q.get()
        finally:
            await self.unsubscribe(q)


@lru_cache()
def get_notification_bus() -> NotificationBus:
    return NotificationBus()
