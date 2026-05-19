"""Zero → Legion heartbeat emitter (Sprint S5, 2026-05-18).

Posts a lightweight liveness signal to Legion every 30 s so Legion's Grafana
panel shows Zero's CPU / memory / active agent count in real time and the
``ProjectHeartbeatStale`` alert fires when Zero goes dark.

Reuses the existing ``LEGION_LOOPS_BASE_URL`` + ``LEGION_LOOPS_TOKEN`` env
vars from ``legion_client.py`` — same shared bearer, same transport.

Fire-and-forget: any failure is logged but never raised into Zero's main
event loop. Legion outages must not break Zero's voice / Reachy / Carousel
schedulers.

Usage in Zero's startup (call once from main):

    from app.services.legion_heartbeat_emitter import start_heartbeat_loop

    asyncio.create_task(start_heartbeat_loop())
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


HEARTBEAT_INTERVAL_S = int(os.getenv("LEGION_HEARTBEAT_INTERVAL_S", "30"))
LEGION_LOOPS_BASE_URL = os.getenv(
    "LEGION_LOOPS_BASE_URL", "http://host.docker.internal:8005"
)
LEGION_LOOPS_TOKEN = os.getenv("LEGION_LOOPS_TOKEN") or os.getenv(
    "ZERO_GATEWAY_TOKEN"
)
LEGION_PROJECT_ID = int(os.getenv("LEGION_PROJECT_ID_ZERO", "7"))
HEARTBEAT_ENABLED = (
    os.getenv("LEGION_HEARTBEAT_ENABLED", "true").lower()
    not in ("0", "false", "no")
)


def _collect_metrics() -> Dict[str, Any]:
    """Best-effort process metrics. psutil is optional."""
    payload: Dict[str, Any] = {}
    try:
        import psutil  # type: ignore

        payload["cpu_pct"] = round(psutil.cpu_percent(interval=None), 1)
        payload["mem_mb"] = int(psutil.virtual_memory().used // (1024 * 1024))
    except Exception:
        pass
    return payload


async def _post_heartbeat(client: httpx.AsyncClient, payload: Dict[str, Any]) -> None:
    url = f"{LEGION_LOOPS_BASE_URL.rstrip('/')}/api/projects/{LEGION_PROJECT_ID}/heartbeat"
    headers = {"Content-Type": "application/json"}
    if LEGION_LOOPS_TOKEN:
        headers["Authorization"] = f"Bearer {LEGION_LOOPS_TOKEN}"
    try:
        resp = await client.post(url, json=payload, headers=headers, timeout=5.0)
        if resp.status_code >= 400:
            logger.warning(
                "legion_heartbeat.bad_status",
                extra={"status": resp.status_code, "body": resp.text[:200]},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("legion_heartbeat.post_failed", extra={"err": str(exc)[:200]})


async def start_heartbeat_loop() -> None:
    """Supervised loop that POSTs a heartbeat every ``HEARTBEAT_INTERVAL_S`` seconds."""
    if not HEARTBEAT_ENABLED:
        logger.info("legion_heartbeat.disabled_by_env")
        return
    logger.info(
        "legion_heartbeat.started",
        extra={
            "interval_s": HEARTBEAT_INTERVAL_S,
            "project_id": LEGION_PROJECT_ID,
            "url": LEGION_LOOPS_BASE_URL,
        },
    )
    async with httpx.AsyncClient() as client:
        while True:
            try:
                payload = _collect_metrics()
                await _post_heartbeat(client, payload)
            except Exception:
                logger.exception("legion_heartbeat.cycle_failed")
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
