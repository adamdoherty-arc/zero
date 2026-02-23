"""
Agent orchestrator API endpoints.
Provides control over code execution agents and triggers.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
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
        # Auto-start if needed
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
    """
    Trigger full enhancement cycle: scan + create tasks.
    This is the main endpoint for automated enhancement detection.
    """
    orchestrator = get_orchestrator()

    if not orchestrator.is_running:
        await orchestrator.start()

    # Run enhancement scan directly for immediate results
    enhancement_service = get_enhancement_service()

    # Step 1: Scan for signals
    scan_result = await enhancement_service.scan_for_signals()

    # Step 2: Get current sprint
    from app.services.sprint_service import get_sprint_service
    sprint_service = get_sprint_service()
    current_sprint = await sprint_service.get_current_sprint()

    # Step 3: Create tasks from high-confidence signals
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
    """
    Trigger sprint intelligence analysis: health check + proposal generation.
    """
    intelligence_service = get_sprint_intelligence_service()

    # Get sprint ID if not provided
    if not sprint_id:
        from app.services.sprint_service import get_sprint_service
        sprint_service = get_sprint_service()
        current_sprint = await sprint_service.get_current_sprint()
        sprint_id = current_sprint.id if current_sprint else None

    results = {"sprint_id": sprint_id}

    if sprint_id:
        # Get health assessment
        health = await intelligence_service.get_sprint_health(sprint_id)
        results["health"] = health

        # Generate proposal
        proposal = await intelligence_service.generate_sprint_proposal(sprint_id)
        results["proposal"] = proposal

    # Auto-update all sprints
    update_result = await intelligence_service.auto_update_sprints()
    results["sprint_updates"] = update_result

    return results


@router.post("/trigger-auto-update")
async def trigger_auto_update():
    """
    Trigger automatic sprint updates (recalculate points, sync state).
    """
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
# LangGraph Orchestration Gateway (Sprint 53)
# =============================================================================

class OrchestrationRequest(BaseModel):
    """Request schema for LangGraph orchestration."""
    message: str
    thread_id: str = "default"


@router.post("/graph/invoke")
async def invoke_graph(request: OrchestrationRequest):
    """Invoke the LangGraph orchestration graph with a user message.

    Routes the message through the supervisor to specialized subgraphs
    (sprint, email, calendar, enhancement, briefing).
    """
    try:
        from app.services.orchestration_graph import invoke_orchestration
        result = await invoke_orchestration(
            message=request.message,
            thread_id=request.thread_id,
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
            "available_routes": ["sprint", "task", "email", "calendar", "enhancement", "briefing", "research", "notion", "money_maker", "knowledge", "workflow", "system", "general"],
            "checkpointer": type(_compiled_graph.checkpointer).__name__ if _compiled_graph and hasattr(_compiled_graph, 'checkpointer') and _compiled_graph.checkpointer else "none",
        }
    except ImportError:
        return {
            "graph_compiled": False,
            "error": "LangGraph not installed",
        }
