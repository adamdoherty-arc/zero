"""
Orchestration Agent Service.
Manages task execution, agent lifecycle, and event-driven workflows.
Based on ADA patterns.
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
import structlog

logger = structlog.get_logger()


class AgentType(str, Enum):
    """Types of agents in the system."""
    ENHANCEMENT = "enhancement"
    SPRINT_INTELLIGENCE = "sprint_intelligence"
    CODE_EXECUTOR = "code_executor"
    ERROR_MONITOR = "error_monitor"


class TaskPriority(str, Enum):
    """Task priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentTask:
    """Represents a task for agent execution."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent_type: AgentType = AgentType.CODE_EXECUTOR
    priority: TaskPriority = TaskPriority.MEDIUM
    description: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    sprint_task_id: Optional[str] = None  # Link to sprint task


@dataclass
class AgentInfo:
    """Agent state information."""
    agent_type: AgentType
    status: str = "stopped"
    started_at: Optional[datetime] = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    last_error: Optional[str] = None
    instance: Optional[Any] = None


class OrchestratorService:
    """
    Main orchestrator for agent management and task execution.
    Follows ADA patterns with hierarchical startup and health monitoring.
    """

    def __init__(self):
        self._running = False
        self._started_at: Optional[datetime] = None
        self._task_queue: List[AgentTask] = []
        self._completed_tasks: List[AgentTask] = []
        self._agents: Dict[AgentType, AgentInfo] = {}
        self._health_task: Optional[asyncio.Task] = None
        self._processing_task: Optional[asyncio.Task] = None

        # Configuration
        self.health_check_interval = 60  # seconds
        self.max_concurrent_tasks = 3
        self.task_timeout = 300  # seconds

        # Initialize agent info
        for agent_type in AgentType:
            self._agents[agent_type] = AgentInfo(agent_type=agent_type)

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> Dict[str, Any]:
        """Start the orchestrator and all enabled agents."""
        if self._running:
            return {"status": "already_running"}

        logger.info("Starting orchestrator")
        self._running = True
        self._started_at = datetime.utcnow()

        results = {"status": "started", "agents": {}}

        # Start agents in dependency order
        # 1. Error monitor first (catches errors from others)
        results["agents"]["error_monitor"] = await self._start_agent(AgentType.ERROR_MONITOR)

        # 2. Enhancement agent
        results["agents"]["enhancement"] = await self._start_agent(AgentType.ENHANCEMENT)

        # 3. Sprint intelligence
        results["agents"]["sprint_intelligence"] = await self._start_agent(AgentType.SPRINT_INTELLIGENCE)

        # 4. Code executor
        results["agents"]["code_executor"] = await self._start_agent(AgentType.CODE_EXECUTOR)

        # Start background tasks
        self._health_task = asyncio.create_task(self._health_monitor_loop())
        self._processing_task = asyncio.create_task(self._task_processing_loop())

        logger.info("Orchestrator started", agents=list(results["agents"].keys()))
        return results

    async def stop(self) -> Dict[str, Any]:
        """Stop the orchestrator and all agents."""
        if not self._running:
            return {"status": "not_running"}

        logger.info("Stopping orchestrator")
        self._running = False

        # Cancel background tasks
        if self._health_task:
            self._health_task.cancel()
        if self._processing_task:
            self._processing_task.cancel()

        # Stop all agents
        for agent_type in reversed(list(AgentType)):
            await self._stop_agent(agent_type)

        self._started_at = None
        logger.info("Orchestrator stopped")
        return {"status": "stopped"}

    async def _start_agent(self, agent_type: AgentType) -> Dict[str, Any]:
        """Start a specific agent."""
        agent_info = self._agents[agent_type]
        agent_info.status = "running"
        agent_info.started_at = datetime.utcnow()
        logger.info("Agent started", agent_type=agent_type.value)
        return {"status": "started", "agent_type": agent_type.value}

    async def _stop_agent(self, agent_type: AgentType) -> None:
        """Stop a specific agent."""
        agent_info = self._agents[agent_type]
        agent_info.status = "stopped"
        agent_info.started_at = None
        logger.info("Agent stopped", agent_type=agent_type.value)

    async def _health_monitor_loop(self) -> None:
        """Periodic health check for all agents."""
        while self._running:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._check_agent_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error", error=str(e))

    async def _check_agent_health(self) -> None:
        """Check health of all agents and restart if needed."""
        for agent_type, agent_info in self._agents.items():
            if agent_info.status == "error":
                logger.warning("Restarting failed agent", agent_type=agent_type.value)
                await self._start_agent(agent_type)

    async def _task_processing_loop(self) -> None:
        """Process queued tasks."""
        while self._running:
            try:
                await asyncio.sleep(1)  # Check queue every second

                # Sort by priority
                self._task_queue.sort(key=lambda t: list(TaskPriority).index(t.priority))

                # Process pending tasks
                running_count = sum(1 for t in self._task_queue if t.status == TaskStatus.RUNNING)

                for task in self._task_queue[:]:
                    if task.status == TaskStatus.PENDING and running_count < self.max_concurrent_tasks:
                        asyncio.create_task(self._execute_task(task))
                        running_count += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Task processing error", error=str(e))

    async def _execute_task(self, task: AgentTask) -> None:
        """Execute a single task."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        agent_info = self._agents.get(task.agent_type)

        logger.info("Executing task", task_id=task.task_id, agent_type=task.agent_type.value)

        try:
            # Execute based on agent type
            if task.agent_type == AgentType.ENHANCEMENT:
                result = await self._run_enhancement_task(task)
            elif task.agent_type == AgentType.SPRINT_INTELLIGENCE:
                result = await self._run_sprint_intelligence_task(task)
            elif task.agent_type == AgentType.CODE_EXECUTOR:
                result = await self._run_code_executor_task(task)
            else:
                result = {"status": "no_handler"}

            task.status = TaskStatus.COMPLETED
            task.result = result
            if agent_info:
                agent_info.tasks_completed += 1

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            if agent_info:
                agent_info.tasks_failed += 1
                agent_info.last_error = str(e)
            logger.error("Task failed", task_id=task.task_id, error=str(e))

        finally:
            task.completed_at = datetime.utcnow()
            # Move to completed
            if task in self._task_queue:
                self._task_queue.remove(task)
            self._completed_tasks.append(task)

    async def _run_enhancement_task(self, task: AgentTask) -> Dict[str, Any]:
        """Run enhancement detection task."""
        from app.services.enhancement_service import get_enhancement_service
        service = get_enhancement_service()

        action = task.payload.get("action", "scan")
        if action == "scan":
            return await service.scan_for_signals()
        elif action == "create_tasks":
            return await service.create_tasks_from_signals(task.payload.get("sprint_id"))
        return {"status": "unknown_action"}

    async def _run_sprint_intelligence_task(self, task: AgentTask) -> Dict[str, Any]:
        """Run sprint intelligence task."""
        from app.services.sprint_intelligence_service import get_sprint_intelligence_service
        service = get_sprint_intelligence_service()

        action = task.payload.get("action", "scan_todos")
        if action == "scan_todos":
            return await service.scan_todo_comments()
        elif action == "generate_proposal":
            return await service.generate_sprint_proposal(task.payload.get("sprint_id"))
        return {"status": "unknown_action"}

    async def _run_code_executor_task(self, task: AgentTask) -> Dict[str, Any]:
        """Run code execution task via the Task Execution Service."""
        from app.services.task_execution_service import get_task_execution_service
        executor = get_task_execution_service()

        result = await executor.submit_task(
            title=task.description[:200] or "Orchestrator task",
            description=task.payload.get("description", task.description),
            project_path=task.payload.get("project_path"),
            priority=task.priority.value,
        )
        return {
            "status": "submitted",
            "task_id": result.get("task_id"),
            "message": f"Task submitted for autonomous execution: {result.get('task_id')}",
        }

    def queue_task(self, task: AgentTask) -> str:
        """Add a task to the queue."""
        self._task_queue.append(task)
        logger.info("Task queued", task_id=task.task_id, priority=task.priority.value)
        return task.task_id

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive orchestrator status."""
        uptime = None
        if self._started_at:
            uptime = int((datetime.utcnow() - self._started_at).total_seconds())

        agents_status = {}
        for agent_type, info in self._agents.items():
            agents_status[agent_type.value] = {
                "status": info.status,
                "started_at": info.started_at.isoformat() if info.started_at else None,
                "tasks_completed": info.tasks_completed,
                "tasks_failed": info.tasks_failed,
                "last_error": info.last_error
            }

        return {
            "orchestrator": {
                "running": self._running,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "uptime_seconds": uptime,
                "health_check_interval": self.health_check_interval
            },
            "agents": agents_status,
            "task_queue": {
                "pending": len([t for t in self._task_queue if t.status == TaskStatus.PENDING]),
                "running": len([t for t in self._task_queue if t.status == TaskStatus.RUNNING]),
                "completed": len(self._completed_tasks),
                "failed": len([t for t in self._completed_tasks if t.status == TaskStatus.FAILED])
            },
            "recent_tasks": [
                {
                    "task_id": t.task_id,
                    "agent_type": t.agent_type.value,
                    "status": t.status.value,
                    "description": t.description[:100]
                }
                for t in (self._completed_tasks[-10:] + self._task_queue)
            ]
        }

    async def trigger_enhancement_cycle(self) -> Dict[str, Any]:
        """Trigger a full enhancement cycle."""
        task = AgentTask(
            agent_type=AgentType.ENHANCEMENT,
            priority=TaskPriority.HIGH,
            description="Run enhancement detection cycle",
            payload={"action": "scan"}
        )
        task_id = self.queue_task(task)
        return {"status": "triggered", "task_id": task_id}

    async def trigger_sprint_intelligence(self, sprint_id: Optional[str] = None) -> Dict[str, Any]:
        """Trigger sprint intelligence analysis."""
        task = AgentTask(
            agent_type=AgentType.SPRINT_INTELLIGENCE,
            priority=TaskPriority.MEDIUM,
            description="Scan for TODO/FIXME comments and generate proposals",
            payload={"action": "scan_todos", "sprint_id": sprint_id}
        )
        task_id = self.queue_task(task)
        return {"status": "triggered", "task_id": task_id}


# Singleton instance
_orchestrator_instance: Optional[OrchestratorService] = None


def get_orchestrator() -> OrchestratorService:
    """Get the singleton orchestrator instance."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = OrchestratorService()
    return _orchestrator_instance
