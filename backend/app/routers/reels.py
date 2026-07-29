"""Motivation Reels API — generate / review / publish quote-driven video reels.

Thin router: parses input, calls the reel orchestrator (or Temporal workflow),
returns the result. Generation is CPU-heavy (Playwright + ffmpeg), so the
default path schedules it as a background task and returns the generation_id to
poll; pass ``?wait=true`` to run inline (used by E2E tests).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.models.reel import PlatformName, ReelWorkflowInput

logger = structlog.get_logger(__name__)

router = APIRouter()

# Hold background task refs so they aren't garbage-collected mid-flight.
_BG_TASKS: set[asyncio.Task] = set()


class ReelGenerateRequest(BaseModel):
    sub_niche: Optional[str] = None
    theme: Optional[str] = None
    quote_text: Optional[str] = None
    quote_author: Optional[str] = None
    scene_count: int = Field(5, ge=3, le=7)
    target_duration_s: float = Field(18.0, ge=8.0, le=45.0)
    voiceover: bool = False
    mood: Optional[str] = None
    music_track_id: Optional[str] = None
    visual_style: Optional[str] = None
    auto_publish: bool = False
    platforms: list[str] = Field(default_factory=lambda: [PlatformName.TIKTOK.value])


def _to_input(req: ReelGenerateRequest) -> ReelWorkflowInput:
    return ReelWorkflowInput(
        sub_niche=req.sub_niche, theme=req.theme, quote_text=req.quote_text,
        quote_author=req.quote_author, scene_count=req.scene_count,
        target_duration_s=req.target_duration_s, voiceover=req.voiceover,
        mood=req.mood, music_track_id=req.music_track_id, visual_style=req.visual_style,
        auto_publish=req.auto_publish, platforms=req.platforms, initiated_by="api",
    )


@router.post("/generate")
async def generate_reel(req: ReelGenerateRequest, wait: bool = Query(False)):
    """Generate a motivation reel. ``wait=true`` runs inline and returns the
    full result; otherwise schedules a background task and returns the id.
    """
    from app.services.reels import reel_orchestrator

    gen_id = uuid.uuid4().hex
    payload = _to_input(req)

    if wait:
        result = await reel_orchestrator.generate_reel(payload, generation_id=gen_id)
        return result.model_dump(mode="json")

    async def _run():
        try:
            await reel_orchestrator.generate_reel(payload, generation_id=gen_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("reel_bg_generation_failed", generation_id=gen_id, error=str(exc))

    task = asyncio.create_task(_run())
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return {"generation_id": gen_id, "status": "started"}


@router.get("")
@router.get("/")
async def list_reels(limit: int = Query(30, ge=1, le=200),
                     status: Optional[str] = None, sub_niche: Optional[str] = None):
    from app.services.reels import reel_state
    return {"reels": await reel_state.list_reels(limit=limit, status=status, sub_niche=sub_niche)}


@router.get("/music")
async def list_music():
    from app.services.reels import rf_music_service
    tracks = await rf_music_service.list_tracks(bakeable_only=True)
    return {"tracks": [t.model_dump(mode="json") for t in tracks]}


@router.post("/music/seed")
async def seed_music(force: bool = Query(False)):
    from app.services.reels.music_ingest import ingest_procedural
    total = await ingest_procedural(force=force)
    return {"ok": True, "bakeable_tracks": total}


@router.get("/{generation_id}")
async def get_reel(generation_id: str):
    from app.services.reels import reel_state
    row = await reel_state.get_reel(generation_id)
    if not row:
        raise HTTPException(404, "reel not found")
    return row


@router.get("/{generation_id}/video")
async def get_reel_video(generation_id: str):
    """Stream the rendered MP4 for in-app review."""
    from app.services.reels.reel_orchestrator import reel_local_path
    path = reel_local_path(generation_id)
    if not os.path.exists(path):
        raise HTTPException(404, "video not found")
    return FileResponse(path, media_type="video/mp4", filename=f"reel-{generation_id[:8]}.mp4")


@router.post("/{generation_id}/approve")
async def approve_reel(generation_id: str):
    """Approve a reel and publish it to its target platforms (dry-run by default)."""
    from app.services.reels import reel_publish_service, reel_state
    row = await reel_state.get_reel(generation_id)
    if not row:
        raise HTTPException(404, "reel not found")
    pubs = await reel_publish_service.publish_reel_by_id(generation_id)
    return {"ok": True, "generation_id": generation_id,
            "platform_publishes": [p.model_dump(mode="json") for p in pubs]}


@router.post("/{generation_id}/reject")
async def reject_reel(generation_id: str):
    from app.services.reels import reel_state
    row = await reel_state.get_reel(generation_id)
    if not row:
        raise HTTPException(404, "reel not found")
    from app.db.models import ReelGenerationModel
    from app.infrastructure.database import get_session
    from sqlalchemy import update
    async with get_session() as session:
        await session.execute(
            update(ReelGenerationModel).where(ReelGenerationModel.id == generation_id)
            .values(status="abandoned")
        )
    return {"ok": True, "generation_id": generation_id, "status": "abandoned"}


@router.post("/{generation_id}/publish")
async def publish_reel(generation_id: str, platforms: Optional[str] = Query(None)):
    """Explicit publish (comma-separated platforms override)."""
    from app.services.reels import reel_publish_service, reel_state
    row = await reel_state.get_reel(generation_id)
    if not row:
        raise HTTPException(404, "reel not found")
    plats = [p.strip() for p in platforms.split(",")] if platforms else None
    pubs = await reel_publish_service.publish_reel_by_id(generation_id, platforms=plats)
    return {"ok": True, "generation_id": generation_id,
            "platform_publishes": [p.model_dump(mode="json") for p in pubs]}
