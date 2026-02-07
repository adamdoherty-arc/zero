"""
Sprint Intelligence Service.
Generates sprint proposals, analyzes task health, and provides AI-powered recommendations.
Based on ADA's sprint intelligence patterns.
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from functools import lru_cache
import structlog
import httpx

from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_sprints_path, get_settings
from app.services.enhancement_service import get_enhancement_service

logger = structlog.get_logger()


@dataclass
class SprintProposal:
    """AI-generated sprint proposal."""
    sprint_id: str
    title: str
    goal: str
    suggested_tasks: List[Dict[str, Any]]
    estimated_effort_hours: float
    priority_score: float
    reasoning: str
    signals_used: List[str]
    generated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FeatureHealth:
    """Health assessment for a feature/sprint area."""
    feature_id: str
    display_name: str
    health_score: float  # 0-100
    open_issues: int
    pending_signals: int
    velocity_trend: str  # "improving", "stable", "declining"
    last_activity: Optional[datetime]
    recommendations: List[str]


class SprintIntelligenceService:
    """
    Service for sprint intelligence, health analysis, and AI-powered recommendations.
    """

    def __init__(self):
        self.storage = JsonStorage(get_sprints_path())
        self.settings = get_settings()

    async def scan_todo_comments(self) -> Dict[str, Any]:
        """
        Trigger a full scan for TODO/FIXME comments via enhancement service.
        """
        enhancement_service = get_enhancement_service()
        result = await enhancement_service.scan_for_signals()
        return {
            "status": "completed",
            "scan_result": result
        }

    async def generate_sprint_proposal(self, sprint_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate an AI-powered sprint proposal based on signals and current state.
        """
        # Gather data for proposal
        enhancement_service = get_enhancement_service()
        stats = await enhancement_service.get_stats()

        # Get current sprint info
        sprints_data = await self.storage.read("sprints.json")
        tasks_data = await self.storage.read("tasks.json")

        current_sprint = None
        if sprint_id:
            for s in sprints_data.get("sprints", []):
                if s["id"] == sprint_id:
                    current_sprint = s
                    break
        elif sprints_data.get("currentSprintId"):
            for s in sprints_data.get("sprints", []):
                if s["id"] == sprints_data["currentSprintId"]:
                    current_sprint = s
                    break

        # Get pending tasks and signals
        pending_tasks = [t for t in tasks_data.get("tasks", []) if t.get("status") in ["backlog", "todo"]]

        # Build proposal using LLM
        proposal = await self._generate_llm_proposal(
            current_sprint=current_sprint,
            pending_tasks=pending_tasks,
            signal_stats=stats
        )

        return proposal

    async def _generate_llm_proposal(
        self,
        current_sprint: Optional[Dict],
        pending_tasks: List[Dict],
        signal_stats: Dict
    ) -> Dict[str, Any]:
        """Generate proposal using LLM."""
        # Build context for LLM
        context = f"""
You are a sprint planning assistant. Generate a sprint proposal based on:

CURRENT SPRINT:
{current_sprint if current_sprint else "No active sprint"}

PENDING TASKS ({len(pending_tasks)} total):
{self._format_tasks_for_llm(pending_tasks[:10])}

ENHANCEMENT SIGNALS:
- Total pending signals: {signal_stats.get('pending', 0)}
- By type: {signal_stats.get('by_type', {})}
- By severity: {signal_stats.get('by_severity', {})}

Generate a sprint proposal with:
1. A clear sprint goal
2. Top 5-8 recommended tasks to focus on
3. Estimated effort in hours
4. Priority reasoning

Format as JSON with keys: goal, recommended_tasks, estimated_hours, reasoning
"""

        try:
            # Call Ollama
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url}/chat/completions",
                    json={
                        "model": self.settings.ollama_model,
                        "messages": [
                            {"role": "system", "content": "You are a helpful sprint planning assistant. Always respond with valid JSON."},
                            {"role": "user", "content": context}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1000
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")

                    # Try to parse JSON from response
                    import json
                    try:
                        proposal_data = json.loads(content)
                    except json.JSONDecodeError:
                        # Extract JSON from response if wrapped in markdown
                        import re
                        json_match = re.search(r'\{[\s\S]*\}', content)
                        if json_match:
                            proposal_data = json.loads(json_match.group())
                        else:
                            proposal_data = {"goal": "Continue current work", "reasoning": content}

                    return {
                        "status": "generated",
                        "proposal": {
                            "goal": proposal_data.get("goal", "Focus on high-priority tasks"),
                            "recommended_tasks": proposal_data.get("recommended_tasks", []),
                            "estimated_hours": proposal_data.get("estimated_hours", 40),
                            "reasoning": proposal_data.get("reasoning", "Based on pending signals and tasks"),
                            "generated_at": datetime.utcnow().isoformat()
                        },
                        "context": {
                            "pending_tasks": len(pending_tasks),
                            "pending_signals": signal_stats.get("pending", 0)
                        }
                    }

        except Exception as e:
            logger.warning("LLM proposal generation failed", error=str(e))

        # Fallback: rule-based proposal
        return self._generate_fallback_proposal(pending_tasks, signal_stats)

    def _generate_fallback_proposal(self, pending_tasks: List[Dict], signal_stats: Dict) -> Dict[str, Any]:
        """Generate proposal without LLM (fallback)."""
        # Sort tasks by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_tasks = sorted(
            pending_tasks,
            key=lambda t: priority_order.get(t.get("priority", "medium"), 2)
        )

        recommended = sorted_tasks[:8]
        total_points = sum(t.get("points", 3) for t in recommended)

        return {
            "status": "generated",
            "proposal": {
                "goal": "Complete high-priority tasks and address pending signals",
                "recommended_tasks": [
                    {"id": t["id"], "title": t["title"], "priority": t.get("priority", "medium")}
                    for t in recommended
                ],
                "estimated_hours": total_points * 2,  # Rough estimate: 2 hours per point
                "reasoning": f"Selected {len(recommended)} highest priority tasks. {signal_stats.get('pending', 0)} enhancement signals pending.",
                "generated_at": datetime.utcnow().isoformat()
            },
            "context": {
                "pending_tasks": len(pending_tasks),
                "pending_signals": signal_stats.get("pending", 0)
            }
        }

    def _format_tasks_for_llm(self, tasks: List[Dict]) -> str:
        """Format tasks for LLM context."""
        lines = []
        for t in tasks:
            lines.append(f"- [{t.get('priority', 'medium')}] {t.get('title', 'Untitled')} ({t.get('points', '?')} pts)")
        return '\n'.join(lines) if lines else "No pending tasks"

    async def get_sprint_health(self, sprint_id: str) -> Dict[str, Any]:
        """
        Calculate health score for a sprint.
        """
        sprints_data = await self.storage.read("sprints.json")
        tasks_data = await self.storage.read("tasks.json")

        # Find sprint
        sprint = None
        for s in sprints_data.get("sprints", []):
            if s["id"] == sprint_id:
                sprint = s
                break

        if not sprint:
            return {"error": "Sprint not found"}

        # Get sprint tasks
        sprint_tasks = [t for t in tasks_data.get("tasks", []) if t.get("sprintId") == sprint_id]

        # Calculate metrics
        total_tasks = len(sprint_tasks)
        done_tasks = len([t for t in sprint_tasks if t.get("status") == "done"])
        blocked_tasks = len([t for t in sprint_tasks if t.get("status") == "blocked"])
        in_progress = len([t for t in sprint_tasks if t.get("status") == "in_progress"])

        total_points = sum(t.get("points", 0) for t in sprint_tasks)
        completed_points = sum(t.get("points", 0) for t in sprint_tasks if t.get("status") == "done")

        # Calculate health score (0-100)
        if total_tasks == 0:
            health_score = 100
        else:
            completion_rate = done_tasks / total_tasks
            blocked_penalty = (blocked_tasks / total_tasks) * 30
            progress_bonus = (in_progress / total_tasks) * 10

            health_score = max(0, min(100, (completion_rate * 70) + progress_bonus - blocked_penalty + 30))

        # Determine velocity trend
        velocity_trend = "stable"
        if sprint.get("completedPoints", 0) > sprint.get("totalPoints", 0) * 0.7:
            velocity_trend = "improving"
        elif blocked_tasks > total_tasks * 0.2:
            velocity_trend = "declining"

        # Generate recommendations
        recommendations = []
        if blocked_tasks > 0:
            recommendations.append(f"Resolve {blocked_tasks} blocked tasks")
        if in_progress > 5:
            recommendations.append("Consider completing in-progress tasks before starting new ones")
        if completion_rate < 0.3 and sprint.get("status") == "active":
            recommendations.append("Sprint progress is behind schedule")

        return {
            "sprint_id": sprint_id,
            "sprint_name": sprint.get("name", ""),
            "health_score": round(health_score, 1),
            "metrics": {
                "total_tasks": total_tasks,
                "done_tasks": done_tasks,
                "blocked_tasks": blocked_tasks,
                "in_progress": in_progress,
                "total_points": total_points,
                "completed_points": completed_points,
                "completion_rate": round(completion_rate * 100, 1) if total_tasks > 0 else 0
            },
            "velocity_trend": velocity_trend,
            "recommendations": recommendations
        }

    async def auto_update_sprints(self) -> Dict[str, Any]:
        """
        Automatically update sprint points and status based on task changes.
        This runs periodically to keep sprint data current.
        """
        sprints_data = await self.storage.read("sprints.json")
        tasks_data = await self.storage.read("tasks.json")

        updates = []

        for sprint in sprints_data.get("sprints", []):
            sprint_id = sprint["id"]
            sprint_tasks = [t for t in tasks_data.get("tasks", []) if t.get("sprintId") == sprint_id]

            # Calculate current points
            total_points = sum(t.get("points", 0) for t in sprint_tasks)
            completed_points = sum(t.get("points", 0) for t in sprint_tasks if t.get("status") == "done")

            # Check if update needed
            if sprint.get("totalPoints") != total_points or sprint.get("completedPoints") != completed_points:
                sprint["totalPoints"] = total_points
                sprint["completedPoints"] = completed_points
                updates.append({
                    "sprint_id": sprint_id,
                    "total_points": total_points,
                    "completed_points": completed_points
                })

        if updates:
            await self.storage.write("sprints.json", sprints_data)
            logger.info("Sprints auto-updated", count=len(updates))

        return {
            "status": "completed",
            "sprints_updated": len(updates),
            "updates": updates
        }


@lru_cache()
def get_sprint_intelligence_service() -> SprintIntelligenceService:
    """Get cached sprint intelligence service instance."""
    return SprintIntelligenceService()
