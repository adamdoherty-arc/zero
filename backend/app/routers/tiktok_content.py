"""
TikTok Content Pipeline API endpoints.
REST API for faceless video script generation, content queue management, and template browsing.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import structlog

from app.models.tiktok_content import (
    VideoScript, VideoScriptCreate, VideoScriptUpdate,
    VideoTemplateType, VideoTemplateInfo,
    ContentQueueItem, ContentQueueStats,
)
from app.services.tiktok_video_service import get_tiktok_video_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================
# TEMPLATES
# ============================================

@router.get("/templates", response_model=List[VideoTemplateInfo])
async def list_templates():
    """List available faceless video templates."""
    service = get_tiktok_video_service()
    return service.list_templates()


# ============================================
# SCRIPTS
# ============================================

@router.post("/scripts/generate", response_model=VideoScript)
async def generate_script(data: VideoScriptCreate):
    """Generate a faceless video script for a product."""
    service = get_tiktok_video_service()
    script = await service.generate_video_script(data.product_id, data.template_type)
    if not script:
        raise HTTPException(status_code=404, detail="Product not found or template invalid")
    return script


@router.get("/scripts", response_model=List[VideoScript])
async def list_scripts(
    product_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List video scripts."""
    service = get_tiktok_video_service()
    return await service.list_scripts(product_id=product_id, status=status, limit=limit)


@router.get("/scripts/{script_id}", response_model=VideoScript)
async def get_script(script_id: str):
    """Get a specific video script."""
    service = get_tiktok_video_service()
    script = await service.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return script


@router.patch("/scripts/{script_id}", response_model=VideoScript)
async def update_script(script_id: str, updates: VideoScriptUpdate):
    """Edit a video script before generation."""
    service = get_tiktok_video_service()
    script = await service.update_script(script_id, updates)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return script


# ============================================
# CONTENT QUEUE
# ============================================

@router.post("/scripts/{script_id}/queue", response_model=ContentQueueItem)
async def queue_script(script_id: str):
    """Send a video script to AIContentTools for generation."""
    service = get_tiktok_video_service()
    item = await service.queue_for_generation(script_id)
    if not item:
        raise HTTPException(status_code=404, detail="Script not found")
    return item


@router.get("/queue", response_model=List[ContentQueueItem])
async def list_queue(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List content generation queue."""
    service = get_tiktok_video_service()
    return await service.list_content_queue(status=status, limit=limit)


@router.get("/queue/stats", response_model=ContentQueueStats)
async def get_queue_stats():
    """Get content queue statistics."""
    service = get_tiktok_video_service()
    return await service.get_queue_stats()


@router.post("/queue/{queue_id}/check", response_model=ContentQueueItem)
async def check_queue_status(queue_id: str):
    """Check generation status for a queue item."""
    service = get_tiktok_video_service()
    item = await service.check_generation_status(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item
