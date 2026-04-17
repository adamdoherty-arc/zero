"""Visual workflow builder endpoints."""
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import structlog

router = APIRouter()
logger = structlog.get_logger()


class WorkflowCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    nodes: list = []
    edges: list = []
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict] = None


class WorkflowUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[list] = None
    edges: Optional[list] = None
    status: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict] = None


@router.get("/node-types")
async def get_node_types():
    from app.services.visual_workflow_service import get_visual_workflow_service
    return get_visual_workflow_service().get_node_types()


@router.get("")
async def list_workflows(status: Optional[str] = None):
    from app.services.visual_workflow_service import get_visual_workflow_service
    return await get_visual_workflow_service().list_workflows(status=status)


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    from app.services.visual_workflow_service import get_visual_workflow_service
    wf = await get_visual_workflow_service().get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return wf


@router.post("")
async def create_workflow(req: WorkflowCreateRequest):
    from app.services.visual_workflow_service import get_visual_workflow_service
    return await get_visual_workflow_service().create_workflow(req.model_dump())


@router.patch("/{workflow_id}")
async def update_workflow(workflow_id: str, req: WorkflowUpdateRequest):
    from app.services.visual_workflow_service import get_visual_workflow_service
    data = {k: v for k, v in req.model_dump().items() if v is not None}
    result = await get_visual_workflow_service().update_workflow(workflow_id, data)
    if not result:
        raise HTTPException(404, "Workflow not found")
    return result


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    from app.services.visual_workflow_service import get_visual_workflow_service
    deleted = await get_visual_workflow_service().delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(404, "Workflow not found")
    return {"deleted": True}


@router.post("/{workflow_id}/execute")
async def execute_workflow(workflow_id: str):
    from app.services.visual_workflow_service import get_visual_workflow_service
    return await get_visual_workflow_service().execute_workflow(workflow_id)


@router.get("/{workflow_id}/executions")
async def list_executions(workflow_id: str, limit: int = Query(default=20, le=100)):
    from app.services.visual_workflow_service import get_visual_workflow_service
    return await get_visual_workflow_service().list_executions(workflow_id, limit=limit)


# Outcome tracking endpoints
@router.get("/outcomes/dashboard")
async def outcome_dashboard(days: int = Query(default=30, le=365)):
    from app.services.self_healing_service import get_self_healing_service
    return await get_self_healing_service().get_outcome_dashboard(days=days)


@router.post("/outcomes/record")
async def record_outcome(body: Dict[str, Any]):
    from app.services.self_healing_service import get_self_healing_service
    outcome_id = await get_self_healing_service().record_outcome(
        action_source=body.get("action_source", "manual"),
        kpi_type=body.get("kpi_type", "custom"),
        kpi_value=body.get("kpi_value", 0),
        kpi_unit=body.get("kpi_unit", "count"),
        action_id=body.get("action_id"),
        metadata=body.get("metadata"),
    )
    return {"id": outcome_id}
