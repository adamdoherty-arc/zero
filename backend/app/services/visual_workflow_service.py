"""Visual workflow service — CRUD, compilation, and execution of visual workflows."""
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Any, List, Optional
from uuid import uuid4

from sqlalchemy import select, desc, func
import structlog

from app.db.models import VisualWorkflowDefinitionModel, VisualWorkflowExecutionModel
from app.infrastructure.database import get_session

logger = structlog.get_logger()


def _ulid() -> str:
    ts = int(time.time() * 1000)
    return f"{ts:013x}-{uuid4().hex[:12]}"


# Available node types for the visual builder
NODE_TYPES = [
    {"type": "llm_call", "label": "LLM Call", "color": "#8b5cf6", "inputs": ["prompt"], "outputs": ["response"]},
    {"type": "api_request", "label": "API Request", "color": "#3b82f6", "inputs": ["url", "method"], "outputs": ["data"]},
    {"type": "conditional", "label": "Condition", "color": "#f59e0b", "inputs": ["expression"], "outputs": ["true", "false"]},
    {"type": "human_approval", "label": "Human Approval", "color": "#ef4444", "inputs": ["context"], "outputs": ["approved", "rejected"]},
    {"type": "data_transform", "label": "Data Transform", "color": "#10b981", "inputs": ["data", "template"], "outputs": ["result"]},
    {"type": "timer", "label": "Timer", "color": "#6b7280", "inputs": ["duration"], "outputs": ["done"]},
    {"type": "route", "label": "Route to Agent", "color": "#ec4899", "inputs": ["message", "route"], "outputs": ["response"]},
]


class VisualWorkflowService:
    def get_node_types(self) -> List[Dict[str, Any]]:
        return NODE_TYPES

    async def list_workflows(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        async with get_session() as session:
            stmt = select(VisualWorkflowDefinitionModel)
            if status:
                stmt = stmt.where(VisualWorkflowDefinitionModel.status == status)
            stmt = stmt.order_by(desc(VisualWorkflowDefinitionModel.updated_at))
            rows = (await session.execute(stmt)).scalars().all()
            return [self._def_to_dict(r) for r in rows]

    async def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        async with get_session() as session:
            row = (await session.execute(
                select(VisualWorkflowDefinitionModel).where(VisualWorkflowDefinitionModel.id == workflow_id)
            )).scalar_one_or_none()
            return self._def_to_dict(row) if row else None

    async def create_workflow(self, data: Dict[str, Any]) -> Dict[str, Any]:
        wf_id = _ulid()
        async with get_session() as session:
            row = VisualWorkflowDefinitionModel(
                id=wf_id,
                name=data["name"],
                description=data.get("description"),
                nodes=data.get("nodes", []),
                edges=data.get("edges", []),
                trigger_type=data.get("trigger_type"),
                trigger_config=data.get("trigger_config"),
            )
            session.add(row)
        return await self.get_workflow(wf_id)

    async def update_workflow(self, workflow_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with get_session() as session:
            row = (await session.execute(
                select(VisualWorkflowDefinitionModel).where(VisualWorkflowDefinitionModel.id == workflow_id)
            )).scalar_one_or_none()
            if not row:
                return None
            for key in ["name", "description", "nodes", "edges", "status", "trigger_type", "trigger_config"]:
                if key in data:
                    setattr(row, key, data[key])
            if "nodes" in data or "edges" in data:
                row.version = (row.version or 1) + 1
        return await self.get_workflow(workflow_id)

    async def delete_workflow(self, workflow_id: str) -> bool:
        async with get_session() as session:
            row = (await session.execute(
                select(VisualWorkflowDefinitionModel).where(VisualWorkflowDefinitionModel.id == workflow_id)
            )).scalar_one_or_none()
            if row:
                await session.delete(row)
                return True
            return False

    async def execute_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Execute a workflow by walking its node graph."""
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return {"error": "Workflow not found"}
        if workflow["status"] != "active":
            return {"error": "Workflow must be active to execute"}

        exec_id = _ulid()
        async with get_session() as session:
            row = VisualWorkflowExecutionModel(
                id=exec_id,
                workflow_id=workflow_id,
                status="running",
                execution_log=[],
            )
            session.add(row)

        # Execute nodes in order (simplified linear execution)
        nodes = workflow.get("nodes", [])
        log_entries = []
        current_output = {}

        for i, node in enumerate(nodes):
            node_type = node.get("type", "unknown")
            node_id = node.get("id", str(i))
            entry = {
                "node_id": node_id,
                "node_type": node_type,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "completed",
            }

            try:
                if node_type == "llm_call":
                    from app.infrastructure.langchain_adapter import get_zero_chat_model
                    llm = get_zero_chat_model()
                    prompt = node.get("data", {}).get("prompt", "Hello")
                    resp = await llm.ainvoke(prompt)
                    current_output = {"response": resp.content if hasattr(resp, "content") else str(resp)}
                elif node_type == "api_request":
                    import httpx
                    url = node.get("data", {}).get("url", "")
                    method = node.get("data", {}).get("method", "GET")
                    async with httpx.AsyncClient(timeout=30) as client:
                        resp = await client.request(method, url)
                        current_output = {"status": resp.status_code, "data": resp.text[:2000]}
                elif node_type == "conditional":
                    # Simple pass-through
                    current_output = {"branch": "true"}
                elif node_type == "data_transform":
                    current_output = {"result": current_output}
                elif node_type == "timer":
                    import asyncio
                    duration = min(node.get("data", {}).get("duration", 1), 10)
                    await asyncio.sleep(duration)
                    current_output = {"waited": duration}
                else:
                    current_output = {"passthrough": True}

                entry["output"] = current_output
            except Exception as e:
                entry["status"] = "failed"
                entry["error"] = str(e)

            entry["completed_at"] = datetime.now(timezone.utc).isoformat()
            log_entries.append(entry)

            # Update execution record
            async with get_session() as session:
                exec_row = (await session.execute(
                    select(VisualWorkflowExecutionModel).where(VisualWorkflowExecutionModel.id == exec_id)
                )).scalar_one_or_none()
                if exec_row:
                    exec_row.current_node_id = node_id
                    exec_row.execution_log = log_entries

        # Mark complete
        final_status = "completed" if all(e["status"] == "completed" for e in log_entries) else "failed"
        async with get_session() as session:
            exec_row = (await session.execute(
                select(VisualWorkflowExecutionModel).where(VisualWorkflowExecutionModel.id == exec_id)
            )).scalar_one_or_none()
            if exec_row:
                exec_row.status = final_status
                exec_row.output = current_output
                exec_row.completed_at = datetime.now(timezone.utc)
                exec_row.execution_log = log_entries

        return {"execution_id": exec_id, "status": final_status, "log": log_entries, "output": current_output}

    async def list_executions(self, workflow_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        async with get_session() as session:
            stmt = (
                select(VisualWorkflowExecutionModel)
                .where(VisualWorkflowExecutionModel.workflow_id == workflow_id)
                .order_by(desc(VisualWorkflowExecutionModel.started_at))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._exec_to_dict(r) for r in rows]

    def _def_to_dict(self, row) -> Dict[str, Any]:
        return {
            "id": row.id, "name": row.name, "description": row.description,
            "nodes": row.nodes or [], "edges": row.edges or [],
            "version": row.version, "status": row.status,
            "trigger_type": row.trigger_type, "trigger_config": row.trigger_config,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _exec_to_dict(self, row) -> Dict[str, Any]:
        return {
            "id": row.id, "workflow_id": row.workflow_id, "status": row.status,
            "current_node_id": row.current_node_id,
            "execution_log": row.execution_log or [], "output": row.output,
            "error": row.error,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }


@lru_cache()
def get_visual_workflow_service() -> VisualWorkflowService:
    return VisualWorkflowService()
