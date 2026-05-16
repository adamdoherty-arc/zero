"""Company work-item API.

This is the task-management surface for ADA AI LLC Company OS. It is
separate from `/api/company/tasks`, which is already used for agent-task records.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.models.company_facts import CompletionOutput
from app.models.task import TaskCreate, TaskUpdate
from app.services.company_completion_review_service import get_company_completion_review_service
from app.services.company_dashboard_review_service import get_company_dashboard_review_service
from app.services.company_progress_checkin_service import get_company_progress_checkin_service
from app.services.company_setup_progress_service import get_company_setup_progress_service
from app.services.company_walkthroughs import walkthrough_for
from app.services.company_work_item_service import get_company_work_item_service


router = APIRouter(
    prefix="/api/company/work-items",
    tags=["company-work-items"],
    dependencies=[Depends(require_auth)],
)


class ActorRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)


class CompletionReviewRequest(BaseModel):
    actor: str = Field(default="dashboard", max_length=100)
    auto_create_followups: bool = True


class CompleteWorkItemRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)
    completion_note: Optional[str] = None
    outputs: list[CompletionOutput] = Field(default_factory=list)


class TaskNoteRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)
    note: str = Field(..., min_length=1, max_length=4000)


@router.get("")
async def list_work_items(
    status: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
    owner_agent: Optional[str] = Query(default=None),
    risk_level: Optional[str] = Query(default=None),
    approval_state: Optional[str] = Query(default=None),
    filter_name: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=300, ge=1, le=1000),
):
    return await get_company_work_item_service().list_work_items(
        status=status,
        domain=domain,
        owner_agent=owner_agent,
        risk_level=risk_level,
        approval_state=approval_state,
        filter_name=filter_name,
        search=search,
        limit=limit,
    )


@router.get("/seed-status")
async def seed_status():
    return await get_company_work_item_service().seed_status()


@router.get("/setup-progress")
async def setup_progress():
    return await get_company_setup_progress_service().progress()


@router.get("/progress-checkin")
async def progress_checkin():
    return await get_company_progress_checkin_service().run_checkin(requested_by="dashboard")


@router.post("/progress-checkin/run")
async def run_progress_checkin(req: ActorRequest | None = None):
    actor = req.actor if req else "dashboard"
    return await get_company_progress_checkin_service().run_checkin(requested_by=actor)


@router.get("/reviews/summary")
async def review_summary():
    return await get_company_dashboard_review_service().summary()


@router.get("/reviews")
async def list_reviews(limit: int = Query(default=500, ge=1, le=1000)):
    return await get_company_dashboard_review_service().list_reviews(limit=limit)


@router.post("/reviews/run")
async def run_dashboard_review(req: ActorRequest | None = None):
    return await get_company_dashboard_review_service().run_dashboard_review(
        reviewed_by=(req.actor if req else "dashboard"),
        auto_apply=True,
    )


@router.post("/import-seed")
async def import_seed(req: ActorRequest | None = None):
    return await get_company_work_item_service().import_seed_backlog(actor=(req.actor if req else "user"))


@router.get("/{task_id}")
async def get_work_item(task_id: str):
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.get("/{task_id}/events")
async def events(task_id: str, limit: int = Query(default=100, ge=1, le=500)):
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return await get_company_work_item_service().events(task_id, limit=limit)


@router.get("/{task_id}/review")
async def review(task_id: str):
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    item = await get_company_dashboard_review_service().get_review(task_id)
    if not item:
        # Build a minimal review on the fly so the walkthrough is still surfaced
        walkthrough = walkthrough_for(task.title, task.description or "")
        if walkthrough is None:
            raise HTTPException(404, f"Company work item review {task_id} not found")
        return {
            "id": f"adhoc-{task.id}",
            "task_id": task.id,
            "score": 0,
            "recommendation": "keep",
            "summary": None,
            "missing_info": [],
            "action_steps": [],
            "acceptance_criteria": [],
            "automation_plan": {},
            "source_links": [],
            "walkthrough": walkthrough,
            "completion_review": None,
            "reviewed_by": "walkthrough-only",
            "operator_run_id": None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": None,
        }
    return item


@router.get("/{task_id}/walkthrough")
async def get_walkthrough(task_id: str):
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    walkthrough = walkthrough_for(task.title, task.description or "")
    if walkthrough is None:
        raise HTTPException(404, f"No curated walkthrough for task {task_id}")
    return walkthrough


@router.post("/{task_id}/completion-review")
async def run_completion_review(task_id: str, req: CompletionReviewRequest | None = None):
    request = req or CompletionReviewRequest()
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return await get_company_completion_review_service().review_completion(
        task_id,
        actor=request.actor,
        auto_create_followups=request.auto_create_followups,
    )


@router.post("")
async def create_work_item(task: TaskCreate):
    return await get_company_work_item_service().create_work_item(task, actor="user")


@router.patch("/{task_id}")
async def update_work_item(task_id: str, updates: TaskUpdate):
    task = await get_company_work_item_service().update_work_item(task_id, updates, actor="user")
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.post("/{task_id}/complete")
async def complete_work_item(task_id: str, req: CompleteWorkItemRequest | None = None):
    request = req or CompleteWorkItemRequest()
    task = await get_company_work_item_service().complete_work_item(
        task_id,
        actor=request.actor,
        completion_note=request.completion_note,
        outputs=[output.model_dump() for output in request.outputs],
    )
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.delete("/{task_id}/notes/{event_id}")
async def delete_company_note(task_id: str, event_id: str):
    """Remove a note. Only event_type='note' rows are deletable — audit
    history (created/updated/blocked/approval_queued/etc.) is untouchable."""
    from app.db.models import CompanyTaskEventModel
    from app.infrastructure.database import get_session
    async with get_session() as session:
        row = await session.get(CompanyTaskEventModel, event_id)
        if not row or row.task_id != task_id or row.event_type != "note":
            raise HTTPException(404, "Note not found (or not a note)")
        await session.delete(row)
        await session.flush()
    return {"status": "deleted", "event_id": event_id}


@router.post("/{task_id}/notes")
async def add_note(task_id: str, req: TaskNoteRequest):
    """Append a free-text note. Same notes panel feeds personal + company boards.
    Stored as a company_task_events row with event_type='note'."""
    service = get_company_work_item_service()
    existing = await service.get_work_item(task_id)
    if not existing:
        raise HTTPException(404, f"Company work item {task_id} not found")
    event = await service.record_event(
        task_id, "note", actor=req.actor, summary=req.note.strip(),
    )
    return event


@router.post("/{task_id}/reopen")
async def reopen_work_item(task_id: str, req: ActorRequest | None = None):
    task = await get_company_work_item_service().reopen_work_item(task_id, actor=(req.actor if req else "user"))
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.post("/{task_id}/duplicate")
async def duplicate_work_item(task_id: str, req: ActorRequest | None = None):
    task = await get_company_work_item_service().duplicate_work_item(task_id, actor=(req.actor if req else "user"))
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.delete("/{task_id}")
async def delete_work_item(task_id: str):
    deleted = await get_company_work_item_service().delete_work_item(task_id, actor="user")
    if not deleted:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return {"status": "deleted", "task_id": task_id}
