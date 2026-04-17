"""
Agent orchestrator API endpoints.
Provides control over code execution agents, LangGraph gateway,
conversation history, execution traces, and real-time activity feed.
"""

import asyncio
import json
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import structlog

from app.services.orchestrator_service import get_orchestrator, AgentTask, AgentType, TaskPriority
from app.services.enhancement_service import get_enhancement_service
from app.services.sprint_intelligence_service import get_sprint_intelligence_service

router = APIRouter()
logger = structlog.get_logger()


class AgentTrigger(BaseModel):
    """Schema for triggering agent actions."""
    action: str  # "execute_task", "scan_enhancements", "create_tasks", "generate_proposal"
    task_id: Optional[str] = None
    sprint_id: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


@router.get("/status")
async def get_status():
    """Get comprehensive orchestrator status."""
    orchestrator = get_orchestrator()
    return orchestrator.get_status()


@router.post("/start")
async def start_orchestrator():
    """Start the orchestrator and all agents."""
    orchestrator = get_orchestrator()
    result = await orchestrator.start()
    return result


@router.post("/stop")
async def stop_orchestrator():
    """Stop the orchestrator and all agents."""
    orchestrator = get_orchestrator()
    result = await orchestrator.stop()
    return result


@router.post("/trigger")
async def trigger_action(trigger: AgentTrigger):
    """Trigger a specific orchestrator action."""
    orchestrator = get_orchestrator()

    if not orchestrator.is_running:
        await orchestrator.start()

    logger.info("Action triggered", action=trigger.action)

    if trigger.action == "execute_task":
        if not trigger.task_id:
            raise HTTPException(status_code=400, detail="task_id required")

        task = AgentTask(
            agent_type=AgentType.CODE_EXECUTOR,
            priority=TaskPriority.HIGH,
            description=f"Execute sprint task {trigger.task_id}",
            payload={"task_id": trigger.task_id},
            sprint_task_id=trigger.task_id
        )
        task_id = orchestrator.queue_task(task)
        return {"status": "queued", "orchestrator_task_id": task_id}

    elif trigger.action == "scan_enhancements":
        task = AgentTask(
            agent_type=AgentType.ENHANCEMENT,
            priority=TaskPriority.MEDIUM,
            description="Scan codebase for enhancement signals",
            payload={"action": "scan"}
        )
        task_id = orchestrator.queue_task(task)
        return {"status": "queued", "orchestrator_task_id": task_id}

    elif trigger.action == "create_tasks":
        task = AgentTask(
            agent_type=AgentType.ENHANCEMENT,
            priority=TaskPriority.MEDIUM,
            description="Create tasks from pending signals",
            payload={"action": "create_tasks", "sprint_id": trigger.sprint_id}
        )
        task_id = orchestrator.queue_task(task)
        return {"status": "queued", "orchestrator_task_id": task_id}

    elif trigger.action == "generate_proposal":
        task = AgentTask(
            agent_type=AgentType.SPRINT_INTELLIGENCE,
            priority=TaskPriority.LOW,
            description="Generate sprint proposal",
            payload={"action": "generate_proposal", "sprint_id": trigger.sprint_id}
        )
        task_id = orchestrator.queue_task(task)
        return {"status": "queued", "orchestrator_task_id": task_id}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {trigger.action}")


@router.post("/trigger-enhancement")
async def trigger_enhancement_scan():
    """Trigger full enhancement cycle: scan + create tasks."""
    orchestrator = get_orchestrator()

    if not orchestrator.is_running:
        await orchestrator.start()

    enhancement_service = get_enhancement_service()
    scan_result = await enhancement_service.scan_for_signals()

    from app.services.sprint_service import get_sprint_service
    sprint_service = get_sprint_service()
    current_sprint = await sprint_service.get_current_sprint()

    sprint_id = current_sprint.id if current_sprint else None
    create_result = await enhancement_service.create_tasks_from_signals(sprint_id)

    logger.info("Enhancement cycle completed",
               signals_found=scan_result.get("signals_found", 0),
               tasks_created=create_result.get("tasks_created", 0))

    return {
        "status": "completed",
        "scan_result": scan_result,
        "task_creation": create_result,
        "sprint_id": sprint_id
    }


@router.post("/trigger-intelligence")
async def trigger_sprint_intelligence(sprint_id: Optional[str] = None):
    """Trigger sprint intelligence analysis: health check + proposal generation."""
    intelligence_service = get_sprint_intelligence_service()

    if not sprint_id:
        from app.services.sprint_service import get_sprint_service
        sprint_service = get_sprint_service()
        current_sprint = await sprint_service.get_current_sprint()
        sprint_id = current_sprint.id if current_sprint else None

    results = {"sprint_id": sprint_id}

    if sprint_id:
        health = await intelligence_service.get_sprint_health(sprint_id)
        results["health"] = health
        proposal = await intelligence_service.generate_sprint_proposal(sprint_id)
        results["proposal"] = proposal

    update_result = await intelligence_service.auto_update_sprints()
    results["sprint_updates"] = update_result
    return results


@router.post("/trigger-auto-update")
async def trigger_auto_update():
    """Trigger automatic sprint updates (recalculate points, sync state)."""
    intelligence_service = get_sprint_intelligence_service()
    result = await intelligence_service.auto_update_sprints()
    return result


@router.get("/health/{sprint_id}")
async def get_sprint_health(sprint_id: str):
    """Get health assessment for a specific sprint."""
    intelligence_service = get_sprint_intelligence_service()
    return await intelligence_service.get_sprint_health(sprint_id)


@router.post("/proposal/{sprint_id}")
async def generate_sprint_proposal(sprint_id: str):
    """Generate AI-powered sprint proposal."""
    intelligence_service = get_sprint_intelligence_service()
    return await intelligence_service.generate_sprint_proposal(sprint_id)


# =============================================================================
# LangGraph Orchestration Gateway
# =============================================================================

class OrchestrationRequest(BaseModel):
    """Request schema for LangGraph orchestration."""
    message: str
    thread_id: str = "default"
    channel: str = "api"


@router.post("/graph/invoke")
async def invoke_graph(request: OrchestrationRequest):
    """Invoke the LangGraph orchestration graph with a user message."""
    try:
        from app.services.orchestration_graph import invoke_orchestration
        result = await invoke_orchestration(
            message=request.message,
            thread_id=request.thread_id,
            channel=request.channel,
        )
        return result
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"LangGraph not available: {e}. Install langgraph and langchain-core."
        )
    except Exception as e:
        logger.error("graph_invoke_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/status")
async def get_graph_status():
    """Get the status of the LangGraph orchestration graph."""
    try:
        from app.services.orchestration_graph import _compiled_graph
        return {
            "graph_compiled": _compiled_graph is not None,
            "available_routes": [
                "sprint", "task", "email", "calendar", "enhancement",
                "briefing", "research", "notion", "money_maker", "knowledge",
                "workflow", "system", "tiktok", "content", "prediction_market",
                "planner", "general",
            ],
            "checkpointer": type(_compiled_graph.checkpointer).__name__ if _compiled_graph and hasattr(_compiled_graph, 'checkpointer') and _compiled_graph.checkpointer else "none",
        }
    except ImportError:
        return {
            "graph_compiled": False,
            "error": "LangGraph not installed",
        }


# =============================================================================
# Conversation History & Traces
# =============================================================================

@router.get("/conversations")
async def list_conversations(
    thread_id: Optional[str] = None,
    channel: Optional[str] = None,
    route: Optional[str] = None,
    errors_only: bool = False,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    """List orchestrator conversations with optional filters."""
    from app.services.orchestrator_trace_service import list_conversations as _list
    return await _list(
        thread_id=thread_id,
        channel=channel,
        route=route,
        errors_only=errors_only,
        limit=limit,
        offset=offset,
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation_detail(conversation_id: str):
    """Get a single conversation with its full execution trace."""
    from app.services.orchestrator_trace_service import get_conversation_with_traces
    detail = await get_conversation_with_traces(conversation_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.get("/threads")
async def get_threads(
    limit: int = Query(default=20, le=100),
    offset: int = 0,
):
    """List unique conversation threads."""
    from app.services.orchestrator_trace_service import list_threads as _list
    return await _list(limit=limit, offset=offset)


@router.get("/threads/{thread_id}")
async def get_thread_history(
    thread_id: str,
    limit: int = Query(default=100, le=500),
):
    """Get full message history for a thread."""
    from app.services.orchestrator_trace_service import get_thread_history as _get
    return await _get(thread_id=thread_id, limit=limit)


@router.get("/graph/routes/stats")
async def get_route_stats(hours: int = Query(default=24, le=720)):
    """Get aggregated route statistics for the given time period."""
    from app.services.orchestrator_trace_service import get_route_stats as _get
    return await _get(hours=hours)


@router.get("/activity/feed")
async def get_activity_feed(limit: int = Query(default=50, le=200)):
    """Get recent activity events."""
    from app.services.orchestrator_trace_service import get_activity_feed as _get
    return await _get(limit=limit)


# =============================================================================
# SSE Activity Stream
# =============================================================================

@router.get("/activity/stream")
async def activity_stream():
    """Server-Sent Events stream for real-time orchestrator activity.

    Clients connect and receive events as they happen:
    - invocation: new user message received
    - response: agent response sent
    - trace: node execution completed
    - error: an error occurred
    """
    from app.services.orchestrator_trace_service import subscribe_activity, unsubscribe_activity

    queue = subscribe_activity()

    async def event_generator():
        try:
            # Send initial keepalive
            yield f"data: {json.dumps({'event_type': 'connected', 'status': 'ok'})}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive every 30s
                    yield f": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_activity(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
