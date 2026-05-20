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
