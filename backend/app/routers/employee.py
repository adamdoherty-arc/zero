"""
Employee Check-in API — Phase 036 (24/7 Employee).

Exposes the aggregate check-in + history used by the frontend dashboard and
the /zero-employee-checkin skill.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.db.models import EmployeeCheckinModel
from app.infrastructure.auth import require_auth
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])


def _row_to_dict(row: EmployeeCheckinModel) -> Dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "ops_grade": row.ops_grade,
        "overall_grade": row.overall_grade,
        "subsystem_grades": row.subsystem_grades or {},
        "accomplishments": row.accomplishments or {},
        "issues": row.issues or [],
        "wins": row.wins or [],
        "legion_task_ids": row.legion_task_ids or [],
        "full_report": row.full_report or {},
    }


@router.post("/checkin/run", response_model=Dict[str, Any])
async def run_checkin(window_hours: int = Query(24, ge=1, le=168)):
    """Trigger an immediate check-in (normally runs daily via scheduler)."""
    from app.services.employee_checkin_service import get_employee_checkin_service
    return await get_employee_checkin_service().run_checkin(window_hours=window_hours)


@router.get("/checkin/latest", response_model=Dict[str, Any])
async def get_latest_checkin():
    async with get_session() as session:
        q = (
            select(EmployeeCheckinModel)
            .order_by(EmployeeCheckinModel.created_at.desc())
            .limit(1)
        )
        row = (await session.execute(q)).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="no employee check-in recorded yet")
    return _row_to_dict(row)


@router.get("/checkin/history", response_model=List[Dict[str, Any]])
async def get_checkin_history(days: int = Query(30, ge=1, le=180)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_session() as session:
        q = (
            select(EmployeeCheckinModel)
            .where(EmployeeCheckinModel.created_at >= since)
            .order_by(EmployeeCheckinModel.created_at.desc())
        )
        rows = (await session.execute(q)).scalars().all()
    return [_row_to_dict(r) for r in rows]
