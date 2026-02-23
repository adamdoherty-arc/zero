"""
TikTok Shop Research Agent API endpoints.
REST API for managing TikTok Shop product discovery, research, and opportunity scoring.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import structlog

from app.models.tiktok_shop import (
    TikTokProduct, TikTokProductCreate, TikTokProductUpdate,
    TikTokProductStatus, TikTokProductApproval,
    TikTokResearchCycleResult, TikTokShopStats,
)
from app.services.tiktok_shop_service import get_tiktok_shop_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================
# APPROVAL QUEUE (must be before /products/{product_id})
# ============================================

@router.get("/products/pending", response_model=List[TikTokProduct])
async def list_pending_products(
    limit: int = Query(50, ge=1, le=200),
):
    """List products pending approval."""
    service = get_tiktok_shop_service()
    return await service.list_pending(limit=limit)


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


# ============================================
# PRODUCTS
# ============================================

@router.get("/products", response_model=List[TikTokProduct])
async def list_products(
    status: Optional[TikTokProductStatus] = Query(None, description="Filter by status"),
    niche: Optional[str] = Query(None, description="Filter by niche"),
    min_score: Optional[float] = Query(None, ge=0, le=100, description="Minimum opportunity score"),
    limit: int = Query(50, ge=1, le=200),
):
    """List TikTok Shop products."""
    service = get_tiktok_shop_service()
    return await service.list_products(
        status=status.value if status else None,
        niche=niche,
        min_score=min_score,
        limit=limit,
    )


@router.post("/products", response_model=TikTokProduct)
async def create_product(data: TikTokProductCreate):
    """Manually add a TikTok Shop product."""
    service = get_tiktok_shop_service()
    return await service.create_product(data)


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
        "title": "TikTok Shop Setup Guide",
        "steps": [
            {
                "step": 1,
                "title": "Create a TikTok Seller Account",
                "description": "Sign up at seller-us.tiktok.com to create your TikTok Shop seller account.",
                "link": "https://seller-us.tiktok.com",
                "required": True,
            },
            {
                "step": 2,
                "title": "Choose Your Business Model",
                "description": "Decide between Affiliate (promote others' products for commission), Dropship (list products, supplier handles fulfillment), or Own Products (full control over inventory).",
                "options": ["Affiliate - Lowest barrier, earn commission", "Dropship - List products, no inventory", "Own Products - Full control, higher margins"],
                "required": True,
            },
            {
                "step": 3,
                "title": "Set Up TikTok for Business",
                "description": "Create a TikTok Business account linked to your seller account and enable TikTok Shopping features.",
                "link": "https://www.tiktok.com/business",
                "required": True,
            },
            {
                "step": 4,
                "title": "Configure Zero Automation",
                "description": "Zero automatically researches trending products every 4 hours, scores them, and generates faceless video scripts. Products scoring >= 85 are auto-approved.",
                "required": False,
            },
            {
                "step": 5,
                "title": "Review the Approval Queue",
                "description": "Check the Product Research tab regularly to review and approve discovered products. Approved products enter the content pipeline.",
                "required": False,
            },
            {
                "step": 6,
                "title": "Set Up AIContentTools (Optional)",
                "description": "For automated video generation, ensure AIContentTools is running at C:\\code\\AIContentTools on port 8085.",
                "required": False,
            },
        ],
        "scheduled_jobs": [
            {"name": "Product Research", "frequency": "Every 4 hours", "description": "Discovers new trending products via SearXNG"},
            {"name": "Niche Deep Dive", "frequency": "Daily at 2 PM", "description": "Deep research into top-performing niches"},
            {"name": "Approval Reminder", "frequency": "9 AM & 5 PM", "description": "Discord notification for pending product reviews"},
            {"name": "Content Pipeline", "frequency": "Every 6 hours", "description": "Auto-generates scripts for approved products"},
            {"name": "Generation Check", "frequency": "Every 15 min", "description": "Polls AIContentTools for completed videos"},
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
):
    """Get active/approved products with content stats for the catalog view."""
    service = get_tiktok_shop_service()
    approved = await service.list_products(status="approved", limit=limit)
    active = await service.list_products(status="active", limit=limit)
    content_planned = await service.list_products(status="content_planned", limit=limit)
    all_catalog = approved + active + content_planned

    try:
        from app.services.tiktok_video_service import get_tiktok_video_service
        video_svc = get_tiktok_video_service()
        enriched = []
        for product in all_catalog:
            scripts = await video_svc.list_scripts(product_id=product.id)
            product_dict = product.model_dump()
            product_dict["script_count"] = len(scripts)
            product_dict["scripts_generated"] = len([s for s in scripts if s.status in ("approved", "queued", "generated")])
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
        queue = await video_svc.list_content_queue()
        product_queue = [q for q in queue if q.product_id == product_id]
        return {
            "product_id": product_id,
            "scripts": [s.model_dump() for s in scripts],
            "queue_items": [q.model_dump() for q in product_queue],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
