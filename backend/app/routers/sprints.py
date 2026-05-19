"""
Sprint management API endpoints.
Proxies to Legion sprint manager.

Sprint-Tracking policy (2026-05-17): Every Zero feature/enhancement is a
Legion sprint with a 5-field retrospective gated at POST /{id}/complete.
See `C:\\code\\zero\\CLAUDE.md` SPRINT TRACKING section.
"""

from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.config import get_settings
from app.models.sprint import Sprint
from app.services import sprint_vault_renderer
from app.services.legion_client import get_legion_client
from app.services.sprint_service import get_sprint_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================
# RETROSPECTIVE GATE
# ============================================

REQUIRED_RETRO_FIELDS = ("goal", "work_completed", "testing", "improvements_found", "deferred")
_VALID_REGRESSION_STATUS = {"pass", "fail", "warning", "not_tested"}


class SprintRetrospective(BaseModel):
    """5-field retrospective required at sprint completion."""
    goal: str = Field(..., min_length=1)
    work_completed: List[dict] = Field(default_factory=list)
    testing: dict = Field(default_factory=dict)
    improvements_found: List[dict] = Field(default_factory=list)
    deferred: List[dict] = Field(default_factory=list)


def _validate_retro(retro: Optional[dict]) -> List[str]:
    """Return a list of missing/malformed retro field names. [] = valid."""
    if not isinstance(retro, dict):
        return list(REQUIRED_RETRO_FIELDS)
    missing: List[str] = []
    for f in REQUIRED_RETRO_FIELDS:
        v = retro.get(f)
        if v is None:
            missing.append(f)
            continue
        if f == "goal":
            if not (isinstance(v, str) and v.strip()):
                missing.append(f)
        elif f == "testing":
            if not isinstance(v, dict):
                missing.append(f)
                continue
            rs = v.get("regression_status")
            if not (isinstance(rs, str) and rs.strip() in _VALID_REGRESSION_STATUS):
                missing.append(f)
        elif f in ("work_completed", "improvements_found"):
            if not isinstance(v, list):
                missing.append(f)
        elif f == "deferred":
            if not isinstance(v, list):
                missing.append(f)
                continue
            for entry in v:
                if not isinstance(entry, dict) or not entry.get("item") or not entry.get("reason"):
                    missing.append(f)
                    break
    return missing


# ============================================
# REQUEST MODELS
# ============================================

class SprintCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    goal: Optional[str] = None
    description: Optional[str] = None
    planned_points: int = Field(default=0, ge=0)
    primary_hub_id: Optional[int] = None
    documentation_link: Optional[str] = None
    # S52 (2026-05-19): optional tasks; when present, the router takes the
    # atomic /api/sprints/with-tasks path so the sprint can never exist
    # with zero tasks (eliminates the S46 ACTIVE-with-no-tasks race).
    tasks: Optional[List["TaskCreateRequest"]] = None


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    prompt: Optional[str] = None
    category: Optional[str] = "feature"
    priority: int = Field(default=5, ge=1, le=10)
    story_points: int = Field(default=1, ge=1, le=21)
    assignee: Optional[str] = None
    files_affected: Optional[List[str]] = None
    acceptance_criteria: Optional[List[str]] = None
    labels: Optional[List[str]] = None
    estimated_hours: Optional[float] = None


class TaskMoveRequest(BaseModel):
    status: str
    notes: Optional[str] = None


class CompleteSprintRequest(BaseModel):
    retrospective: Optional[SprintRetrospective] = None
    force: bool = False


@router.get("")
async def list_sprints(
    project_id: Optional[int] = Query(None, description="Filter by Legion project ID"),
    status: Optional[str] = Query(None, description="Filter by status (planning, active, completed, paused)"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
):
    """Get all sprints from Legion."""
    service = get_sprint_service()
    return await service.list_sprints(project_id=project_id, status=status, limit=limit)


@router.get("/current")
async def get_current_sprint():
    """Get the currently active sprint for Zero."""
    service = get_sprint_service()
    return await service.get_current_sprint()


@router.get("/{sprint_id}")
async def get_sprint(sprint_id: str):
    """Get sprint by ID."""
    service = get_sprint_service()
    sprint = await service.get_sprint(sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


@router.get("/{sprint_id}/board")
async def get_sprint_board(sprint_id: str):
    """Get Kanban board data for a sprint."""
    service = get_sprint_service()
    board = await service.get_board(sprint_id)
    if not board:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return board


# ============================================
# LIFECYCLE WRITES (Sprint-Tracking policy)
# ============================================

@router.post("", status_code=201)
async def create_sprint(data: SprintCreateRequest):
    """Create a Zero sprint in Legion (Sprint-Tracking policy).

    S52 (2026-05-19): if ``data.tasks`` is non-empty, posts to Legion's
    atomic ``/api/sprints/with-tasks`` endpoint so the sprint can never
    exist in a zero-tasks state. Falls back to the legacy two-call path
    when ``tasks`` is omitted (preserves existing operator workflow).
    """
    settings = get_settings()
    client = get_legion_client()
    sprint_body: dict = {
        "name": data.name,
        "project_id": settings.zero_legion_project_id,
        "auto_execute": False,
        "source_system": "zero",
    }
    if data.goal:
        sprint_body["goal"] = data.goal
    if data.description:
        sprint_body["description"] = data.description
    if data.planned_points:
        sprint_body["planned_points"] = data.planned_points
    if data.primary_hub_id is not None:
        sprint_body["primary_hub_id"] = data.primary_hub_id
    if data.documentation_link:
        sprint_body["documentation_link"] = data.documentation_link

    try:
        if data.tasks:
            # Atomic path — sprint + tasks in one transaction.
            tasks_body: list[dict] = []
            for t in data.tasks:
                tb: dict = {
                    "title": t.title,
                    "priority": t.priority,
                    "story_points": t.story_points,
                    "prompt": t.prompt or t.description or t.title,
                }
                if t.description:
                    tb["description"] = t.description
                if t.category:
                    tb["category"] = t.category
                if t.assignee:
                    tb["assignee"] = t.assignee
                if t.files_affected is not None:
                    tb["files_affected"] = t.files_affected
                if t.acceptance_criteria is not None:
                    tb["acceptance_criteria"] = t.acceptance_criteria
                if t.labels is not None:
                    tb["labels"] = t.labels
                if t.estimated_hours is not None:
                    tb["estimated_hours"] = t.estimated_hours
                tasks_body.append(tb)
            legion_sprint = await client.create_sprint_with_tasks(
                {"sprint": sprint_body, "tasks": tasks_body}
            )
        else:
            legion_sprint = await client.create_sprint(sprint_body)
    except Exception as exc:  # noqa: BLE001
        logger.error("zero_sprint_create_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Legion unreachable: {exc}")
    if legion_sprint and legion_sprint.get("id"):
        sprint_vault_renderer.fire_render(int(legion_sprint["id"]))
    return legion_sprint


@router.post("/{sprint_id}/tasks", status_code=201)
async def create_task(sprint_id: int, data: TaskCreateRequest):
    """Add a task to a Zero sprint."""
    client = get_legion_client()
    body: dict = {
        "title": data.title,
        "priority": data.priority,
        "story_points": data.story_points,
        "source_system": "zero",
    }
    body["prompt"] = data.prompt or data.description or data.title
    if data.description:
        body["description"] = data.description
    if data.category:
        body["category"] = data.category
    if data.assignee:
        body["assignee"] = data.assignee
    if data.files_affected is not None:
        body["files_affected"] = data.files_affected
    if data.acceptance_criteria is not None:
        body["acceptance_criteria"] = data.acceptance_criteria
    if data.labels is not None:
        body["labels"] = data.labels
    if data.estimated_hours is not None:
        body["estimated_hours"] = data.estimated_hours
    try:
        legion_task = await client.create_task(sprint_id, body)
    except Exception as exc:  # noqa: BLE001
        logger.error("zero_task_create_failed", error=str(exc), sprint_id=sprint_id)
        raise HTTPException(status_code=502, detail=f"Legion unreachable: {exc}")
    sprint_vault_renderer.fire_render(sprint_id)
    return legion_task


@router.post("/tasks/{task_id}/move")
async def move_task(task_id: int, data: TaskMoveRequest):
    """Move a Zero task to a new status."""
    client = get_legion_client()
    try:
        legion_task = await client.move_task(task_id, status=data.status, notes=data.notes)
    except Exception as exc:  # noqa: BLE001
        logger.error("zero_task_move_failed", error=str(exc), task_id=task_id)
        raise HTTPException(status_code=502, detail=f"Legion unreachable: {exc}")
    if legion_task and legion_task.get("sprint_id"):
        sprint_vault_renderer.fire_render(int(legion_task["sprint_id"]))
    return legion_task


@router.post("/{sprint_id}/complete")
async def complete_sprint(sprint_id: int, body: Optional[CompleteSprintRequest] = None,
                          force: bool = Query(False, description="Bypass retro gate (audited)")):
    """Complete a Zero sprint, gating on the 5-field retrospective.

    Returns 422 with missing_fields[] if retro is incomplete unless force=true.
    The retro lands in Legion's `sprints.retrospective_data` JSONB column.
    """
    retro_dict = body.retrospective.model_dump() if body and body.retrospective else None
    missing = _validate_retro(retro_dict)
    if missing and not force:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "retrospective_incomplete",
                "missing_fields": missing,
                "required_fields": list(REQUIRED_RETRO_FIELDS),
                "hint": "POST body must include retrospective.{goal, work_completed, testing, improvements_found, deferred}",
            },
        )
    client = get_legion_client()
    try:
        # 1) PATCH retrospective_data, then 2) mark complete via status=completed
        if retro_dict:
            await client.update_sprint(sprint_id, {"retrospective_data": retro_dict})
        result = await client.update_sprint(sprint_id, {"status": "completed"})
    except Exception as exc:  # noqa: BLE001
        logger.error("zero_sprint_complete_failed", error=str(exc), sprint_id=sprint_id)
        raise HTTPException(status_code=502, detail=f"Legion unreachable: {exc}")
    sprint_vault_renderer.fire_render(sprint_id)
    return result
