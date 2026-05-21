"""Live notification fan-out.

WebSocket subscribers (the dashboard, the host_agent's Windows-toast
bridge) connect to /api/notifications/ws and receive every published
event in JSON. A POST endpoint lets services (scheduler, meeting auto
recorder, supervisor_graph) push events.

The system of record for durable notifications is notification_service;
this router only handles transport. See backend/app/services/
notification_bus.py for the pub/sub primitive.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, Body, WebSocket, WebSocketDisconnect

from app.services.notification_bus import get_notification_bus

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/recent")
async def recent_notifications(limit: int = 20):
    bus = get_notification_bus()
    return {"events": await bus.recent(limit=limit)}


@router.get("/history")
async def notifications_history(
    since_hours: int = 24,
    type: str | None = None,
    limit: int = 200,
):
    """F-64 — DB-backed history reader. Pulls from notification_events
    (Enhancement-11 persistence). Filter by event type + lookback hours.
    Default 24h / 200 events is the dashboard tile shape.
    """
    from datetime import datetime, timedelta, timezone

    try:
        from sqlalchemy import select
        from app.db.models import NotificationEventModel  # type: ignore
        from app.infrastructure.database import get_session
    except Exception as exc:
        return {"events": [], "error": str(exc)}

    since_hours = max(1, min(int(since_hours), 24 * 30))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    stmt = (
        select(NotificationEventModel)
        .where(NotificationEventModel.created_at >= cutoff)
        .order_by(NotificationEventModel.created_at.desc())
        .limit(max(1, min(int(limit), 1000)))
    )
    if type:
        stmt = stmt.where(NotificationEventModel.type == type)
    try:
        async with get_session() as db:
            rows = (await db.execute(stmt)).scalars().all()
    except Exception as exc:
        return {"events": [], "error": str(exc)}
    events = []
    by_type: dict[str, int] = {}
    for row in rows:
        ev = {
            "type": row.type,
            "source": row.source,
            "ts": row.created_at.astimezone(timezone.utc).isoformat() if row.created_at else None,
            **(row.payload or {}),
        }
        events.append(ev)
        by_type[row.type] = by_type.get(row.type, 0) + 1
    return {
        "events": events,
        "since_hours": since_hours,
        "type_filter": type,
        "by_type": by_type,
        "count": len(events),
    }


@router.get("/metrics")
async def notification_metrics():
    """Enhancement-12 — surface notification_bus counters.

    publish_total / deliver_total / drop_queue_full_total / persist_ok_total /
    persist_fail_total + per-event-type breakdown so a silent regression
    (e.g. every event dropped because no subscriber is alive) becomes
    visible. Counters are process-local; aggregate across pods if scaled.
    """
    bus = get_notification_bus()
    return bus.metrics()


@router.post("/publish")
async def publish_notification(payload: dict[str, Any] = Body(...)):
    """Manual publish hook. Useful for host_agent / external producers."""
    bus = get_notification_bus()
    if "type" not in payload:
        payload = {**payload, "type": "notice"}
    delivered = await bus.publish(payload)
    return {"ok": True, "delivered": delivered}


@router.websocket("/ws")
async def notifications_ws(ws: WebSocket):
    await ws.accept()
    bus = get_notification_bus()
    q = await bus.subscribe()
    logger.info("notifications_ws_connected")
    # Replay last 5 events so a freshly opened dashboard tab does not
    # miss a "meeting starting" toast that fired 2s before connect.
    for event in await bus.recent(limit=5):
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            break
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                await ws.send_text(json.dumps(event))
            except asyncio.TimeoutError:
                # Send a keepalive ping so intermediate proxies don't
                # close the long-lived socket. Frontend can ignore.
                await ws.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        logger.info("notifications_ws_disconnected")
    except Exception as exc:
        logger.warning("notifications_ws_error", error=str(exc))
    finally:
        await bus.unsubscribe(q)
        try:
            await ws.close()
        except Exception:
            pass
