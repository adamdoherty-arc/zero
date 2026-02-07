"""
Ecosystem monitoring and cross-project sync endpoints.
Sprint 70: Ecosystem Orchestration & Cross-Project Sync.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict, List, Optional

router = APIRouter()


@router.get("/status")
async def ecosystem_status() -> Dict[str, Any]:
    """
    Full ecosystem status: all projects with sprint info, health scores,
    task summaries, and alert counts. Served from local cache (fast).
    """
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    status = await svc.get_cached_status()

    if not status.get("projects"):
        return {
            **status,
            "hint": "No data cached yet. Trigger a sync with POST /api/ecosystem/sync/trigger?full=true",
        }

    return status


@router.get("/projects/{project_id}/sprint")
async def project_current_sprint(project_id: int) -> Dict[str, Any]:
    """Get current sprint + tasks for a specific project from cache."""
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    result = await svc.get_cached_project_sprint(project_id)
    if not result:
        raise HTTPException(404, f"Project {project_id} not found in cache. Run a full sync first.")
    return result


@router.get("/timeline")
async def sprint_timeline() -> Dict[str, Any]:
    """All active sprints across projects for timeline visualization."""
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    sprints = await svc.get_cached_timeline()
    return {"sprints": sprints, "count": len(sprints)}


@router.get("/alerts")
async def ecosystem_alerts() -> Dict[str, Any]:
    """
    Unified alert feed: blocked tasks, stale sprints, failed executions.
    Sorted by severity (critical first).
    """
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    alerts = await svc.get_alerts()
    return {
        "alerts": alerts,
        "count": len(alerts),
        "critical": sum(1 for a in alerts if a.get("severity") == "critical"),
        "warning": sum(1 for a in alerts if a.get("severity") == "warning"),
    }


@router.get("/sync/status")
async def sync_status() -> Dict[str, Any]:
    """Sync timing: last sync times, change event count."""
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    return await svc.get_sync_status()


@router.post("/sync/trigger")
async def trigger_sync(full: bool = False) -> Dict[str, Any]:
    """Manually trigger a quick or full ecosystem sync."""
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()

    if full:
        return await svc.full_sync()
    return await svc.quick_sync()


@router.get("/changes")
async def recent_changes(limit: int = Query(default=50, le=200)) -> Dict[str, Any]:
    """Get recent ecosystem change events."""
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    events = await svc.get_change_events(limit=limit)
    return {"events": events, "count": len(events)}


@router.get("/health-scores")
async def project_health_scores() -> Dict[str, Any]:
    """Per-project health scores with breakdown."""
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    scores = await svc.compute_project_health_scores()
    return {
        "scores": {str(k): v for k, v in scores.items()},
        "count": len(scores),
    }


@router.get("/risks")
async def ecosystem_risks() -> Dict[str, Any]:
    """Detected risks across all projects, sorted by severity."""
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    risks = await svc.detect_risks()
    return {"risks": risks, "count": len(risks)}


@router.get("/suggestions")
async def lifecycle_suggestions() -> Dict[str, Any]:
    """Natural language suggestions based on sprint lifecycle analysis."""
    from app.services.ecosystem_sync_service import get_ecosystem_sync_service
    svc = get_ecosystem_sync_service()
    suggestions = await svc.generate_lifecycle_suggestions()
    return {"suggestions": suggestions, "count": len(suggestions)}


# ============================================
# ORCHESTRATION ENDPOINTS (S70 Phase 2)
# ============================================

@router.get("/orchestration/status")
async def orchestration_status() -> Dict[str, Any]:
    """
    Orchestration status: last daily run, last monitor, next scheduled,
    and recent actions taken by the autopilot.
    """
    from app.services.autonomous_orchestration_service import get_orchestration_service
    svc = get_orchestration_service()
    return await svc.get_orchestration_status()


@router.post("/orchestration/trigger")
async def trigger_orchestration() -> Dict[str, Any]:
    """Manually trigger the daily orchestration cycle."""
    from app.services.autonomous_orchestration_service import get_orchestration_service
    svc = get_orchestration_service()
    return await svc.run_daily_orchestration()


@router.get("/orchestration/log")
async def orchestration_log(limit: int = Query(default=50, le=200)) -> Dict[str, Any]:
    """Get recent orchestration actions log."""
    from app.services.autonomous_orchestration_service import get_orchestration_service
    svc = get_orchestration_service()
    entries = await svc.get_orchestration_log(limit=limit)
    return {"entries": entries, "count": len(entries)}
