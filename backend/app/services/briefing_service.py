"""
Daily briefing service for ZERO.
Generates personalized morning briefings with calendar, tasks, email, reminders,
and project sprint data from Legion.
"""

import json
from pathlib import Path
from typing import Optional, List
from functools import lru_cache
from datetime import datetime, timedelta
import structlog

from app.models.assistant import DailyBriefing, BriefingSection, Reminder
from app.models.task import TaskStatus

logger = structlog.get_logger()


async def _get_legion_data() -> tuple[Optional[BriefingSection], Optional[str]]:
    """
    Get sprint summary and project health from Legion for the briefing.

    Returns:
        Tuple of (BriefingSection for sprints, health summary string)
    """
    try:
        from app.services.legion_client import get_legion_client

        legion = get_legion_client()

        # Single health check for both operations
        if not await legion.health_check():
            logger.warning("legion_not_reachable")
            return None, None

        # Get daily summary from Legion
        summary = await legion.get_daily_summary()

        # Build sprint section with safe dict access
        sprint_items = []

        total_projects = summary.get('total_projects', 0)
        healthy_projects = summary.get('healthy_projects', 0)
        active_sprints = summary.get('active_sprints', 0)
        blocked_count = summary.get('blocked_count', 0)
        blocked_tasks = summary.get('blocked_tasks', [])

        # Add project count
        sprint_items.append(
            f"📊 {total_projects} project(s), {healthy_projects} healthy"
        )

        # Add active sprints
        sprint_items.append(f"🏃 {active_sprints} active sprint(s)")

        # Add blocked tasks warning if any
        if blocked_count > 0:
            sprint_items.append(f"🚫 {blocked_count} blocked task(s) need attention")
            # Add first few blocked tasks
            for task in blocked_tasks[:2]:
                sprint_items.append(
                    f"   - {task.get('title', 'Unknown')} ({task.get('project_name', '')})"
                )

        section = BriefingSection(
            title="Project Sprints (Legion)",
            icon="🎯",
            items=sprint_items,
            priority=2  # High priority after calendar
        )

        # Build health summary from the same data (avoid extra API calls)
        health_summary = f"{healthy_projects}/{total_projects} projects healthy"

        return section, health_summary

    except Exception as e:
        logger.warning("briefing_legion_failed", error=str(e))
        return None, None


class BriefingService:
    """Service for generating daily briefings."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.briefing_path = self.workspace_path / "briefings"
        self.briefing_path.mkdir(parents=True, exist_ok=True)

    def _get_greeting(self) -> str:
        """Get time-appropriate greeting."""
        hour = datetime.now().hour
        if hour < 12:
            return "Good morning"
        elif hour < 17:
            return "Good afternoon"
        else:
            return "Good evening"

    async def generate_briefing(self) -> DailyBriefing:
        """Generate the daily briefing."""
        from app.services.calendar_service import get_calendar_service
        from app.services.gmail_service import get_gmail_service
        from app.services.task_service import get_task_service
        from app.services.reminder_service import get_reminder_service
        from app.services.knowledge_service import get_knowledge_service

        today = datetime.utcnow().date()
        sections = []

        # Get user name
        user_name = "there"
        try:
            knowledge = get_knowledge_service()
            profile = await knowledge.get_user_profile()
            if profile.name and profile.name != "User":
                user_name = profile.name.split()[0]  # First name only
        except Exception:
            pass

        greeting = f"{self._get_greeting()}, {user_name}!"

        # Calendar section
        calendar_summary = None
        try:
            calendar = get_calendar_service()
            if calendar.has_valid_tokens():
                schedule = await calendar.get_today_schedule()
                if schedule.events:
                    calendar_items = []
                    for event in schedule.events[:5]:
                        time_str = ""
                        if event.start.date_time:
                            dt = datetime.fromisoformat(event.start.date_time.replace("Z", "+00:00"))
                            time_str = dt.strftime("%I:%M %p")
                        else:
                            time_str = "All day"
                        calendar_items.append(f"{time_str}: {event.summary}")

                    sections.append(BriefingSection(
                        title="Today's Schedule",
                        icon="📅",
                        items=calendar_items,
                        priority=1
                    ))
                    calendar_summary = f"{schedule.total_events} event(s) today"
                else:
                    calendar_summary = "No events scheduled for today"
        except Exception as e:
            logger.warning("briefing_calendar_failed", error=str(e))

        # Legion Project Sprints section (from Legion sprint manager)
        project_health_summary = None
        try:
            legion_section, project_health_summary = await _get_legion_data()
            if legion_section:
                sections.append(legion_section)
        except Exception as e:
            logger.warning("briefing_legion_section_failed", error=str(e))

        # Tasks section
        task_summary = None
        try:
            tasks = get_task_service()
            in_progress = await tasks.list_tasks(status=TaskStatus.IN_PROGRESS)
            todo_tasks = await tasks.list_tasks(status=TaskStatus.TODO)

            if in_progress or todo_tasks:
                task_items = []
                for t in in_progress[:3]:
                    task_items.append(f"🔄 {t.title}")
                for t in todo_tasks[:3]:
                    task_items.append(f"📋 {t.title}")

                sections.append(BriefingSection(
                    title="Active Tasks",
                    icon="✅",
                    items=task_items,
                    priority=2
                ))

            task_summary = f"{len(in_progress)} in progress, {len(todo_tasks)} to do"
        except Exception as e:
            logger.warning("briefing_tasks_failed", error=str(e))

        # Email section
        email_summary = None
        try:
            gmail = get_gmail_service()
            status = gmail.get_sync_status()
            if status.connected:
                digest = await gmail.generate_digest()
                if digest.unread_emails > 0:
                    email_items = []
                    for e in digest.urgent_emails[:2]:
                        email_items.append(f"🚨 {e.subject}")
                    for e in digest.important_emails[:2]:
                        email_items.append(f"⭐ {e.subject}")

                    if email_items:
                        sections.append(BriefingSection(
                            title="Email Highlights",
                            icon="📧",
                            items=email_items,
                            priority=3
                        ))

                email_summary = f"{digest.unread_emails} unread email(s)"
        except Exception as e:
            logger.warning("briefing_email_failed", error=str(e))

        # Reminders section
        reminders_due = []
        try:
            reminder_service = get_reminder_service()
            upcoming = await reminder_service.get_upcoming_reminders(hours=24)
            if upcoming:
                reminder_items = [f"⏰ {r.title}" for r in upcoming[:5]]
                sections.append(BriefingSection(
                    title="Reminders",
                    icon="🔔",
                    items=reminder_items,
                    priority=4
                ))
                reminders_due = upcoming[:5]
        except Exception as e:
            logger.warning("briefing_reminders_failed", error=str(e))

        # Generate suggestions
        suggestions = []
        if task_summary and "0 in progress" in task_summary:
            suggestions.append("Consider starting a task from your backlog")
        if email_summary and "unread" in email_summary:
            num = int(email_summary.split()[0])
            if num > 10:
                suggestions.append("You have many unread emails - consider processing your inbox")
        if not calendar_summary or "No events" in calendar_summary:
            suggestions.append("Today looks free - great time for focused work!")

        # Sort sections by priority
        sections.sort(key=lambda x: x.priority)

        briefing = DailyBriefing(
            date=today.isoformat(),
            greeting=greeting,
            sections=sections,
            calendar_summary=calendar_summary,
            task_summary=task_summary,
            email_summary=email_summary,
            project_health_summary=project_health_summary,
            reminders_due=reminders_due,
            suggestions=suggestions,
            generated_at=datetime.utcnow()
        )

        # Save briefing
        self._save_briefing(briefing)

        logger.info("briefing_generated", sections=len(sections))
        return briefing

    def _save_briefing(self, briefing: DailyBriefing):
        """Save briefing to file."""
        filename = f"briefing_{briefing.date}.json"
        filepath = self.briefing_path / filename
        filepath.write_text(json.dumps(briefing.model_dump(), indent=2, default=str))

    async def get_latest_briefing(self) -> Optional[DailyBriefing]:
        """Get the most recent briefing."""
        today = datetime.utcnow().date().isoformat()
        filepath = self.briefing_path / f"briefing_{today}.json"

        if filepath.exists():
            data = json.loads(filepath.read_text())
            return DailyBriefing(**data)

        return None


@lru_cache()
def get_briefing_service() -> BriefingService:
    """Get singleton BriefingService instance."""
    return BriefingService()
