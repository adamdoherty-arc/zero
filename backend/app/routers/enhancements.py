"""
Enhancement system API endpoints.
Integrates with Zero's enhancement system to track and create sprint tasks.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel
import structlog

from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_enhancement_path
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
    storage = JsonStorage(get_enhancement_path())
    data = await storage.read("signals.json")

    signals = data.get("signals", [])

    # Apply filters
    filtered = []
    for s in signals:
        if status and s.get("status") != status:
            continue
        if type and s.get("type") != type:
            continue
        filtered.append(EnhancementSignal(**s))
        if len(filtered) >= limit:
            break

    return filtered


@router.get("/stats", response_model=EnhancementStats)
async def get_stats():
    """Get enhancement system statistics."""
    storage = JsonStorage(get_enhancement_path())
    data = await storage.read("signals.json")

    signals = data.get("signals", [])

    # Calculate stats
    by_type: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_status: Dict[str, int] = {"pending": 0, "converted": 0, "dismissed": 0}

    for s in signals:
        # By type
        signal_type = s.get("type", "unknown")
        by_type[signal_type] = by_type.get(signal_type, 0) + 1

        # By severity
        severity = s.get("severity", "medium")
        by_severity[severity] = by_severity.get(severity, 0) + 1

        # By status
        status = s.get("status", "pending")
        if status in by_status:
            by_status[status] += 1

    return EnhancementStats(
        total_signals=len(signals),
        pending=by_status["pending"],
        converted_to_tasks=by_status["converted"],
        dismissed=by_status["dismissed"],
        by_type=by_type,
        by_severity=by_severity
    )


@router.post("/signals/{signal_id}/convert")
async def convert_signal_to_task(signal_id: str, request: SignalToTaskRequest):
    """Convert an enhancement signal to a sprint task."""
    storage = JsonStorage(get_enhancement_path())
    data = await storage.read("signals.json")

    signals = data.get("signals", [])

    # Find the signal
    signal = None
    signal_idx = None
    for i, s in enumerate(signals):
        if s.get("id") == signal_id:
            signal = s
            signal_idx = i
            break

    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    if signal.get("status") == "converted":
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

    title = request.title or signal.get("message", "Enhancement task")[:100]
    priority = request.priority or severity_to_priority.get(signal.get("severity", "medium"), TaskPriority.MEDIUM)
    category = type_to_category.get(signal.get("type", "todo"), TaskCategory.ENHANCEMENT)

    task_data = TaskCreate(
        title=title,
        description=f"Source: {signal.get('source_file', 'unknown')}:{signal.get('line_number', '?')}\n\n{signal.get('message', '')}",
        sprint_id=request.sprint_id,
        category=category,
        priority=priority,
        points=request.points,
        source=TaskSource.ENHANCEMENT_ENGINE,
        source_reference=signal_id
    )

    task = await task_service.create_task(task_data)

    # Update signal status
    signals[signal_idx]["status"] = "converted"
    signals[signal_idx]["converted_to_task"] = task.id
    signals[signal_idx]["converted_at"] = datetime.utcnow().isoformat()
    data["signals"] = signals
    await storage.write("signals.json", data)

    logger.info("Signal converted to task", signal_id=signal_id, task_id=task.id)

    return {
        "status": "converted",
        "signal_id": signal_id,
        "task": task.model_dump()
    }


@router.post("/signals/{signal_id}/dismiss")
async def dismiss_signal(signal_id: str, reason: Optional[str] = None):
    """Dismiss an enhancement signal."""
    storage = JsonStorage(get_enhancement_path())
    data = await storage.read("signals.json")

    signals = data.get("signals", [])

    for i, s in enumerate(signals):
        if s.get("id") == signal_id:
            signals[i]["status"] = "dismissed"
            signals[i]["dismissed_at"] = datetime.utcnow().isoformat()
            if reason:
                signals[i]["dismiss_reason"] = reason
            data["signals"] = signals
            await storage.write("signals.json", data)

            logger.info("Signal dismissed", signal_id=signal_id)
            return {"status": "dismissed", "signal_id": signal_id}

    raise HTTPException(status_code=404, detail="Signal not found")


@router.post("/scan")
async def trigger_scan():
    """Trigger a scan for new enhancement signals."""
    # This would integrate with Zero's enhancement system to:
    # 1. Scan codebase for TODO/FIXME comments
    # 2. Parse error logs for patterns
    # 3. Check for performance issues
    # 4. Run static analysis

    logger.info("Enhancement scan triggered")

    return {
        "status": "scanning",
        "message": "Enhancement scan initiated",
        "scan_types": ["todo_comments", "error_logs", "performance_metrics"]
    }
