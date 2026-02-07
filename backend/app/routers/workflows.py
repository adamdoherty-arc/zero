"""
Workflow Management API Endpoints.
Sprint 42 Task 77: List, status, trigger, and cancel workflows via REST API.
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.services.workflow_engine import get_workflow_engine

router = APIRouter()


class TriggerRequest(BaseModel):
    trigger: Optional[Dict[str, Any]] = None
    variables: Optional[Dict[str, Any]] = None


@router.get("/")
async def list_workflows():
    """List all available workflow definitions."""
    engine = get_workflow_engine()
    return {
        "workflows": engine.list_workflows(),
        "total": len(engine.list_workflows()),
    }


@router.get("/{workflow_name}")
async def get_workflow(workflow_name: str):
    """Get details of a specific workflow."""
    engine = get_workflow_engine()
    wf = engine.get_workflow(workflow_name)
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found")
    return {
        "name": wf.name,
        "version": wf.version,
        "description": wf.description,
        "steps": [
            {
                "id": s["id"],
                "name": s.get("name", s["id"]),
                "type": s["type"],
                "depends_on": s.get("depends_on", []),
                "timeout": s.get("timeout"),
                "on_error": s.get("on_error", "fail"),
            }
            for s in wf.steps
        ],
        "triggers": wf.triggers,
        "variables": wf.variables,
        "topological_order": wf.topological_order(),
        "source": wf.source_path,
    }


@router.post("/{workflow_name}/trigger")
async def trigger_workflow(
    workflow_name: str,
    request: TriggerRequest,
    background_tasks: BackgroundTasks,
):
    """Trigger a workflow execution."""
    engine = get_workflow_engine()
    wf = engine.get_workflow(workflow_name)
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found")

    result = await engine.trigger_workflow(
        workflow_name,
        trigger=request.trigger,
        variables=request.variables,
    )
    return result


@router.get("/executions/active")
async def get_active_executions():
    """Get all active (running) workflow executions."""
    engine = get_workflow_engine()
    return {"executions": engine.get_active_executions()}


@router.get("/executions/history")
async def get_execution_history(limit: int = 20):
    """Get recent execution history."""
    engine = get_workflow_engine()
    return {"history": engine.get_history(limit=limit)}


@router.get("/executions/{execution_id}/status")
async def get_execution_status(execution_id: str):
    """Get status of a specific execution."""
    engine = get_workflow_engine()
    state = engine.get_execution_status(execution_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    return state


@router.post("/executions/{execution_id}/resume")
async def resume_execution(execution_id: str):
    """Resume a crashed/interrupted execution."""
    engine = get_workflow_engine()
    result = await engine.resume(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found or no workflow to resume")
    return result


@router.delete("/executions/{execution_id}")
async def cancel_execution(execution_id: str):
    """Cancel an active execution."""
    engine = get_workflow_engine()
    success = engine.cancel(execution_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    return {"message": f"Execution '{execution_id}' cancelled"}
