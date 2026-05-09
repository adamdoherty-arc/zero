"""
AI Company Router.
REST API for agent roles, tasks, and company operations.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.infrastructure.auth import require_auth
from app.models.agent_company import (
    AgentRole, AgentTask, AgentTaskCreate, AiCompanyStats,
)
from app.services.agent_company_service import get_agent_company_service
from app.services.company_context_service import get_company_context_service

router = APIRouter(prefix="/api/company", tags=["ai-company"], dependencies=[Depends(require_auth)])


# ------------------------------------------------------------------
# Roles
# ------------------------------------------------------------------

@router.get("/roles", response_model=list[AgentRole])
async def list_roles():
    svc = get_agent_company_service()
    return await svc.list_roles()


@router.get("/roles/{role_id}", response_model=AgentRole)
async def get_role(role_id: str):
    svc = get_agent_company_service()
    role = await svc.get_role(role_id)
    if not role:
        raise HTTPException(404, f"Role {role_id} not found")
    return role


# ------------------------------------------------------------------
# Tasks
# ------------------------------------------------------------------

@router.get("/tasks", response_model=list[AgentTask])
async def list_tasks(
    status: Optional[str] = None,
    role: Optional[str] = None,
    task_type: Optional[str] = None,
    limit: int = 50,
):
    svc = get_agent_company_service()
    return await svc.list_tasks(status=status, role=role, task_type=task_type, limit=limit)


@router.get("/tasks/{task_id}", response_model=AgentTask)
async def get_task(task_id: str):
    svc = get_agent_company_service()
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task {task_id} not found")
    return task


@router.post("/tasks", response_model=AgentTask, status_code=201)
async def create_task(req: AgentTaskCreate):
    svc = get_agent_company_service()
    return await svc.create_task(req)


@router.post("/tasks/{task_id}/execute", response_model=AgentTask)
async def execute_task(task_id: str):
    svc = get_agent_company_service()
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task {task_id} not found")
    return await svc.execute_task(task_id)


# ------------------------------------------------------------------
# CEO Operations
# ------------------------------------------------------------------

@router.post("/plan")
async def ceo_plan(description: str, context: Optional[dict] = None):
    """CEO decomposes a complex task and delegates subtasks."""
    svc = get_agent_company_service()
    result = await svc.ceo_plan_and_delegate(description, context)
    return result


@router.post("/tasks/{parent_id}/execute-subtasks")
async def execute_subtasks(parent_id: str):
    """Execute all pending subtasks for a parent task."""
    svc = get_agent_company_service()
    results = await svc.execute_subtasks(parent_id)
    return {"executed": len(results), "tasks": results}


# ------------------------------------------------------------------
# Stats
# ------------------------------------------------------------------

@router.get("/stats", response_model=AiCompanyStats)
async def get_stats():
    svc = get_agent_company_service()
    return await svc.get_stats()


# ------------------------------------------------------------------
# Company OS Docs / Context
# ------------------------------------------------------------------

@router.get("/docs-index")
async def docs_index():
    """List migrated Company OS docs now canonical inside Zero."""
    svc = get_company_context_service()
    return svc.list_docs()


@router.get("/operating-context")
async def operating_context():
    """Return retrieval-friendly context for Zero company reports."""
    svc = get_company_context_service()
    return svc.operating_context()
