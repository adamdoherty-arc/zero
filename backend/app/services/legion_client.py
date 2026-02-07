"""
Legion Client - API client for communicating with Legion sprint manager

This client provides a unified interface for Zero to interact with Legion's
sprint management capabilities, including:
- Sprint operations (list, create, update, get metrics)
- Task operations (create, update, move status)
- Hub operations (feature areas)
- Goal operations (sprint targets)
- Project operations (registration, health)

Legion is THE sprint manager for all projects.
"""
import asyncio
import aiohttp
from typing import Optional, List, Dict, Any
from datetime import datetime
from functools import lru_cache
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


# ============================================
# CONFIGURATION
# ============================================

class LegionConfig(BaseModel):
    """Configuration for Legion client."""
    base_url: str = Field(default="http://localhost:8005")
    api_prefix: str = Field(default="/api")
    timeout_seconds: int = Field(default=30)
    retry_count: int = Field(default=3)
    retry_delay_seconds: float = Field(default=1.0)


# ============================================
# RESPONSE MODELS
# ============================================

class SprintSummary(BaseModel):
    """Summary of a sprint for briefings."""
    id: int
    name: str
    project_id: int
    project_name: Optional[str] = None
    status: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    progress_percentage: float
    health_score: Optional[float] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None


class ProjectHealth(BaseModel):
    """Health status for a project."""
    project_id: int
    project_name: str
    status: str
    active_tasks: int
    completed_tasks: int
    blocked_tasks: int
    health_score: float
    current_sprint: Optional[SprintSummary] = None


class TaskInfo(BaseModel):
    """Basic task information."""
    id: int
    sprint_id: int
    title: str
    status: str
    priority: int
    description: Optional[str] = None
    story_points: Optional[int] = None
    blocked_reason: Optional[str] = None


# ============================================
# LEGION CLIENT
# ============================================

class LegionClient:
    """
    Async client for communicating with Legion sprint engine.

    Usage:
        client = LegionClient()
        sprints = await client.list_sprints(project_id=1)
        await client.create_task(sprint_id=1, task_data={...})
    """

    def __init__(self, config: Optional[LegionConfig] = None):
        self.config = config or LegionConfig()
        self._session: Optional[aiohttp.ClientSession] = None

        from app.infrastructure.circuit_breaker import get_circuit_breaker
        self._circuit_breaker = get_circuit_breaker(
            "legion",
            failure_threshold=5,
            recovery_timeout=30.0,
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            # Use connection pooling for better performance
            connector = aiohttp.TCPConnector(
                limit=10,  # Max connections
                limit_per_host=5,  # Max connections per host
                ttl_dns_cache=300  # DNS cache TTL
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector
            )
        return self._session

    async def close(self):
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
        retry: bool = True
    ) -> Dict[str, Any]:
        """Make an HTTP request to Legion API with circuit breaker + retry logic."""
        from app.infrastructure.circuit_breaker import CircuitBreakerError
        try:
            return await self._circuit_breaker.call(
                self._do_request, method, endpoint, params, json, retry
            )
        except CircuitBreakerError:
            logger.warning("legion_circuit_open", endpoint=endpoint)
            raise LegionConnectionError("Legion circuit breaker is open — service unavailable")

    async def _do_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
        retry: bool = True
    ) -> Dict[str, Any]:
        """Inner request logic with retry (called through circuit breaker)."""
        url = f"{self.config.base_url}{self.config.api_prefix}{endpoint}"
        session = await self._get_session()

        last_error = None
        attempts = self.config.retry_count if retry else 1

        for attempt in range(attempts):
            try:
                async with session.request(
                    method,
                    url,
                    params=params,
                    json=json
                ) as response:
                    if response.status == 404:
                        return None
                    response.raise_for_status()
                    return await response.json()

            except aiohttp.ClientResponseError as e:
                # Don't retry on client errors (4xx)
                if 400 <= e.status < 500:
                    logger.warning(
                        "legion_client_error",
                        endpoint=endpoint,
                        status=e.status,
                        error=str(e)
                    )
                    raise LegionAPIError(f"Legion API error {e.status}: {e.message}")
                last_error = e
                logger.warning(
                    "legion_request_failed",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    status=e.status,
                    error=str(e)
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))

            except aiohttp.ClientError as e:
                last_error = e
                logger.warning(
                    "legion_request_failed",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    error=str(e)
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))

        logger.error(
            "legion_request_exhausted",
            endpoint=endpoint,
            error=str(last_error)
        )
        raise LegionConnectionError(f"Failed to connect to Legion: {last_error}")

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request."""
        return await self._request("GET", endpoint, params=params)

    async def _post(self, endpoint: str, json: Optional[Dict] = None) -> Dict:
        """Make a POST request."""
        return await self._request("POST", endpoint, json=json)

    async def _patch(self, endpoint: str, json: Optional[Dict] = None) -> Dict:
        """Make a PATCH request."""
        return await self._request("PATCH", endpoint, json=json)

    async def _delete(self, endpoint: str) -> Dict:
        """Make a DELETE request."""
        return await self._request("DELETE", endpoint)

    # ============================================
    # HEALTH & STATUS
    # ============================================

    async def health_check(self) -> bool:
        """Check if Legion is healthy and reachable."""
        try:
            # Health endpoint is at root level, not under /api
            session = await self._get_session()
            url = f"{self.config.base_url}/health"
            async with session.get(url) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("status") == "healthy"
                return False
        except Exception:
            return False

    async def get_system_state(self) -> Dict[str, Any]:
        """Get Legion's current system state."""
        return await self._get("/system/state")

    # ============================================
    # PROJECT OPERATIONS
    # ============================================

    async def list_projects(self, status: Optional[str] = None) -> List[Dict]:
        """Get all registered projects."""
        params = {"status": status} if status else None
        result = await self._get("/projects", params)
        return result if isinstance(result, list) else result.get("projects", [])

    async def get_project(self, project_id: int) -> Optional[Dict]:
        """Get a specific project by ID."""
        return await self._get(f"/projects/{project_id}")

    async def get_project_health(self, project_id: int) -> Optional[ProjectHealth]:
        """Get health status for a project."""
        # Get task stats
        stats = await self._get(f"/tasks/stats/{project_id}")
        if not stats:
            return None

        # Get project info for name
        project = await self.get_project(project_id)
        if not project:
            return None

        # Calculate health score based on task completion
        total = stats.get("total", 0)
        completed = stats.get("completed", 0)
        blocked = stats.get("blocked", 0)
        health_score = 100.0 if total == 0 else (completed / total) * 100

        # Penalize for blocked tasks
        if blocked > 0 and total > 0:
            health_score = max(0, health_score - (blocked / total) * 30)

        return ProjectHealth(
            project_id=project_id,
            project_name=project.get("name", "Unknown"),
            status=project.get("status", "unknown"),
            active_tasks=stats.get("in_progress", 0),
            completed_tasks=completed,
            blocked_tasks=blocked,
            health_score=round(health_score, 1)
        )

    async def create_project(self, project_data: Dict) -> Dict:
        """Register a new project with Legion."""
        return await self._post("/projects", project_data)

    # ============================================
    # SPRINT OPERATIONS
    # ============================================

    async def list_sprints(
        self,
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get all sprints, optionally filtered by project and status."""
        params = {"limit": limit}
        if project_id:
            params["project_id"] = project_id
        if status:
            params["status"] = status

        result = await self._get("/sprints", params)
        return result if isinstance(result, list) else result.get("sprints", [])

    async def get_sprint(self, sprint_id: int) -> Optional[Dict]:
        """Get a specific sprint by ID."""
        result = await self._get(f"/sprints/{sprint_id}")
        # API returns {"sprint": {...}, "tasks": [...]} - extract sprint
        if result and "sprint" in result:
            return result["sprint"]
        return result

    async def get_current_sprint(self, project_id: int) -> Optional[Dict]:
        """Get the active sprint for a project."""
        sprints = await self.list_sprints(project_id=project_id, status="active", limit=1)
        return sprints[0] if sprints else None

    async def create_sprint(self, sprint_data: Dict) -> Dict:
        """Create a new sprint."""
        return await self._post("/sprints", sprint_data)

    async def update_sprint(self, sprint_id: int, update_data: Dict) -> Dict:
        """Update a sprint."""
        return await self._patch(f"/sprints/{sprint_id}", update_data)

    async def get_sprint_metrics(self, sprint_id: int) -> Dict:
        """Get detailed metrics for a sprint."""
        sprint = await self.get_sprint(sprint_id)
        if not sprint:
            return {}

        return {
            "sprint_id": sprint_id,
            "total_tasks": sprint.get("total_tasks", 0),
            "completed_tasks": sprint.get("completed_tasks", 0),
            "failed_tasks": sprint.get("failed_tasks", 0),
            "completion_percentage": self._calc_completion(
                sprint.get("completed_tasks", 0),
                sprint.get("total_tasks", 0)
            ),
            "status": sprint.get("status"),
            "auto_execute": sprint.get("auto_execute", False)
        }

    async def get_sprint_summary(self, sprint_id: int) -> Optional[SprintSummary]:
        """Get a sprint summary suitable for briefings."""
        sprint = await self.get_sprint(sprint_id)
        if not sprint:
            return None

        return SprintSummary(
            id=sprint["id"],
            name=sprint["name"],
            project_id=sprint["project_id"],
            status=sprint["status"],
            total_tasks=sprint.get("total_tasks", 0),
            completed_tasks=sprint.get("completed_tasks", 0),
            failed_tasks=sprint.get("failed_tasks", 0),
            progress_percentage=self._calc_completion(
                sprint.get("completed_tasks", 0),
                sprint.get("total_tasks", 0)
            ),
            planned_start=sprint.get("planned_start"),
            planned_end=sprint.get("planned_end")
        )

    def _calc_completion(self, completed: int, total: int) -> float:
        """Calculate completion percentage."""
        if total == 0:
            return 0.0
        return round((completed / total) * 100, 1)

    # ============================================
    # TASK OPERATIONS
    # ============================================

    async def list_tasks(
        self,
        sprint_id: int,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get tasks for a sprint."""
        params = {"limit": limit}
        if status:
            params["status"] = status

        result = await self._get(f"/sprints/{sprint_id}/tasks", params)
        return result if isinstance(result, list) else result.get("tasks", [])

    async def get_task(self, task_id: int) -> Optional[Dict]:
        """Get a specific task by ID."""
        return await self._get(f"/sprints/tasks/{task_id}")

    async def create_task(self, sprint_id: int, task_data: Dict) -> Dict:
        """Create a task in a sprint."""
        return await self._post(f"/sprints/{sprint_id}/tasks", task_data)

    async def update_task(self, task_id: int, update_data: Dict) -> Dict:
        """Update a task."""
        return await self._patch(f"/sprints/tasks/{task_id}", update_data)

    async def move_task(
        self,
        task_id: int,
        new_status: str,
        reason: Optional[str] = None
    ) -> Dict:
        """Move a task to a new status."""
        return await self._post(
            f"/sprints/tasks/{task_id}/move",
            {"status": new_status, "reason": reason}
        )

    async def get_blocked_tasks(self, project_id: Optional[int] = None) -> List[Dict]:
        """Get all blocked/failed tasks, optionally filtered by project.

        Note: Legion uses 'failed' status instead of 'blocked'. Tasks that need
        attention are those in 'failed' state.
        """
        # Get active sprints
        sprints = await self.list_sprints(project_id=project_id, status="active")

        blocked = []
        for sprint in sprints:
            # Legion uses 'failed' status for tasks that need attention
            tasks = await self.list_tasks(sprint["id"], status="failed")
            for task in tasks:
                task["sprint_name"] = sprint["name"]
                blocked.append(task)

        return blocked

    # ============================================
    # HUB OPERATIONS (ADA Features)
    # ============================================

    async def list_hubs(self, project_id: int) -> List[Dict]:
        """Get all hubs for a project."""
        result = await self._get("/hubs", {"project_id": project_id})
        return result if isinstance(result, list) else []

    async def create_hub(self, hub_data: Dict) -> Dict:
        """Create a new sprint hub."""
        return await self._post("/hubs", hub_data)

    async def update_hub(self, hub_id: int, update_data: Dict) -> Dict:
        """Update a hub."""
        return await self._patch(f"/hubs/{hub_id}", update_data)

    # ============================================
    # GOAL OPERATIONS (ADA Features)
    # ============================================

    async def list_goals(
        self,
        sprint_id: Optional[int] = None,
        hub_id: Optional[int] = None
    ) -> List[Dict]:
        """Get goals for a sprint or hub."""
        params = {}
        if sprint_id:
            params["sprint_id"] = sprint_id
        if hub_id:
            params["hub_id"] = hub_id

        result = await self._get("/goals", params)
        return result if isinstance(result, list) else []

    async def create_goal(self, goal_data: Dict) -> Dict:
        """Create a new sprint goal."""
        return await self._post("/goals", goal_data)

    async def update_goal(self, goal_id: int, update_data: Dict) -> Dict:
        """Update a goal."""
        return await self._patch(f"/goals/{goal_id}", update_data)

    # ============================================
    # AUTONOMOUS EXECUTION
    # ============================================

    async def trigger_autonomous_execution(
        self,
        sprint_id: int,
        auto_push: bool = False
    ) -> Dict:
        """Trigger autonomous sprint execution."""
        return await self._post(
            f"/sprints/{sprint_id}/execute",
            {"auto_push": auto_push}
        )

    async def get_execution_status(self, sprint_id: int) -> Dict:
        """Get autonomous execution status for a sprint."""
        return await self._get(f"/sprints/{sprint_id}/execution-status")

    async def get_recent_executions(
        self,
        project_id: Optional[int] = None,
        since: Optional[datetime] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get recent task executions."""
        params = {"limit": limit}
        if project_id:
            params["project_id"] = project_id
        if since:
            params["since"] = since.isoformat()

        result = await self._get("/monitoring/executions/recent", params)
        return result if isinstance(result, list) else result.get("executions", [])

    # ============================================
    # SWARM OPERATIONS
    # ============================================

    async def trigger_swarm_lifecycle(self, project_id: int, force_plan_next: bool = False) -> Dict:
        """Trigger full sprint lifecycle: audit -> execute -> plan next."""
        return await self._post("/swarm/lifecycle", {
            "project_id": project_id,
            "force_plan_next": force_plan_next,
        })

    async def trigger_swarm_execute(self, sprint_id: int, max_attempts: int = 6) -> Dict:
        """Execute sprint tasks via agent swarm."""
        return await self._post(f"/swarm/execute/{sprint_id}", {
            "max_attempts": max_attempts,
        })

    async def plan_next_sprint(self, project_id: int) -> Dict:
        """Plan next sprint for a project from backlog/ideas."""
        return await self._post(f"/swarm/plan-next/{project_id}", {})

    async def enable_project_autonomy(self, project_id: int, enabled: bool = True) -> Dict:
        """Enable/disable autonomous mode for a project."""
        return await self._patch(f"/projects/{project_id}", {
            "autonomous_mode_enabled": enabled,
            "auto_sprint_enabled": enabled,
        })

    async def get_active_executions(self) -> List[Dict]:
        """Get currently running executions."""
        result = await self._get("/monitoring/executions/active")
        if result is None:
            return []
        return result if isinstance(result, list) else result.get("executions", [])

    # ============================================
    # AGGREGATION FOR ZERO BRIEFINGS
    # ============================================

    async def get_all_projects_summary(self) -> List[ProjectHealth]:
        """Get health summary for all projects (for Zero briefings)."""
        projects = await self.list_projects(status="active")
        summaries = []

        for project in projects:
            try:
                health = await self.get_project_health(project["id"])
                if health:
                    # Get current sprint
                    current = await self.get_current_sprint(project["id"])
                    if current:
                        health.current_sprint = await self.get_sprint_summary(current["id"])
                    summaries.append(health)
            except Exception as e:
                logger.warning(
                    "failed_to_get_project_health",
                    project_id=project["id"],
                    error=str(e)
                )

        return summaries

    async def get_daily_summary(self) -> Dict[str, Any]:
        """
        Get a comprehensive daily summary for Zero's morning briefing.

        Returns:
            Dict with:
            - total_projects: Number of active projects
            - healthy_projects: Projects with health > 70
            - active_sprints: Number of active sprints
            - blocked_tasks: List of blocked tasks
            - blocked_count: Number of blocked tasks
        """
        import asyncio

        projects = await self.list_projects(status="active")

        if not projects:
            return {
                "total_projects": 0,
                "healthy_projects": 0,
                "active_sprints": 0,
                "blocked_tasks": [],
                "blocked_count": 0,
                "generated_at": datetime.utcnow().isoformat()
            }

        async def process_project(project: Dict) -> Dict[str, Any]:
            """Process a single project in parallel."""
            result = {
                "has_active_sprint": False,
                "blocked_tasks": [],
                "is_healthy": False
            }

            try:
                # Get current sprint
                current = await self.get_current_sprint(project["id"])
                if current:
                    result["has_active_sprint"] = True

                    # Get failed tasks (Legion uses 'failed' instead of 'blocked')
                    failed = await self.list_tasks(current["id"], status="failed")
                    for task in failed:
                        task["project_name"] = project["name"]
                        task["sprint_name"] = current["name"]
                        result["blocked_tasks"].append(task)

                # Check health
                health = await self.get_project_health(project["id"])
                if health and health.health_score >= 70:
                    result["is_healthy"] = True
            except Exception as e:
                logger.warning(
                    "daily_summary_project_error",
                    project_id=project["id"],
                    error=str(e)
                )

            return result

        # Process all projects in parallel
        results = await asyncio.gather(
            *[process_project(p) for p in projects],
            return_exceptions=True
        )

        # Aggregate results
        active_sprints = 0
        healthy_count = 0
        blocked_tasks = []

        for result in results:
            if isinstance(result, Exception):
                continue
            if result["has_active_sprint"]:
                active_sprints += 1
            if result["is_healthy"]:
                healthy_count += 1
            blocked_tasks.extend(result["blocked_tasks"])

        return {
            "total_projects": len(projects),
            "healthy_projects": healthy_count,
            "active_sprints": active_sprints,
            "blocked_tasks": blocked_tasks,
            "blocked_count": len(blocked_tasks),
            "generated_at": datetime.utcnow().isoformat()
        }


# ============================================
# EXCEPTIONS
# ============================================

class LegionConnectionError(Exception):
    """Raised when connection to Legion fails."""
    pass


class LegionAPIError(Exception):
    """Raised when Legion returns an error."""
    pass


# ============================================
# SINGLETON INSTANCE
# ============================================

_legion_client: Optional[LegionClient] = None


def get_legion_client() -> LegionClient:
    """Get the singleton Legion client instance."""
    global _legion_client
    if _legion_client is None:
        from app.infrastructure.config import get_settings
        settings = get_settings()
        config = LegionConfig(
            base_url=settings.legion_api_url,
            api_prefix=settings.legion_api_prefix,
            timeout_seconds=settings.legion_timeout
        )
        _legion_client = LegionClient(config)
    return _legion_client


async def close_legion_client():
    """Close the Legion client."""
    global _legion_client
    if _legion_client:
        await _legion_client.close()
        _legion_client = None
