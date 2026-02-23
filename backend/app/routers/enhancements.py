"""
Enhancement system API endpoints.
Integrates with Zero's enhancement system to track and create sprint tasks.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import structlog

from sqlalchemy import select, func as sa_func
from app.infrastructure.database import get_session
from app.db.models import EnhancementSignalModel
from app.services.task_service import get_task_service
from app.models.task import TaskCreate, TaskCategory, TaskPriority, TaskSource

router = APIRouter()
logger = structlog.get_logger()


class EnhancementSignal(BaseModel):
    """An enhancement signal detected by the system."""
    id: str
    type: str  # "todo", "fixme", "error", "performance", "qa_issue"
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    message: str
    severity: str  # "critical", "high", "medium", "low"
    detected_at: datetime
    status: str = "pending"  # "pending", "converted", "dismissed"


class EnhancementStats(BaseModel):
    """Enhancement system statistics."""
    total_signals: int
    pending: int
    converted_to_tasks: int
    dismissed: int
    by_type: Dict[str, int]
    by_severity: Dict[str, int]


class SignalToTaskRequest(BaseModel):
    """Request to convert a signal to a sprint task."""
    signal_id: str
    sprint_id: str
    title: Optional[str] = None
    priority: Optional[TaskPriority] = None
    points: Optional[int] = None


@router.get("/signals", response_model=List[EnhancementSignal])
async def get_signals(
    status: Optional[str] = Query(None, description="Filter by status"),
    type: Optional[str] = Query(None, description="Filter by signal type"),
    limit: int = Query(50, ge=1, le=200)
):
    """Get enhancement signals."""
    async with get_session() as session:
        query = select(EnhancementSignalModel)
        if status:
            query = query.where(EnhancementSignalModel.status == status)
        if type:
            query = query.where(EnhancementSignalModel.type == type)
        query = query.order_by(EnhancementSignalModel.detected_at.desc()).limit(limit)

        result = await session.execute(query)
        rows = result.scalars().all()

    return [
        EnhancementSignal(
            id=r.id, type=r.type, source_file=r.source_file,
            line_number=r.line_number, message=r.message,
            severity=r.severity, detected_at=r.detected_at, status=r.status
        )
        for r in rows
    ]


@router.get("/stats", response_model=EnhancementStats)
async def get_stats():
    """Get enhancement system statistics."""
    async with get_session() as session:
        # Total count
        total = (await session.execute(
            select(sa_func.count()).select_from(EnhancementSignalModel)
        )).scalar() or 0

        # By status
        status_result = await session.execute(
            select(EnhancementSignalModel.status, sa_func.count())
            .group_by(EnhancementSignalModel.status)
        )
        by_status = dict(status_result.all())

        # By type
        type_result = await session.execute(
            select(EnhancementSignalModel.type, sa_func.count())
            .group_by(EnhancementSignalModel.type)
        )
        by_type = dict(type_result.all())

        # By severity
        sev_result = await session.execute(
            select(EnhancementSignalModel.severity, sa_func.count())
            .group_by(EnhancementSignalModel.severity)
        )
        by_severity = dict(sev_result.all())

    return EnhancementStats(
        total_signals=total,
        pending=by_status.get("pending", 0),
        converted_to_tasks=by_status.get("converted", 0),
        dismissed=by_status.get("dismissed", 0),
        by_type=by_type,
        by_severity=by_severity
    )


@router.post("/signals/{signal_id}/convert")
async def convert_signal_to_task(signal_id: str, request: SignalToTaskRequest):
    """Convert an enhancement signal to a sprint task."""
    async with get_session() as session:
        signal = await session.get(EnhancementSignalModel, signal_id)
        if not signal:
            raise HTTPException(status_code=404, detail="Signal not found")

        if signal.status == "converted":
            raise HTTPException(status_code=400, detail="Signal already converted to task")

        # Map severity to priority
        severity_to_priority = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW
        }

        # Map signal type to category
        type_to_category = {
            "todo": TaskCategory.CHORE,
            "fixme": TaskCategory.BUG,
            "error": TaskCategory.BUG,
            "performance": TaskCategory.ENHANCEMENT,
            "qa_issue": TaskCategory.BUG
        }

        # Create task
        task_service = get_task_service()

        title = request.title or signal.message[:100]
        priority = request.priority or severity_to_priority.get(signal.severity, TaskPriority.MEDIUM)
        category = type_to_category.get(signal.type, TaskCategory.ENHANCEMENT)

        task_data = TaskCreate(
            title=title,
            description=f"Source: {signal.source_file or 'unknown'}:{signal.line_number or '?'}\n\n{signal.message}",
            sprint_id=request.sprint_id,
            category=category,
            priority=priority,
            points=request.points,
            source=TaskSource.ENHANCEMENT_ENGINE,
            source_reference=signal_id
        )

        task = await task_service.create_task(task_data)

        # Update signal status
        signal.status = "converted"
        signal.converted_to_task = task.id
        signal.converted_at = datetime.now(timezone.utc)

    logger.info("Signal converted to task", signal_id=signal_id, task_id=task.id)

    return {
        "status": "converted",
        "signal_id": signal_id,
        "task": task.model_dump()
    }


@router.post("/signals/{signal_id}/dismiss")
async def dismiss_signal(signal_id: str, reason: Optional[str] = None):
    """Dismiss an enhancement signal."""
    async with get_session() as session:
        signal = await session.get(EnhancementSignalModel, signal_id)
        if not signal:
            raise HTTPException(status_code=404, detail="Signal not found")

        signal.status = "dismissed"
        if reason:
            # Store dismiss reason in context field (reusing available column)
            signal.context = f"Dismissed: {reason}"

    logger.info("Signal dismissed", signal_id=signal_id)
    return {"status": "dismissed", "signal_id": signal_id}


@router.post("/scan")
async def trigger_scan():
    """Trigger a scan for new enhancement signals."""
    from app.services.enhancement_service import get_enhancement_service

    logger.info("Enhancement scan triggered")
    svc = get_enhancement_service()
    result = await svc.scan_all_projects()

    return {
        "status": "completed",
        "message": "Enhancement scan complete",
        **result,
    }


# ============================================
# DAILY IMPROVEMENT ENDPOINTS
# ============================================

@router.get("/improvement/metrics")
async def get_improvement_metrics():
    """Get daily improvement metrics and trends."""
    from app.services.daily_improvement_service import get_daily_improvement_service

    svc = get_daily_improvement_service()
    return await svc.get_metrics()


@router.get("/improvement/plan")
async def get_improvement_plan():
    """Get today's daily improvement plan."""
    from app.services.daily_improvement_service import get_daily_improvement_service

    svc = get_daily_improvement_service()
    return await svc.get_todays_plan()


@router.post("/improvement/run-cycle")
async def trigger_improvement_cycle():
    """
    Manually trigger the full daily improvement cycle:
    plan -> execute -> verify.
    """
    from app.services.daily_improvement_service import get_daily_improvement_service

    logger.info("Manual improvement cycle triggered")
    svc = get_daily_improvement_service()

    # Phase 1: Plan
    plan_result = await svc.create_daily_plan()
    if plan_result.get("status") == "empty":
        return {"status": "empty", "reason": plan_result.get("summary")}

    # Phase 2: Execute
    exec_result = await svc.execute_daily_plan()

    # Phase 3: Verify
    verify_result = await svc.verify_daily_plan()

    return {
        "status": "completed",
        "plan": plan_result.get("summary"),
        "execution": {
            "auto_fixes": exec_result.get("auto_fixes_applied", 0),
            "total": exec_result.get("total_improvements", 0),
        },
        "verification": verify_result,
    }
