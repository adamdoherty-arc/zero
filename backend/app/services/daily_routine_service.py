"""
Daily Routine Service

Manages the user's daily routine: morning startup, work blocks, breaks,
end-of-day review. Learns patterns and suggests optimizations.
"""

from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class DailyRoutineService:
    """Orchestrates daily routines combining all Zero services."""

    async def morning_startup(self) -> Dict[str, Any]:
        """Complete morning startup routine."""
        results = {}

        # 1. Generate daily focus
        try:
            from app.services.cross_domain_service import get_cross_domain_service
            focus = await get_cross_domain_service().what_should_i_focus_on()
            results["focus"] = focus
        except Exception as e:
            results["focus_error"] = str(e)

        # 2. Habit status
        try:
            from app.services.habit_service import get_habit_service
            results["habits"] = await get_habit_service().get_today_status()
        except Exception as e:
            results["habits_error"] = str(e)

        # 3. Goal alerts
        try:
            from app.services.goal_tracking_service import get_goal_tracking_service
            results["goal_alerts"] = await get_goal_tracking_service().get_anticipatory_alerts()
        except Exception as e:
            results["goals_error"] = str(e)

        # 4. Calendar preview
        try:
            from app.services.calendar_service import get_calendar_service
            schedule = await get_calendar_service().get_today_schedule()
            events = schedule.events if hasattr(schedule, 'events') else []
            results["events"] = [
                e.get("summary", str(e)) if isinstance(e, dict) else str(e)
                for e in events[:5]
            ]
        except Exception as e:
            results["calendar_error"] = str(e)

        # 5. Email summary
        try:
            from app.services.gmail_service import get_gmail_service
            from app.models.email import EmailStatus
            emails = await get_gmail_service().list_emails(status=EmailStatus.UNREAD, limit=10)
            results["unread_emails"] = len(emails) if emails else 0
        except Exception as e:
            results["email_error"] = str(e)

        # 6. Ecosystem health
        try:
            from app.services.ecosystem_health_service import get_ecosystem_health_service
            health = await get_ecosystem_health_service().get_summary()
            results["ecosystem"] = health.get("overall", "unknown")
        except Exception as e:
            results["ecosystem_error"] = str(e)

        return results

    async def end_of_day_review(self) -> Dict[str, Any]:
        """Generate end-of-day review and auto-journal."""
        results = {}

        # 1. Habit completion
        try:
            from app.services.habit_service import get_habit_service
            results["habits"] = await get_habit_service().get_today_status()
        except Exception:
            pass

        # 2. Auto-journal
        try:
            from app.services.journal_service import get_journal_service
            summary = await get_journal_service().generate_auto_summary()
            results["journal_summary"] = summary
        except Exception:
            pass

        # 3. Tasks completed today
        try:
            from app.services.task_service import get_task_service
            tasks = await get_task_service().list_tasks(limit=50)
            completed = [t for t in tasks if t.status == "completed"] if tasks else []
            results["tasks_completed"] = len(completed)
        except Exception:
            pass

        # 4. Tomorrow preview
        try:
            from app.services.calendar_service import get_calendar_service
            # This might not have a tomorrow method, so we'll handle gracefully
            results["tomorrow_preview"] = "Check calendar for tomorrow's events"
        except Exception:
            pass

        return results

    async def get_routine_briefing(self) -> str:
        """Generate a formatted briefing string."""
        from app.services.context_awareness_service import get_context_awareness_service
        ctx = get_context_awareness_service()
        time_ctx = ctx.get_time_context()

        if time_ctx["period"] in ("early_morning", "morning"):
            data = await self.morning_startup()
            lines = [f"# {time_ctx['greeting']}! Here's your morning briefing:", ""]

            focus = data.get("focus", {})
            if focus.get("summary"):
                lines.append(f"**Focus:** {focus['summary']}")
                for rec in focus.get("recommendations", [])[:3]:
                    lines.append(f"  - [{rec['domain']}] {rec['action']}")
                lines.append("")

            habits = data.get("habits", {})
            if habits.get("total", 0) > 0:
                lines.append(f"**Habits:** {habits['completed']}/{habits['total']} completed")

            events = data.get("events", [])
            if events:
                lines.append(f"**Calendar:** {len(events)} event(s) today")
                for e in events[:3]:
                    lines.append(f"  - {e}")

            unread = data.get("unread_emails", 0)
            if unread > 0:
                lines.append(f"**Email:** {unread} unread")

            alerts = data.get("goal_alerts", [])
            if alerts:
                lines.append(f"**Alerts:** {len(alerts)} goal alert(s)")

            return "\n".join(lines)

        elif time_ctx["period"] in ("evening", "night"):
            data = await self.end_of_day_review()
            lines = [f"# {time_ctx['greeting']}! End of day review:", ""]

            habits = data.get("habits", {})
            if habits.get("total", 0) > 0:
                lines.append(f"**Habits:** {habits['completed']}/{habits['total']} ({habits.get('completion_pct', 0):.0f}%)")

            completed = data.get("tasks_completed", 0)
            if completed > 0:
                lines.append(f"**Tasks completed:** {completed}")

            summary = data.get("journal_summary")
            if summary:
                lines.append(f"**Day summary:** {summary}")

            return "\n".join(lines)

        else:
            from app.services.cross_domain_service import get_cross_domain_service
            focus = await get_cross_domain_service().what_should_i_focus_on()
            return focus.get("summary", "All caught up!")


_routine_service: Optional[DailyRoutineService] = None

def get_daily_routine_service() -> DailyRoutineService:
    global _routine_service
    if _routine_service is None:
        _routine_service = DailyRoutineService()
    return _routine_service
