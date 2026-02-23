"""
System management endpoints for ZERO API.

Provides circuit breaker status, scheduler audit log, backup management,
self-knowledge introspection, and other operational endpoints.
"""

import os
import json
from fastapi import APIRouter, HTTPException
from typing import Dict, Any

router = APIRouter()


@router.get("/status")
async def get_system_status() -> Dict[str, Any]:
    """Simple status endpoint for auth validation and system overview."""
    return {"status": "ok", "service": "zero-api"}


@router.get("/self-knowledge")
async def get_self_knowledge() -> Dict[str, Any]:
    """Return Zero's complete architecture as structured JSON for self-awareness."""
    # In Docker, app root is /app; config/workspace/backups are mounted there
    app_root = os.environ.get("APP_ROOT", "/app")

    # Count skills (may not be mounted in Docker - read from config if available)
    skills: list = []
    for skills_dir in [os.path.join(app_root, "skills"), os.path.join(app_root, "..", "skills")]:
        if os.path.isdir(skills_dir):
            skills = sorted([d for d in os.listdir(skills_dir) if os.path.isdir(os.path.join(skills_dir, d))])
            break
    # Fallback: read skill list from workspace metadata if skills dir not mounted
    if not skills:
        try:
            meta_path = os.path.join(app_root, "workspace", "self_knowledge_cache.json")
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    cached = json.load(f)
                skills = cached.get("skills", [])
        except Exception:
            pass

    # Get LLM config
    llm_info: Dict[str, Any] = {}
    try:
        from app.infrastructure.llm_router import get_llm_router
        router_svc = get_llm_router()
        llm_info = {
            "default_model": router_svc.default_model,
            "task_overrides": dict(router_svc.task_overrides) if hasattr(router_svc, "task_overrides") else {},
        }
    except Exception:
        llm_info = {"default_model": "unknown", "task_overrides": {}}

    # Get scheduler jobs
    scheduler_jobs = []
    try:
        from app.services.scheduler_service import get_scheduler_service
        svc = get_scheduler_service()
        status = svc.get_status()
        scheduler_jobs = status.get("jobs", [])
    except Exception:
        pass

    # Get orchestration routes
    orchestration_routes = []
    try:
        from app.services.orchestration_graph import VALID_ROUTES
        orchestration_routes = sorted(VALID_ROUTES)
    except Exception:
        pass

    # Gateway version from config
    gateway_version = "unknown"
    try:
        config_path = os.path.join(app_root, "config", "zero.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                gw_config = json.load(f)
            gateway_version = (
                gw_config.get("lastTouchedVersion")
                or gw_config.get("meta", {}).get("lastTouchedVersion", "unknown")
            )
    except Exception:
        pass

    return {
        "name": "Zero",
        "description": "24/7 Personal AI Assistant & Second Brain",
        "gateway_version": gateway_version,
        "architecture": {
            "routers": 22,
            "services": 38,
            "infrastructure_modules": 12,
            "database_tables": 20,
            "frontend_pages": 19,
            "frontend_hooks": 9,
            "scheduled_jobs": len(scheduler_jobs),
            "skills_installed": len(skills),
        },
        "containers": ["zero-api", "zero-ui", "zero-gateway", "zero-searxng", "zero-db"],
        "integrations": [
            "gmail", "google_calendar", "notion", "discord",
            "whatsapp", "slack", "github", "ollama", "searxng", "legion",
        ],
        "llm": llm_info,
        "orchestration_routes": orchestration_routes,
        "skills": skills,
        "scheduler_jobs_count": len(scheduler_jobs),
        "compose_files": [
            "docker-compose.sprint.yml (API + UI + DB)",
            "docker-compose.yml (Gateway)",
            "docker-compose.searxng.yml (Search)",
        ],
    }


# ============================================
# CIRCUIT BREAKERS
# ============================================

@router.get("/circuit-breakers")
async def list_circuit_breakers() -> Dict[str, Any]:
    """List all circuit breakers and their current status."""
    from app.infrastructure.circuit_breaker import all_circuit_breakers
    breakers = all_circuit_breakers()
    return {
        "circuit_breakers": [cb.status() for cb in breakers.values()],
        "count": len(breakers),
    }


@router.post("/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(name: str) -> Dict[str, Any]:
    """Manually reset a circuit breaker to CLOSED state."""
    from app.infrastructure.circuit_breaker import all_circuit_breakers
    breakers = all_circuit_breakers()
    if name not in breakers:
        raise HTTPException(404, f"Circuit breaker '{name}' not found")
    await breakers[name].reset()
    return {"reset": True, "name": name, "state": breakers[name].state.value}


# ============================================
# SCHEDULER AUDIT LOG
# ============================================

@router.get("/scheduler/status")
async def scheduler_status() -> Dict[str, Any]:
    """Get scheduler status with next run times."""
    from app.services.scheduler_service import get_scheduler_service
    return get_scheduler_service().get_status()


@router.get("/scheduler/audit")
async def scheduler_audit(limit: int = 50) -> Dict[str, Any]:
    """Get recent scheduler job execution history."""
    from app.services.scheduler_service import get_scheduler_service
    svc = get_scheduler_service()
    if not hasattr(svc, 'get_audit_log'):
        return {"executions": [], "message": "Audit log not yet available"}
    return await svc.get_audit_log(limit=limit)


@router.post("/scheduler/jobs/{job_name}/trigger")
async def trigger_job(job_name: str) -> Dict[str, Any]:
    """Manually trigger a scheduled job."""
    from app.services.scheduler_service import get_scheduler_service
    result = await get_scheduler_service().trigger_job(job_name)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Unknown error"))
    return result


# ============================================
# BACKUPS
# ============================================

@router.get("/backups")
async def list_backups() -> Dict[str, Any]:
    """List all available backups by tier."""
    try:
        from app.services.backup_service import get_backup_service
        return await get_backup_service().list_backups()
    except ImportError:
        return {"message": "Backup service not yet available"}


# ============================================
# METRICS & OBSERVABILITY
# ============================================

@router.get("/metrics")
async def get_metrics(hours: int = 24) -> Dict[str, Any]:
    """Get aggregated system metrics for the last N hours."""
    from app.services.metrics_service import get_metrics_service
    return get_metrics_service().get_summary(hours=hours)


@router.get("/metrics/timeseries/{name}")
async def get_timeseries(name: str, hours: int = 24, resolution: int = 5) -> Dict[str, Any]:
    """Get time-bucketed metric data for charts."""
    from app.services.metrics_service import get_metrics_service
    data = get_metrics_service().get_timeseries(name, hours=hours, resolution_minutes=resolution)
    return {"metric": name, "hours": hours, "resolution_minutes": resolution, "data": data}


@router.get("/metrics/history")
async def get_metrics_history(limit: int = 24) -> Dict[str, Any]:
    """Get historical metrics snapshots from PostgreSQL."""
    from app.infrastructure.database import get_session
    from sqlalchemy import text

    try:
        async with get_session() as session:
            result = await session.execute(
                text(
                    "SELECT id, timestamp, metrics_data, period FROM metrics_snapshots "
                    "ORDER BY timestamp DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
            rows = result.fetchall()
            return {
                "snapshots": [
                    {
                        "id": r[0],
                        "timestamp": r[1].isoformat() if r[1] else None,
                        "metrics_data": r[2],
                        "period": r[3],
                    }
                    for r in reversed(rows)
                ],
                "count": len(rows),
            }
    except Exception as e:
        return {"snapshots": [], "count": 0, "error": str(e)}


@router.get("/disk")
async def get_disk_status() -> Dict[str, Any]:
    """Get disk space usage."""
    import shutil
    try:
        usage = shutil.disk_usage("/")
        return {
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
            "percent_used": round((usage.used / usage.total) * 100, 1),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/alerting/status")
async def get_alerting_status() -> Dict[str, Any]:
    """Get current alerting status (active issues, recent alerts)."""
    from app.services.alerting_service import get_alerting_service
    return get_alerting_service().get_status()


# ============================================
# BACKUPS
# ============================================

@router.post("/backups")
async def trigger_backup(tier: str = "hourly") -> Dict[str, Any]:
    """Trigger a manual backup."""
    if tier not in ("hourly", "daily", "weekly"):
        raise HTTPException(400, "tier must be one of: hourly, daily, weekly")
    from app.services.backup_service import get_backup_service
    return await get_backup_service().create_backup(tier=tier)


@router.post("/backups/test-restore")
async def test_restore_backup() -> Dict[str, Any]:
    """Test-restore the most recent backup to verify integrity."""
    from app.services.backup_service import get_backup_service
    return await get_backup_service().test_restore()


# ============================================
# TOKEN ROTATION
# ============================================

@router.post("/auth/rotate")
async def rotate_token() -> Dict[str, Any]:
    """Generate a new API token with a 5-minute grace period for the old one."""
    import secrets
    import time as _time

    old_token = os.environ.get("ZERO_GATEWAY_TOKEN", "")
    new_token = secrets.token_urlsafe(32)

    # Store both tokens during grace period
    os.environ["ZERO_GATEWAY_TOKEN"] = new_token
    os.environ["ZERO_OLD_TOKEN"] = old_token
    os.environ["ZERO_TOKEN_GRACE_UNTIL"] = str(int(_time.time()) + 300)  # 5 min

    return {
        "rotated": True,
        "new_token": new_token,
        "grace_period_seconds": 300,
        "note": "Old token valid for 5 more minutes. Update all clients.",
    }


# ============================================
# FRONTEND ERROR REPORTING
# ============================================

@router.post("/errors")
async def report_frontend_error(body: Dict[str, Any]) -> Dict[str, str]:
    """Accept error reports from the frontend ErrorBoundary."""
    import structlog
    logger = structlog.get_logger("frontend_errors")
    logger.error(
        "frontend_error",
        message=body.get("message", ""),
        page=body.get("page", ""),
        timestamp=body.get("timestamp", ""),
    )
    return {"status": "recorded"}


# ============================================
# GATEWAY AUTO-UPDATE
# ============================================

@router.get("/gateway-version")
async def get_gateway_version() -> Dict[str, Any]:
    """Get current gateway version, latest available, and update status."""
    from app.services.gateway_updater_service import get_gateway_updater_service
    return await get_gateway_updater_service().get_update_status()


@router.post("/gateway-update/check")
async def check_gateway_update() -> Dict[str, Any]:
    """Manually trigger a gateway update check against GitHub releases."""
    from app.services.gateway_updater_service import get_gateway_updater_service
    return await get_gateway_updater_service().check_for_updates()
