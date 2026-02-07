"""
System management endpoints for ZERO API.

Provides circuit breaker status, scheduler audit log, backup management,
and other operational endpoints.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

router = APIRouter()


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
    return svc.get_audit_log(limit=limit)


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


@router.post("/backups")
async def trigger_backup(tier: str = "hourly") -> Dict[str, Any]:
    """Trigger a manual backup."""
    if tier not in ("hourly", "daily", "weekly"):
        raise HTTPException(400, "tier must be one of: hourly, daily, weekly")
    from app.services.backup_service import get_backup_service
    return await get_backup_service().create_backup(tier=tier)
