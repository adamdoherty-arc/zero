"""
Goal Tracking Service

Tracks user goals, measures progress, generates check-ins,
and provides anticipatory alerts about goal status.
"""

import uuid
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, update, desc, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)


class GoalTrackingService:
    """Tracks goals, progress, and generates anticipatory alerts."""

    async def create_goal(
        self,
        title: str,
        description: Optional[str] = None,
        category: str = "general",
        target_date: Optional[datetime] = None,
        milestones: Optional[list] = None,
    ) -> Dict[str, Any]:
        from app.db.models import GoalModel
        goal_id = str(uuid.uuid4())[:12]
        async with AsyncSessionLocal() as db:
            goal = GoalModel(
                id=goal_id,
                title=title,
                description=description,
                category=category,
                target_date=target_date,
                milestones=milestones or [],
            )
            db.add(goal)
            await db.commit()
            return {"id": goal_id, "title": title, "status": "active"}

    async def update_progress(
        self,
        goal_id: str,
        progress_pct: float,
        note: Optional[str] = None,
        blockers: Optional[list] = None,
    ) -> Dict[str, Any]:
        from app.db.models import GoalModel, GoalCheckInModel
        async with AsyncSessionLocal() as db:
            goal = await db.get(GoalModel, goal_id)
            if not goal:
                return {"error": "Goal not found"}

            old_progress = goal.progress_pct
            goal.progress_pct = max(0, min(100, progress_pct))
            if progress_pct >= 100:
                goal.status = "completed"

            checkin = GoalCheckInModel(
                goal_id=goal_id,
                progress_delta=progress_pct - old_progress,
                note=note,
                blockers=blockers or [],
            )
            db.add(checkin)
            await db.commit()
            return {
                "goal_id": goal_id,
                "progress": goal.progress_pct,
                "delta": progress_pct - old_progress,
                "status": goal.status,
            }

    async def list_goals(self, status: str = "active") -> List[Dict[str, Any]]:
        from app.db.models import GoalModel
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(GoalModel)
                .where(GoalModel.status == status)
                .order_by(desc(GoalModel.created_at))
            )
            goals = result.scalars().all()
            return [
                {
                    "id": g.id,
                    "title": g.title,
                    "category": g.category,
                    "status": g.status,
                    "progress_pct": g.progress_pct,
                    "target_date": g.target_date.isoformat() if g.target_date else None,
                    "milestones": g.milestones,
                    "created_at": g.created_at.isoformat() if g.created_at else None,
                }
                for g in goals
            ]

    async def get_anticipatory_alerts(self) -> List[Dict[str, Any]]:
        """Generate proactive alerts about goals that need attention."""
        from app.db.models import GoalModel, GoalCheckInModel
        alerts = []
        now = datetime.now(UTC).replace(tzinfo=None)

        async with AsyncSessionLocal() as db:
            # Get active goals
            result = await db.execute(
                select(GoalModel).where(GoalModel.status == "active")
            )
            goals = result.scalars().all()

            for goal in goals:
                # Alert: deadline approaching with low progress
                if goal.target_date:
                    days_left = (goal.target_date.replace(tzinfo=None) - now).days
                    if days_left <= 7 and goal.progress_pct < 80:
                        alerts.append({
                            "type": "deadline_risk",
                            "severity": "high" if days_left <= 3 else "medium",
                            "goal_id": goal.id,
                            "title": goal.title,
                            "message": f"Goal '{goal.title}' is {goal.progress_pct:.0f}% complete with {days_left} days left",
                            "progress_pct": goal.progress_pct,
                            "days_remaining": days_left,
                        })

                # Alert: stale goal (no check-in in 7+ days)
                checkin_result = await db.execute(
                    select(GoalCheckInModel)
                    .where(GoalCheckInModel.goal_id == goal.id)
                    .order_by(desc(GoalCheckInModel.created_at))
                    .limit(1)
                )
                last_checkin = checkin_result.scalar_one_or_none()
                if last_checkin:
                    days_since = (now - last_checkin.created_at.replace(tzinfo=None)).days
                    if days_since >= 7:
                        alerts.append({
                            "type": "stale_goal",
                            "severity": "low",
                            "goal_id": goal.id,
                            "title": goal.title,
                            "message": f"No progress update on '{goal.title}' for {days_since} days",
                            "days_since_checkin": days_since,
                        })
                elif (now - goal.created_at.replace(tzinfo=None)).days >= 3:
                    alerts.append({
                        "type": "no_checkin",
                        "severity": "medium",
                        "goal_id": goal.id,
                        "title": goal.title,
                        "message": f"Goal '{goal.title}' has no progress check-ins yet",
                    })

        return sorted(alerts, key=lambda a: {"high": 0, "medium": 1, "low": 2}.get(a["severity"], 3))

    async def get_goal_context_for_briefing(self) -> str:
        """Generate goal summary for daily briefings."""
        goals = await self.list_goals(status="active")
        alerts = await self.get_anticipatory_alerts()

        if not goals and not alerts:
            return ""

        lines = ["## Goals"]
        for g in goals[:5]:
            progress_bar = "\u2588" * int(g["progress_pct"] / 10) + "\u2591" * (10 - int(g["progress_pct"] / 10))
            deadline = f" (due {g['target_date'][:10]})" if g.get("target_date") else ""
            lines.append(f"  - {g['title']}: {progress_bar} {g['progress_pct']:.0f}%{deadline}")

        if alerts:
            lines.append("\n### Alerts")
            for a in alerts[:3]:
                lines.append(f"  \u26a0 {a['message']}")

        return "\n".join(lines)


_goal_service: Optional[GoalTrackingService] = None

def get_goal_tracking_service() -> GoalTrackingService:
    global _goal_service
    if _goal_service is None:
        _goal_service = GoalTrackingService()
    return _goal_service
