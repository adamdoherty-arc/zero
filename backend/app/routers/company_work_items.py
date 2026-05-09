"""Company work-item API.

This is the task-management surface for ADA AI LLC Company OS. It is
separate from `/api/company/tasks`, which is already used for agent-task records.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.models.task import TaskCreate, TaskUpdate
from app.services.company_dashboard_review_service import get_company_dashboard_review_service
from app.services.company_work_item_service import get_company_work_item_service


router = APIRouter(
    prefix="/api/company/work-items",
    tags=["company-work-items"],
    dependencies=[Depends(require_auth)],
)


class ActorRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)


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
        raise HTTPException(404, f"Company work item review {task_id} not found")
    return item


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
async def complete_work_item(task_id: str, req: ActorRequest | None = None):
    task = await get_company_work_item_service().complete_work_item(task_id, actor=(req.actor if req else "user"))
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


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
