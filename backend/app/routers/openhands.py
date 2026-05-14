"""
OpenHands runtime API + microagents API.

  GET  /api/openhands/status                — SDK available? task count?
  POST /api/openhands/tasks                 — dispatch a task
  GET  /api/openhands/tasks                 — list tasks
  GET  /api/openhands/tasks/{id}            — single task
  POST /api/openhands/tasks/{id}/cancel     — cancel a queued/running task

  GET  /api/microagents                     — list every loaded microagent
  POST /api/microagents/match               — return matches for given text
  POST /api/microagents/compose             — render an injectable context
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.microagents_service import get_microagents_service
from app.services.openhands_runtime_service import get_openhands_runtime_service
from app.services.side_effect_gate import queue_side_effect_approval

router = APIRouter()


# ----- OpenHands runtime -----

class DispatchRequest(BaseModel):
    instruction: str
    workspace: str = "local"  # "local" | "docker"
    model: Optional[str] = None
    repo_dir: Optional[str] = None


@router.get("/openhands/status")
async def openhands_status():
    svc = get_openhands_runtime_service()
    return {
        "available": svc.is_available(),
        "task_count": len(svc.list_tasks(limit=999)),
    }


@router.post("/openhands/tasks")
async def openhands_dispatch(req: DispatchRequest):
    svc = get_openhands_runtime_service()
    if not svc.is_available():
        return {
            "status": "unavailable",
            "error": "OpenHands is disabled. Use Legion delegation until a real runtime is approved.",
        }
    return await queue_side_effect_approval(
        tool_name="openhands.dispatch",
        tier="write_external",
        summary="Dispatch code work to OpenHands runtime",
        arguments=req.model_dump(),
    )


@router.get("/openhands/tasks")
async def openhands_list(limit: int = 50):
    return {"tasks": get_openhands_runtime_service().list_tasks(limit=limit)}


@router.get("/openhands/tasks/{task_id}")
async def openhands_get(task_id: str):
    svc = get_openhands_runtime_service()
    t = svc.get(task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="task not found")
    return t


@router.post("/openhands/tasks/{task_id}/cancel")
async def openhands_cancel(task_id: str):
    svc = get_openhands_runtime_service()
    try:
        return await svc.cancel(task_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="task not found") from e


# ----- Microagents -----

class MatchRequest(BaseModel):
    text: str
    agent_persona: str = "any"


class ComposeRequest(BaseModel):
    text: str
    agent_persona: str = "any"
    max_chars: int = 4000


@router.get("/microagents")
async def microagents_list():
    return {"microagents": get_microagents_service().list_all()}


@router.post("/microagents/match")
async def microagents_match(req: MatchRequest):
    svc = get_microagents_service()
    matches = svc.match(req.text, agent_persona=req.agent_persona)
    return {
        "matches": [
            {"name": m.name, "type": m.type, "path": m.path, "body": m.body}
            for m in matches
        ]
    }


@router.post("/microagents/compose")
async def microagents_compose(req: ComposeRequest):
    svc = get_microagents_service()
    body = svc.compose_context_for(
        req.text, agent_persona=req.agent_persona, max_chars=req.max_chars
    )
    return {"context": body, "length": len(body)}
