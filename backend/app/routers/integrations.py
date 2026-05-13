"""
Integrations API — Composio-backed third-party connectors + auto-fetch loop
status.

Stub today; the full provider lives in
``app/services/integrations/composio_provider.py`` and the scheduler in
``app/services/integrations/auto_fetch_loop.py``.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.integrations.composio_provider import get_composio_provider
from app.services.integrations.auto_fetch_loop import get_auto_fetch_loop

router = APIRouter()


class ConnectRequest(BaseModel):
    integration: str  # e.g. "gmail", "linear", "notion"
    auth_token: str | None = None


@router.get("/")
async def list_integrations():
    provider = get_composio_provider()
    return {
        "integrations": provider.list_integrations(),
        "auto_fetch": get_auto_fetch_loop().status(),
    }


@router.get("/status")
async def status():
    provider = get_composio_provider()
    loop = get_auto_fetch_loop()
    return {
        "available": provider.is_available(),
        "connected": provider.list_connected(),
        "auto_fetch": loop.status(),
    }


@router.post("/connect")
async def connect(req: ConnectRequest):
    provider = get_composio_provider()
    return await provider.connect(req.integration, auth_token=req.auth_token)


@router.post("/disconnect/{integration}")
async def disconnect(integration: str):
    provider = get_composio_provider()
    return await provider.disconnect(integration)


@router.post("/sync/{integration}")
async def sync_one(integration: str):
    """Force an immediate sync of one integration (out-of-band of the 20-min loop)."""
    loop = get_auto_fetch_loop()
    result = await loop.sync_one(integration)
    return result


@router.post("/auto-fetch/start")
async def start_loop():
    loop = get_auto_fetch_loop()
    await loop.start()
    return loop.status()


@router.post("/auto-fetch/stop")
async def stop_loop():
    loop = get_auto_fetch_loop()
    await loop.stop()
    return loop.status()
