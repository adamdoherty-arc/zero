"""
Ecosystem Health router.

Provides live health-check endpoints for all services in the AI ecosystem.
Mounted under /api/ecosystem/health to complement the existing ecosystem router.
"""

from fastapi import APIRouter, HTTPException
from typing import Any, Dict

router = APIRouter()


@router.get("")
async def ecosystem_health() -> Dict[str, Any]:
    """
    Full ecosystem health check — pings every registered service
    and returns status, response times, and an overall summary.
    """
    from app.services.ecosystem_health_service import get_ecosystem_health_service
    svc = get_ecosystem_health_service()
    return await svc.get_summary()


@router.get("/{service}")
async def service_health(service: str) -> Dict[str, Any]:
    """
    Health check for a single ecosystem service by name.
    """
    from app.services.ecosystem_health_service import (
        ECOSYSTEM_SERVICES,
        get_ecosystem_health_service,
    )

    if service not in ECOSYSTEM_SERVICES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown service '{service}'. Available: {list(ECOSYSTEM_SERVICES.keys())}",
        )

    svc = get_ecosystem_health_service()
    result = await svc.check_service(service)
    return {"service": service, **result}
