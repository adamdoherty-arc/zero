"""
Prediction Markets Router.
REST API for prediction market data collection, bettor tracking, and quality reporting.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
import structlog

from app.infrastructure.auth import require_auth

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# Market Endpoints
# ---------------------------------------------------------------------------

@router.get("/markets")
async def list_markets(
    platform: Optional[str] = Query(None, description="Filter by platform: kalshi or polymarket"),
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query("open", description="Filter by status: open, closed, settled"),
    limit: int = Query(50, ge=1, le=200),
):
    """List prediction markets with optional filters."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    markets = await svc.list_markets(platform=platform, category=category, status=status, limit=limit)
    return {"markets": [m.model_dump() for m in markets], "count": len(markets)}


@router.get("/bettors")
async def list_bettors(
    platform: Optional[str] = Query(None, description="Filter by platform"),
    min_win_rate: Optional[float] = Query(None, ge=0, le=1, description="Minimum win rate"),
    limit: int = Query(50, ge=1, le=200),
):
    """List tracked bettors ranked by composite score."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    bettors = await svc.list_bettors(platform=platform, min_win_rate=min_win_rate, limit=limit)
    return {"bettors": [b.model_dump() for b in bettors], "count": len(bettors)}


@router.get("/stats")
async def get_stats():
    """Get aggregate prediction market statistics."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    stats = await svc.get_stats()
    return stats.model_dump()


@router.get("/snapshots/{market_id}")
async def get_market_snapshots(
    market_id: str,
    hours: int = Query(24, ge=1, le=168),
):
    """Get price snapshots for a specific market."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    snapshots = await svc.get_market_snapshots(market_id=market_id, hours=hours)
    return {"snapshots": [s.model_dump() for s in snapshots], "count": len(snapshots)}


# ---------------------------------------------------------------------------
# Sync / Cycle Triggers
# ---------------------------------------------------------------------------

@router.post("/sync/kalshi")
async def sync_kalshi():
    """Manually trigger Kalshi market sync."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    result = await svc.sync_kalshi_markets()
    return result


@router.post("/sync/polymarket")
async def sync_polymarket():
    """Manually trigger Polymarket sync."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    result = await svc.sync_polymarket_markets()
    return result


@router.post("/sync/bettors")
async def sync_bettors():
    """Manually trigger bettor discovery."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    result = await svc.discover_top_bettors()
    return result


@router.post("/cycle/run")
async def run_full_cycle():
    """Run a full prediction market research cycle."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()

    results = {}
    results["kalshi"] = await svc.sync_kalshi_markets()
    results["polymarket"] = await svc.sync_polymarket_markets()
    results["snapshots"] = await svc.capture_price_snapshots()
    results["bettors"] = await svc.discover_top_bettors()
    results["research"] = await svc.research_market_insights()
    results["push"] = await svc.push_to_ada()

    return {"status": "completed", "results": results}


@router.post("/push")
async def push_to_ada():
    """Manually push data to ADA."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    result = await svc.push_to_ada()
    return result


# ---------------------------------------------------------------------------
# Quality & Oversight
# ---------------------------------------------------------------------------

@router.get("/quality-report")
async def get_quality_report():
    """Get quality report for Claude oversight."""
    from app.services.prediction_market_service import get_prediction_market_service
    svc = get_prediction_market_service()
    report = await svc.get_quality_report()
    return report


@router.get("/legion-status")
async def get_legion_status():
    """Get Legion sprint progress for prediction market work."""
    from app.services.prediction_legion_manager import get_prediction_legion_manager
    try:
        mgr = get_prediction_legion_manager()
        report = await mgr.get_full_progress_report()
        return report
    except Exception as e:
        logger.warning("legion_status_error", error=str(e))
        return {"error": str(e), "status": "unavailable"}
