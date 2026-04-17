"""
TikTok Shop Research Agent API endpoints.
REST API for managing TikTok Shop product discovery, research, opportunity scoring,
content review, and publishing to TikTok.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from typing import Any, Dict, List, Optional
import structlog
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models.tiktok_shop import (
    TikTokProduct, TikTokProductCreate, TikTokProductUpdate,
    TikTokProductStatus, TikTokProductApproval,
    TikTokResearchCycleResult, TikTokShopStats,
)
from app.models.tiktok_content import ContentApproval, PublishRequest
from app.models.reference_video import ReferenceVideo, ReferenceVideoCreate
from app.services.tiktok_shop_service import get_tiktok_shop_service
from app.services.publishing_service import get_publishing_service
from app.services.url_import_service import get_url_import_service
from app.services.reference_video_service import get_reference_video_service

router = APIRouter()
logger = structlog.get_logger()
limiter = Limiter(key_func=get_remote_address)


# ============================================
# APPROVAL QUEUE (must be before /products/{product_id})
# ============================================

@router.get("/products/pending", response_model=List[TikTokProduct])
async def list_pending_products(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List products pending approval."""
    service = get_tiktok_shop_service()
    return await service.list_pending(limit=limit, offset=offset)


@router.post("/products/approve")
async def approve_products(data: TikTokProductApproval):
    """Batch approve products."""
    service = get_tiktok_shop_service()
    count = await service.batch_approve(data.product_ids)
    return {"status": "approved", "count": count}


@router.post("/products/reject")
async def reject_products(data: TikTokProductApproval):
    """Batch reject products."""
    service = get_tiktok_shop_service()
    count = await service.batch_reject(data.product_ids, data.rejection_reason)
    return {"status": "rejected", "count": count}


@router.post("/products/cleanup")
async def cleanup_products():
    """Clean up products that have article titles instead of real product names."""
    service = get_tiktok_shop_service()
    return await service.cleanup_article_title_products()


@router.post("/products/backfill-images")
async def backfill_images(
    limit: int = Query(20, ge=1, le=100),
):
    """Backfill images for products that don't have them yet."""
    service = get_tiktok_shop_service()
    count = await service.backfill_images(limit=limit)
    return {"images_fetched": count}


@router.post("/products/bulk-enrich")
async def bulk_enrich(data: TikTokProductApproval):
    """Enrich multiple products with images, sourcing info, and success rating."""
    service = get_tiktok_shop_service()
    count = 0
    for product_id in data.product_ids:
        try:
            await service.enrich_product(product_id)
            count += 1
        except Exception as e:
            logger.warning("bulk_enrich_failed", product_id=product_id, error=str(e))
    return {"status": "enriched", "count": count}


@router.post("/products/bulk-delete")
async def bulk_delete(data: TikTokProductApproval):
    """Delete multiple products."""
    service = get_tiktok_shop_service()
    count = 0
    for product_id in data.product_ids:
        if await service.delete_product(product_id):
            count += 1
    return {"status": "deleted", "count": count}


@router.post("/products/import-url", response_model=TikTokProduct)
@limiter.limit("10/minute")
async def import_product_from_url(
    request: Request,
    url: str = Query(..., description="Product URL to import (Amazon, AliExpress, TikTok Shop, etc.)"),
    research: bool = Query(True, description="Run full research pipeline after import"),
):
    """Import a product from a pasted URL. Extracts metadata and optionally runs research."""
    svc = get_url_import_service()
    try:
        return await svc.import_from_url(url, run_research=research)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================
# PRODUCTS
# ============================================

@router.get("/products", response_model=List[TikTokProduct])
async def list_products(
    status: Optional[TikTokProductStatus] = Query(None, description="Filter by status"),
    niche: Optional[str] = Query(None, description="Filter by niche"),
    min_score: Optional[float] = Query(None, ge=0, le=100, description="Minimum opportunity score"),
    search: Optional[str] = Query(None, description="Search name, description, why_trending"),
    product_type: Optional[str] = Query(None, description="Filter by product type"),
    sort_by: Optional[str] = Query("opportunity_score", description="Sort: opportunity_score, name, discovered_at, success_rating"),
    sort_order: Optional[str] = Query("desc", description="asc or desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List TikTok Shop products with advanced filtering."""
    service = get_tiktok_shop_service()
    return await service.list_products(
        status=status.value if status else None,
        niche=niche,
        min_score=min_score,
        search=search,
        product_type=product_type,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )


@router.post("/products", response_model=TikTokProduct)
async def create_product(data: TikTokProductCreate):
    """Manually add a TikTok Shop product."""
    service = get_tiktok_shop_service()
    return await service.create_product(data)


@router.post("/products/add-and-research", response_model=TikTokProduct)
async def add_and_research_product(data: TikTokProductCreate):
    """Add a product manually and immediately run full research pipeline.

    Creates the product, then runs SearXNG research, LLM scoring,
    image fetching, sourcing info, and success rating.
    """
    service = get_tiktok_shop_service()
    return await service.add_and_research_product(data)


@router.get("/products/{product_id}", response_model=TikTokProduct)
async def get_product(product_id: str):
    """Get a specific product."""
    service = get_tiktok_shop_service()
    product = await service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.patch("/products/{product_id}", response_model=TikTokProduct)
async def update_product(product_id: str, updates: TikTokProductUpdate):
    """Update a product."""
    service = get_tiktok_shop_service()
    product = await service.update_product(product_id, updates)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.patch("/products/{product_id}/links")
async def set_product_links(
    product_id: str,
    affiliate_link: Optional[str] = Body(None),
    tiktok_shop_url: Optional[str] = Body(None),
):
    """Set or update the affiliate link and TikTok Shop URL for a product."""
    from pydantic import ValidationError

    service = get_tiktok_shop_service()
    try:
        updates = TikTokProductUpdate(
            affiliate_link=affiliate_link,
            tiktok_shop_url=tiktok_shop_url,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    product = await service.update_product(product_id, updates)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.delete("/products/{product_id}")
async def delete_product(product_id: str):
    """Delete a product."""
    service = get_tiktok_shop_service()
    deleted = await service.delete_product(product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "deleted", "product_id": product_id}


# ============================================
# RESEARCH
# ============================================

@router.post("/products/{product_id}/research", response_model=TikTokProduct)
async def research_product(product_id: str):
    """Deep research a single product."""
    service = get_tiktok_shop_service()
    product = await service.research_product_deep(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/products/{product_id}/ideas")
async def generate_ideas(product_id: str):
    """Generate content ideas for a product."""
    service = get_tiktok_shop_service()
    ideas = await service.generate_content_ideas(product_id)
    return {"product_id": product_id, "ideas": ideas}


@router.post("/products/{product_id}/enrich", response_model=TikTokProduct)
async def enrich_product(product_id: str):
    """Enrich a product with image, sourcing info, and success rating."""
    service = get_tiktok_shop_service()
    product = await service.enrich_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/research/cycle", response_model=TikTokResearchCycleResult)
async def run_research_cycle():
    """Manually trigger the TikTok Shop research cycle."""
    service = get_tiktok_shop_service()
    return await service.run_daily_research_cycle()


# ============================================
# STATS
# ============================================

@router.get("/stats", response_model=TikTokShopStats)
async def get_stats():
    """Get TikTok Shop research statistics."""
    service = get_tiktok_shop_service()
    return await service.get_stats()


# ============================================
# SETUP GUIDE
# ============================================

@router.get("/setup-guide")
async def get_setup_guide():
    """Return TikTok Shop setup guide as structured JSON."""
    return {
        "title": "TikTok Shop Affiliate Setup Guide",
        "steps": [
            {
                "step": 1,
                "title": "Join TikTok Shop as Affiliate",
                "description": "Sign up at seller-us.tiktok.com and choose 'Affiliate/Creator'. Complete KYC verification with your government ID.",
                "link": "https://seller-us.tiktok.com",
                "required": True,
            },
            {
                "step": 2,
                "title": "Enable Product Showcase",
                "description": "In the TikTok app, go to Settings > Creator tools > TikTok Shop. Enable Product Showcase to create your curated storefront.",
                "required": True,
            },
            {
                "step": 3,
                "title": "Browse Affiliate Marketplace",
                "description": "In TikTok Shop, browse the Affiliate Marketplace to find products with high commission rates (10-30%). Request samples from sellers for free product.",
                "required": True,
            },
            {
                "step": 4,
                "title": "Let Zero Discover Products",
                "description": "Zero automatically researches trending products every 4 hours, scores them, and identifies high-commission affiliate opportunities. Review the Approval Queue regularly.",
                "required": False,
            },
            {
                "step": 5,
                "title": "Review and Approve Products",
                "description": "Check the Approval Queue tab to review discovered products. Approve products you want to promote. Zero auto-approves products scoring >= 85.",
                "required": False,
            },
            {
                "step": 6,
                "title": "Generate Content",
                "description": "Zero auto-generates video scripts and carousel content for approved products using AIContentTools. Review content in the Review tab.",
                "required": False,
            },
            {
                "step": 7,
                "title": "Post to TikTok",
                "description": "Use the Export button to get ready-to-post captions and hashtags. Create your TikTok post, then click 'Mark as Published' to track it.",
                "required": False,
            },
        ],
        "scheduled_jobs": [
            {"name": "Product Research", "frequency": "Every 4 hours", "description": "Discovers new trending affiliate products via SearXNG"},
            {"name": "Niche Deep Dive", "frequency": "Daily at 2 PM", "description": "Deep research into top-performing niches"},
            {"name": "Niche Rotation", "frequency": "Every 3 hours", "description": "Rotates through niches for broader product discovery"},
            {"name": "Approval Reminder", "frequency": "9 AM & 5 PM", "description": "Discord notification for pending product reviews"},
            {"name": "Content Pipeline", "frequency": "Every 6 hours", "description": "Auto-generates scripts for approved products via AIContentTools"},
            {"name": "Generation Check", "frequency": "Every 15 min", "description": "Checks AIContentTools for completed video generation"},
            {"name": "Performance Sync", "frequency": "Every 3 hours", "description": "Syncs metrics and runs improvement cycles"},
            {"name": "Pipeline Health", "frequency": "Every 2 hours", "description": "Health check, alerts on failures, retries stuck jobs"},
            {"name": "Weekly Report", "frequency": "Sunday 10 AM", "description": "Full performance report to Discord"},
        ],
    }


# ============================================
# PIPELINE
# ============================================

@router.post("/pipeline/run")
async def run_pipeline(
    mode: str = Query("full", description="Pipeline mode: full, research_only, content_only, performance_only"),
):
    """Trigger the full TikTok Shop agent pipeline."""
    from app.services.tiktok_agent_graph import invoke_tiktok_pipeline
    result = await invoke_tiktok_pipeline(mode=mode)
    return result


# ============================================
# CATALOG
# ============================================

@router.get("/catalog")
async def get_catalog(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Get active/approved products with content stats for the catalog view."""
    service = get_tiktok_shop_service()
    approved = await service.list_products(status="approved", limit=limit, offset=offset)
    active = await service.list_products(status="active", limit=limit, offset=offset)
    content_planned = await service.list_products(status="content_planned", limit=limit, offset=offset)
    all_catalog = approved + active + content_planned

    try:
        from app.db.models import VideoScriptModel
        from app.infrastructure.database import get_session
        from sqlalchemy import select, func

        product_ids = [p.id for p in all_catalog]
        if not product_ids:
            return []

        # Single batch query instead of N+1
        async with get_session() as session:
            result = await session.execute(
                select(
                    VideoScriptModel.product_id,
                    func.count(VideoScriptModel.id).label("script_count"),
                    func.count(VideoScriptModel.id).filter(
                        VideoScriptModel.status.in_(["approved", "queued", "generated"])
                    ).label("scripts_generated"),
                )
                .where(VideoScriptModel.product_id.in_(product_ids))
                .group_by(VideoScriptModel.product_id)
            )
            script_stats = {row.product_id: {"script_count": row.script_count, "scripts_generated": row.scripts_generated} for row in result}

        enriched = []
        for product in all_catalog:
            product_dict = product.model_dump()
            stats = script_stats.get(product.id, {"script_count": 0, "scripts_generated": 0})
            product_dict["script_count"] = stats["script_count"]
            product_dict["scripts_generated"] = stats["scripts_generated"]
            enriched.append(product_dict)
        return enriched
    except Exception:
        return [p.model_dump() for p in all_catalog]


@router.get("/catalog/{product_id}/content")
async def get_product_content(product_id: str):
    """Get all content (scripts + queue items) for a product."""
    try:
        from app.services.tiktok_video_service import get_tiktok_video_service
        video_svc = get_tiktok_video_service()
        scripts = await video_svc.list_scripts(product_id=product_id)
        queue = await video_svc.list_content_queue(product_id=product_id)
        return {
            "product_id": product_id,
            "scripts": [s.model_dump() for s in scripts],
            "queue_items": [q.model_dump() for q in queue],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# E2E TEST
# ============================================

@router.post("/e2e-test/seed")
async def seed_e2e_test(
    count: int = Query(5, ge=1, le=10, description="Number of products to seed"),
):
    """Run E2E test: research → discover → approve → generate scripts → queue for review.

    Seeds the pipeline with real trending products discovered via SearXNG,
    generates video scripts using different templates, and queues them for review.
    """
    service = get_tiktok_shop_service()
    return await service.seed_e2e_test(count=count)


# ============================================
# CONTENT REVIEW
# ============================================

@router.get("/review")
async def list_review_items(
    status: Optional[str] = Query(None, description="Filter: pending_review, approved, published, publish_failed, rejected"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List content items for review with full product + script + publishing details."""
    pub_svc = get_publishing_service()
    return await pub_svc.get_review_items(status=status, limit=limit, offset=offset)


@router.get("/review/{queue_id}")
async def get_review_item(queue_id: str):
    """Get a single review item."""
    pub_svc = get_publishing_service()
    item = await pub_svc.get_review_item(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item


@router.post("/review/{queue_id}/approve")
async def approve_content(queue_id: str, data: Optional[ContentApproval] = None):
    """Approve content for publishing, optionally editing caption and hashtags."""
    pub_svc = get_publishing_service()
    result = await pub_svc.approve_content(
        queue_id=queue_id,
        caption=data.caption if data else None,
        hashtags=data.hashtags if data else None,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Content not found")
    return result


@router.post("/review/{queue_id}/reject")
async def reject_content(queue_id: str, reason: Optional[str] = Query(None)):
    """Reject content from the review queue."""
    pub_svc = get_publishing_service()
    success = await pub_svc.reject_content(queue_id, reason)
    if not success:
        raise HTTPException(status_code=404, detail="Content not found")
    return {"status": "rejected", "queue_id": queue_id}


# ============================================
# PUBLISHING
# ============================================

@router.post("/review/{queue_id}/publish")
async def publish_content(queue_id: str, data: Optional[PublishRequest] = None):
    """Publish approved content to TikTok (or other platform)."""
    pub_svc = get_publishing_service()
    platform = data.platform if data else "tiktok"
    result = await pub_svc.publish_content(queue_id, platform=platform)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Publishing failed"))
    return result


@router.post("/review/publish-all")
async def publish_all_approved(platform: str = Query("tiktok")):
    """Batch publish all approved content items."""
    pub_svc = get_publishing_service()
    return await pub_svc.publish_all_approved(platform=platform)


@router.post("/review/{queue_id}/mark-published")
async def mark_manually_published(
    queue_id: str,
    tiktok_url: str = Query(..., description="The TikTok URL of the published post"),
):
    """Mark content as published when done manually (paste TikTok URL)."""
    from app.infrastructure.database import get_session
    from app.db.models import ContentQueueModel
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(
            select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Content not found")
        row.publish_status = "published"
        row.publish_url = tiktok_url
        row.manually_published_url = tiktok_url
        row.publish_platform = "tiktok"
        row.published_at = datetime.now(timezone.utc)
        await session.flush()
    return {"status": "published", "queue_id": queue_id, "url": tiktok_url}


@router.get("/review/{queue_id}/export")
async def export_for_posting(queue_id: str):
    """Get everything needed for manual posting: caption, hashtags, image URLs, script."""
    pub_svc = get_publishing_service()
    item = await pub_svc.get_review_item(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    # Build complete posting package
    caption = item.get("publish", {}).get("caption", "")
    hashtags = item.get("publish", {}).get("hashtags", [])
    hashtag_text = " ".join(f"#{h.strip('#')}" for h in hashtags) if hashtags else ""
    full_caption = f"{caption}\n\n{hashtag_text}" if hashtag_text else caption

    return {
        "queue_id": queue_id,
        "full_caption": full_caption,
        "caption_only": caption,
        "hashtags": hashtags,
        "hashtag_text": hashtag_text,
        "product_name": item.get("product", {}).get("name", ""),
        "product_image": item.get("product", {}).get("image_url", ""),
        "script": {
            "hook": item.get("script", {}).get("hook_text", ""),
            "voiceover": item.get("script", {}).get("voiceover_script", ""),
            "text_overlays": item.get("script", {}).get("text_overlays", []),
            "template_type": item.get("script", {}).get("template_type", ""),
        },
        "instructions": "Copy the full_caption, download the product image, and create your TikTok post.",
    }


@router.post("/review/{queue_id}/performance")
async def update_performance(
    queue_id: str,
    views: int = Body(0),
    likes: int = Body(0),
    comments: int = Body(0),
    shares: int = Body(0),
):
    """Manually enter performance metrics for published content."""
    from app.infrastructure.database import get_session
    from app.db.models import ContentQueueModel
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(
            select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Content not found")
        row.performance_views = views
        row.performance_likes = likes
        row.performance_comments = comments
        row.performance_shares = shares
        await session.flush()
    return {"status": "updated", "queue_id": queue_id, "views": views, "likes": likes, "comments": comments, "shares": shares}


@router.get("/publish/status")
async def get_publish_status():
    """Check platform readiness and queue counts."""
    pub_svc = get_publishing_service()
    return await pub_svc.get_publish_readiness()


# ============================================
# TIKTOK OAUTH
# ============================================

@router.get("/auth/url")
async def get_tiktok_auth_url():
    """Generate TikTok OAuth authorization URL."""
    from app.infrastructure.tiktok_api_client import get_tiktok_api_client
    client = get_tiktok_api_client()
    url = client.get_authorize_url()
    if not url:
        raise HTTPException(
            status_code=400,
            detail="TikTok API not configured. Set ZERO_TIKTOK_CLIENT_KEY and ZERO_TIKTOK_CLIENT_SECRET.",
        )
    return {"authorize_url": url}


@router.get("/auth/callback")
async def tiktok_auth_callback(code: str, state: str = "zero_tiktok"):
    """Handle TikTok OAuth callback."""
    from app.infrastructure.tiktok_api_client import get_tiktok_api_client
    from app.infrastructure.config import get_settings

    client = get_tiktok_api_client()
    success = await client.exchange_code(code)

    frontend_url = get_settings().frontend_url
    if success:
        return RedirectResponse(url=f"{frontend_url}/tiktok-shop?auth=success")
    else:
        return RedirectResponse(url=f"{frontend_url}/tiktok-shop?auth=failed")


@router.get("/auth/status")
async def get_tiktok_auth_status():
    """Check TikTok authorization status."""
    from app.infrastructure.tiktok_api_client import get_tiktok_api_client
    client = get_tiktok_api_client()
    if not client.is_authorized:
        await client.load_tokens_from_db()
    return client.get_status()


# ============================================
# REFERENCE VIDEOS (Video Inspiration / Copy)
# ============================================

@router.post("/references", response_model=ReferenceVideo)
async def create_reference_video(data: ReferenceVideoCreate):
    """Paste a TikTok video URL to analyze and use as content inspiration."""
    svc = get_reference_video_service()
    return await svc.create_reference(data)


@router.get("/references", response_model=List[ReferenceVideo])
async def list_reference_videos(
    product_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List reference videos, optionally filtered by product or status."""
    svc = get_reference_video_service()
    return await svc.list_references(product_id=product_id, status=status, limit=limit, offset=offset)


@router.get("/references/{ref_id}", response_model=ReferenceVideo)
async def get_reference_video(ref_id: str):
    """Get a single reference video with analysis."""
    svc = get_reference_video_service()
    ref = await svc.get_reference(ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="Reference video not found")
    return ref


@router.post("/references/{ref_id}/analyze", response_model=ReferenceVideo)
async def analyze_reference_video(ref_id: str):
    """Trigger or re-trigger analysis of a reference video."""
    svc = get_reference_video_service()
    try:
        return await svc.analyze_video(ref_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/references/{ref_id}/copy-script")
async def copy_script_from_reference(
    ref_id: str,
    product_id: str = Query(..., description="Product to create the script for"),
    template_type: str = Query("voiceover_broll", description="Script template type"),
):
    """Generate a video script for a product that copies the style of the reference video."""
    svc = get_reference_video_service()
    try:
        return await svc.generate_script_from_reference(ref_id, product_id, template_type)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/references/{ref_id}")
async def delete_reference_video(ref_id: str):
    """Delete a reference video."""
    svc = get_reference_video_service()
    deleted = await svc.delete_reference(ref_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Reference video not found")
    return {"status": "deleted", "ref_id": ref_id}


# ============================================
# AUTOMATION CONFIG
# ============================================

@router.get("/config")
async def get_tiktok_config():
    """Get current TikTok Shop automation configuration."""
    service = get_tiktok_shop_service()
    config = await service._get_config()
    return {
        "auto_approve_threshold": config.get("auto_approve_threshold", 85.0),
        "auto_enrichment_enabled": config.get("auto_enrichment_enabled", True),
        "pipeline_default_mode": config.get("pipeline_default_mode", "full"),
    }


@router.patch("/config")
async def update_tiktok_config(updates: Dict[str, Any] = Body(...)):
    """Update TikTok Shop automation configuration."""
    allowed_keys = {"auto_approve_threshold", "auto_enrichment_enabled", "pipeline_default_mode"}
    filtered = {k: v for k, v in updates.items() if k in allowed_keys}
    if not filtered:
        raise HTTPException(status_code=400, detail=f"No valid config keys. Allowed: {allowed_keys}")

    from app.infrastructure.database import get_session
    from app.db.models import ServiceConfigModel
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(
            select(ServiceConfigModel).where(ServiceConfigModel.service_name == "tiktok_shop")
        )
        row = result.scalar_one_or_none()
        if row:
            current = row.config or {}
            current.update(filtered)
            row.config = current
        else:
            row = ServiceConfigModel(
                service_name="tiktok_shop",
                config=filtered,
            )
            session.add(row)
        await session.flush()

    return {"status": "updated", **filtered}


# ============================================
# PIPELINE STATUS
# ============================================

@router.get("/pipeline/status")
async def get_pipeline_status():
    """Get last run times and results for all TikTok pipeline scheduler jobs."""
    from app.infrastructure.database import get_session
    from app.db.models import SchedulerAuditLogModel
    from sqlalchemy import select, desc

    tiktok_jobs = [
        "tiktok_continuous_research", "tiktok_niche_deep_dive", "tiktok_niche_rotation",
        "tiktok_approval_reminder", "tiktok_auto_content_pipeline",
        "tiktok_content_generation_check", "tiktok_performance_sync",
        "tiktok_pipeline_health", "tiktok_weekly_report",
        "tiktok_shop_research", "tiktok_shop_deep_research", "tiktok_image_revalidation",
    ]

    statuses = []
    try:
        async with get_session() as session:
            for job_name in tiktok_jobs:
                result = await session.execute(
                    select(SchedulerAuditLogModel)
                    .where(SchedulerAuditLogModel.job_name == job_name)
                    .order_by(desc(SchedulerAuditLogModel.started_at))
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row:
                    statuses.append({
                        "job_name": job_name,
                        "last_run": row.started_at.isoformat() if row.started_at else None,
                        "status": row.status,
                        "duration_seconds": row.duration_seconds,
                        "error": row.error,
                    })
                else:
                    statuses.append({
                        "job_name": job_name,
                        "last_run": None,
                        "status": "never_run",
                        "duration_seconds": None,
                        "error": None,
                    })
    except Exception as e:
        logger.warning("pipeline_status_fetch_failed", error=str(e))
        statuses = [{"job_name": j, "last_run": None, "status": "unknown", "duration_seconds": None, "error": None} for j in tiktok_jobs]

    return {"jobs": statuses}


# ============================================
# TEMPLATE ANALYTICS
# ============================================

@router.get("/analytics/templates")
async def get_template_analytics():
    """Get template performance analytics across all niches."""
    service = get_tiktok_shop_service()
    return await service.get_template_analytics()


@router.get("/analytics/best-template/{niche}")
async def get_best_template(niche: str):
    """Get the best-performing template type for a specific niche."""
    service = get_tiktok_shop_service()
    best = await service.get_best_template_for_niche(niche)
    return {"niche": niche, "best_template": best or "voiceover_broll"}
