"""
LangChain tool functions for Legion API integration.
Sprint 53 Task 112: Build LangChain tools for Legion API integration.

These tools wrap the existing LegionClient to expose sprint/task/project
operations as LangGraph-compatible tool nodes.
"""

from typing import Optional
from langchain_core.tools import tool
import structlog

logger = structlog.get_logger()


def _get_legion_client():
    """Lazy import to avoid circular imports."""
    from app.services.legion_client import get_legion_client
    return get_legion_client()


@tool
async def query_sprints(
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 10
) -> str:
    """Query sprints from Legion sprint manager.

    Args:
        project_id: Filter by project ID (optional)
        status: Filter by status: planned, active, completed, cancelled (optional)
        limit: Maximum number of sprints to return (default 10)

    Returns:
        Formatted string with sprint summaries
    """
    client = _get_legion_client()
    try:
        params = {}
        if project_id:
            params["project_id"] = project_id
        if status:
            params["status"] = status
        sprints = await client.list_sprints(**params)
        if not sprints:
            return "No sprints found matching criteria."

        lines = []
        for s in sprints[:limit]:
            progress = f"{s.get('completed_tasks', 0)}/{s.get('total_tasks', 0)}"
            lines.append(
                f"S{s['id']} [{s['status']}] {s['name']} ({progress} tasks)"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error("query_sprints_failed", error=str(e))
        return f"Error querying sprints: {e}"
    finally:
        pass  # singleton client — do not close


@tool
async def get_sprint_details(sprint_id: int) -> str:
    """Get detailed information about a specific sprint including its tasks.

    Args:
        sprint_id: The sprint ID to look up

    Returns:
        Formatted string with sprint details and task list
    """
    client = _get_legion_client()
    try:
        sprint = await client.get_sprint(sprint_id)
        if not sprint:
            return f"Sprint {sprint_id} not found."

        tasks = await client.list_tasks(sprint_id)
        lines = [
            f"Sprint {sprint['id']}: {sprint['name']}",
            f"Status: {sprint['status']}",
            f"Progress: {sprint.get('completed_tasks', 0)}/{sprint.get('total_tasks', 0)}",
            f"Description: {sprint.get('description', 'N/A')[:200]}",
            "",
            "Tasks:",
        ]
        for t in (tasks or []):
            lines.append(f"  [{t['status']}] T{t['id']}: {t['title']}")
        return "\n".join(lines)
    except Exception as e:
        logger.error("get_sprint_details_failed", error=str(e))
        return f"Error getting sprint details: {e}"
    finally:
        pass  # singleton client — do not close


@tool
async def create_task(
    sprint_id: int,
    title: str,
    description: str,
    prompt: str,
    priority: int = 3
) -> str:
    """Create a new task in a Legion sprint.

    Args:
        sprint_id: Sprint to add the task to
        title: Short task title
        description: Detailed task description
        prompt: The execution prompt for autonomous task execution
        priority: Priority 1-5 (1=highest)

    Returns:
        Confirmation with task ID
    """
    client = _get_legion_client()
    try:
        task_data = {
            "title": title,
            "description": description,
            "prompt": prompt,
            "priority": priority,
        }
        result = await client.create_task(sprint_id, task_data)
        if result:
            return f"Created task T{result.get('id', '?')}: {title} in sprint {sprint_id}"
        return "Failed to create task - no response from Legion."
    except Exception as e:
        logger.error("create_task_failed", error=str(e))
        return f"Error creating task: {e}"
    finally:
        pass  # singleton client — do not close


@tool
async def update_task_status(
    task_id: int,
    status: str,
    completion_notes: Optional[str] = None
) -> str:
    """Update a task's status in Legion.

    Args:
        task_id: The task ID to update
        status: New status: pending, running, completed, failed
        completion_notes: Optional notes about the status change

    Returns:
        Confirmation of the update
    """
    client = _get_legion_client()
    try:
        update_data = {"status": status}
        if completion_notes:
            update_data["completion_notes"] = completion_notes
        result = await client.update_task(task_id, update_data)
        if result:
            return f"Task T{task_id} updated to '{status}'"
        return f"Failed to update task T{task_id}."
    except Exception as e:
        logger.error("update_task_status_failed", error=str(e))
        return f"Error updating task: {e}"
    finally:
        pass  # singleton client — do not close


@tool
async def get_project_health(project_id: Optional[int] = None) -> str:
    """Get health status for projects managed by Legion.

    Args:
        project_id: Specific project ID, or None for all projects

    Returns:
        Formatted health summary
    """
    client = _get_legion_client()
    try:
        if project_id:
            projects = [await client.get_project(project_id)]
        else:
            projects = await client.list_projects(status="active")

        if not projects:
            return "No projects found."

        lines = []
        for p in projects:
            if not p:
                continue
            lines.append(f"P{p['id']}: {p['name']} [{p['status']}]")
            tech = p.get('tech_stack')
            if tech:
                if isinstance(tech, dict):
                    lang = tech.get('primary_language') or 'unknown'
                    frameworks = tech.get('frameworks', [])
                    lines.append(f"  Stack: {lang}, {', '.join(frameworks[:5])}" if frameworks else f"  Stack: {lang}")
                elif isinstance(tech, list):
                    lines.append(f"  Stack: {', '.join(tech[:5])}")
        return "\n".join(lines) if lines else "No project data available."
    except Exception as e:
        logger.error("get_project_health_failed", error=str(e))
        return f"Error getting project health: {e}"
    finally:
        pass  # singleton client — do not close


@tool
async def get_daily_summary() -> str:
    """Get a comprehensive daily summary from Legion covering all projects.

    Returns:
        Formatted daily summary with project health, active sprints, and blocked tasks
    """
    client = _get_legion_client()
    try:
        summary = await client.get_daily_summary()
        if not summary:
            return "Could not retrieve daily summary from Legion."

        lines = [
            "=== Daily Summary ===",
            f"Projects: {summary.get('total_projects', 0)} total, {summary.get('healthy_projects', 0)} healthy",
            f"Active Sprints: {summary.get('active_sprints', 0)}",
            f"Blocked Tasks: {summary.get('blocked_count', 0)}",
        ]

        blocked = summary.get('blocked_tasks', [])
        if blocked:
            lines.append("\nBlocked Tasks:")
            for t in blocked[:5]:
                lines.append(f"  T{t.get('id', '?')}: {t.get('title', 'Unknown')}")

        return "\n".join(lines)
    except Exception as e:
        logger.error("get_daily_summary_failed", error=str(e))
        return f"Error getting daily summary: {e}"
    finally:
        pass  # singleton client — do not close
