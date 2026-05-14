"""
Subconscious API â€” idle reflection loop.

The subconscious is a background loop that wakes every ``interval_minutes``
while the user is idle, walks recent vault writes + active integrations, and
drafts "insight" entries into the Memory Vault global digest plus optional
``agent_alerts``.

Endpoints expose start/stop/status and the most recent insights so the UI
can surface them and the user can dismiss / promote them to long-term memory.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.subconscious_loop import get_subconscious_loop

router = APIRouter()


class ConfigUpdate(BaseModel):
    interval_minutes: int | None = None
    enabled: bool | None = None


@router.get("/status")
async def status():
    return get_subconscious_loop().status()


@router.post("/start")
async def start():
    loop = get_subconscious_loop()
    await loop.start()
    return loop.status()


@router.post("/stop")
async def stop():
    loop = get_subconscious_loop()
    await loop.stop()
    return loop.status()


@router.put("/config")
async def update_config(cfg: ConfigUpdate):
    loop = get_subconscious_loop()
    if cfg.interval_minutes is not None:
        loop.set_interval(cfg.interval_minutes)
    if cfg.enabled is not None:
        if cfg.enabled:
            await loop.start()
        else:
            await loop.stop()
    return loop.status()


@router.get("/insights")
async def insights(limit: int = 20):
    return {"insights": get_subconscious_loop().recent_insights(limit=limit)}


@router.post("/run-now")
async def run_now():
    """Trigger one reflection pass immediately (testing convenience)."""
    loop = get_subconscious_loop()
    result = await loop.run_once()
    return result
