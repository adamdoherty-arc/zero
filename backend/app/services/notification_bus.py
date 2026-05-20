"""In-process async pub/sub for live notifications.

Decouples publishers (schedulers, routers, services) from subscribers
(the WebSocket router under /api/notifications/ws, the host_agent's
Windows-toast subscriber). The bus is intentionally tiny: a set of
asyncio.Queue subscribers and a publish() that drops into each.

No persistence; this is the fan-out layer. The system of record is the
notification_service DB table. Publishers should write to BOTH (DB +
bus) when the event also needs durable history.
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
        consumer cannot back-pressure the publisher chain.
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
        logger.debug(
            "notification_bus_publish",
            event_type=event.get("type"),
            subscriber_count=len(subs),
            delivered=delivered,
        )
        return delivered

    async def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._lock:
            return list(self._recent[-max(1, min(limit, self._recent_limit)) :])

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
