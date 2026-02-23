"""
Prediction Market Legion Manager.
Manages ADA and Zero prediction market sprints via Legion.
Reports on execution progress and quality.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from functools import lru_cache
import structlog

logger = structlog.get_logger()

# Legion project IDs
ZERO_PROJECT_ID = 8
ADA_PROJECT_ID = 6

# Sprint IDs created for prediction market work
PREDICTION_SPRINT_IDS = {
    "zero_data_collection": 1787,
    "ada_data_ingestion": 1788,
    "ada_backend_api": 1789,
    "ada_frontend": 1790,
}


class PredictionLegionManager:
    """Manages prediction market sprints in Legion and reports on execution quality."""

    async def get_sprint_progress(self, sprint_id: int) -> Dict[str, Any]:
        """Get progress for a single sprint."""
        from app.services.legion_client import get_legion_client
        legion = get_legion_client()

        try:
            sprint = await legion.get_sprint(sprint_id)
            if not sprint:
                return {"sprint_id": sprint_id, "status": "not_found"}

            tasks = await legion.list_tasks(sprint_id)

            total = len(tasks)
            completed = sum(1 for t in tasks if t.get("status") == "completed")
            failed = sum(1 for t in tasks if t.get("status") == "failed")
            pending = sum(1 for t in tasks if t.get("status") in ("pending", "todo"))
            in_progress = sum(1 for t in tasks if t.get("status") in ("in_progress", "running"))

            completion_pct = round((completed / total * 100), 1) if total > 0 else 0.0

            return {
                "sprint_id": sprint_id,
                "name": sprint.get("name", "Unknown"),
                "status": sprint.get("status", "unknown"),
                "total_tasks": total,
                "completed": completed,
                "failed": failed,
                "pending": pending,
                "in_progress": in_progress,
                "completion_pct": completion_pct,
                "tasks": [
                    {
                        "id": t.get("id"),
                        "title": t.get("title"),
                        "status": t.get("status"),
                    }
                    for t in tasks
                ],
            }
        except Exception as e:
            logger.warning("legion_sprint_progress_error", sprint_id=sprint_id, error=str(e))
            return {"sprint_id": sprint_id, "status": "error", "error": str(e)}

    async def get_full_progress_report(self) -> Dict[str, Any]:
        """Get progress for all prediction market sprints."""
        results = {}
        total_tasks = 0
        total_completed = 0
        total_failed = 0

        for key, sprint_id in PREDICTION_SPRINT_IDS.items():
            progress = await self.get_sprint_progress(sprint_id)
            results[key] = progress
            total_tasks += progress.get("total_tasks", 0)
            total_completed += progress.get("completed", 0)
            total_failed += progress.get("failed", 0)

        overall_pct = round((total_completed / total_tasks * 100), 1) if total_tasks > 0 else 0.0

        # Quality score: penalize failures, reward completion
        quality_score = max(0.0, min(100.0, overall_pct - (total_failed * 5)))

        return {
            "sprints": results,
            "summary": {
                "total_tasks": total_tasks,
                "total_completed": total_completed,
                "total_failed": total_failed,
                "overall_completion_pct": overall_pct,
                "quality_score": round(quality_score, 1),
            },
            "reported_at": datetime.utcnow().isoformat(),
        }

    async def report_legion_quality(self) -> Dict[str, Any]:
        """Assess how well Legion is executing the prediction market sprints."""
        report = await self.get_full_progress_report()
        summary = report.get("summary", {})

        quality = summary.get("quality_score", 0)
        recommendations = []

        if summary.get("total_failed", 0) > 0:
            recommendations.append(f"{summary['total_failed']} tasks have failed — review and retry or unblock them")

        completion = summary.get("overall_completion_pct", 0)
        if completion < 25:
            recommendations.append("Low progress — consider triggering Legion swarm execution")
        elif completion < 75:
            recommendations.append("In progress — monitor for blockers")
        elif completion >= 100:
            recommendations.append("All tasks complete — ready for verification")

        return {
            "quality_score": quality,
            "completion_pct": completion,
            "recommendations": recommendations,
            "detail": report,
        }


@lru_cache()
def get_prediction_legion_manager() -> PredictionLegionManager:
    """Get cached PredictionLegionManager instance."""
    return PredictionLegionManager()
