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
            status = await gmail.get_sync_status()
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

        # Overnight Activity section (from autonomous orchestration)
        try:
            await self._add_overnight_activity(sections)
        except Exception as e:
            logger.warning("briefing_overnight_activity_failed", error=str(e))

        # Generate AI-powered suggestions via Ollama
        suggestions = await self._generate_ai_suggestions(
            sections, user_name, calendar_summary, task_summary, email_summary
        )

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

    async def _generate_ai_suggestions(
        self,
        sections: list,
        user_name: str,
        calendar_summary: Optional[str],
        task_summary: Optional[str],
        email_summary: Optional[str],
    ) -> List[str]:
        """Use Ollama to generate prioritized, actionable suggestions for the day."""
        try:
            from app.infrastructure.ollama_client import get_ollama_client

            # Build context from all gathered data
            context_parts = []
            for section in sections:
                context_parts.append(f"**{section.title}**:")
                for item in section.items[:5]:
                    context_parts.append(f"  - {item}")

            if calendar_summary:
                context_parts.append(f"Calendar: {calendar_summary}")
            if task_summary:
                context_parts.append(f"Tasks: {task_summary}")
            if email_summary:
                context_parts.append(f"Email: {email_summary}")

            context = "\n".join(context_parts)

            prompt = (
                f"Based on {user_name}'s current situation, suggest the top 3 most "
                f"important actions for today. Be specific and actionable. "
                f"Return ONLY a JSON array of 3 short strings (max 15 words each). "
                f"No markdown, no explanation.\n\n"
                f"Current situation:\n{context}"
            )

            client = get_ollama_client()
            response = await client.chat_safe(
                prompt,
                task_type="summarization",
                temperature=0.3,
                num_predict=200,
            )

            if response:
                import json as json_module
                # Try to parse JSON array from response
                response = response.strip()
                if response.startswith("["):
                    try:
                        suggestions = json_module.loads(response)
                        if isinstance(suggestions, list):
                            return [str(s) for s in suggestions[:3]]
                    except json_module.JSONDecodeError:
                        pass
                # Fallback: split by newlines
                lines = [l.strip().lstrip("0123456789.-) ") for l in response.split("\n") if l.strip()]
                return lines[:3]

        except Exception as e:
            logger.warning("ai_suggestions_failed", error=str(e))

        # Static fallback if Ollama is unavailable
        suggestions = []
        if task_summary and "0 in progress" in task_summary:
            suggestions.append("Consider starting a task from your backlog")
        if email_summary and "unread" in email_summary:
            try:
                num = int(email_summary.split()[0])
                if num > 10:
                    suggestions.append("You have many unread emails - consider processing your inbox")
            except ValueError:
                pass
        if not calendar_summary or "No events" in calendar_summary:
            suggestions.append("Today looks free - great time for focused work!")
        return suggestions

    async def _add_overnight_activity(self, sections: list):
        """Add overnight autonomous orchestration activity to the briefing."""
        from app.services.autonomous_orchestration_service import get_orchestration_service
        from app.services.ecosystem_sync_service import get_ecosystem_sync_service

        orch = get_orchestration_service()
        eco = get_ecosystem_sync_service()

        items = []

        # Orchestration log: what ran overnight
        log_entries = await orch.get_orchestration_log(limit=20)
        overnight_cutoff = datetime.utcnow() - timedelta(hours=12)
        overnight_entries = [
            e for e in log_entries
            if e.get("timestamp") and datetime.fromisoformat(e["timestamp"]) > overnight_cutoff
        ]

        if overnight_entries:
            actions_count = len(overnight_entries)
            errors_count = sum(1 for e in overnight_entries if e.get("result") == "failed")
            items.append(f"{actions_count} orchestration action(s) overnight")
            if errors_count:
                items.append(f"{errors_count} action(s) had errors")

        # Execution summary from ecosystem data
        try:
            exec_data = await eco._storage.read("executions.json")
            executions = exec_data.get("executions", [])
            recent = [
                e for e in executions
                if e.get("completed_at") and datetime.fromisoformat(
                    str(e["completed_at"]).replace("Z", "+00:00")
                ).replace(tzinfo=None) > overnight_cutoff
            ]
            if recent:
                completed = sum(1 for e in recent if e.get("status") == "completed")
                failed = sum(1 for e in recent if e.get("status") == "failed")
                items.append(f"{completed} task(s) executed, {failed} failure(s)")
        except Exception:
            pass

        # Lifecycle suggestions
        try:
            suggestions = await eco.generate_lifecycle_suggestions()
            if suggestions:
                items.append(f"{len(suggestions)} lifecycle suggestion(s)")
                items.extend([f"  - {s}" for s in suggestions[:2]])
        except Exception:
            pass

        # Enhancement Engine activity (continuous improvement)
        try:
            from app.services.activity_log_service import get_activity_log_service
            from app.services.continuous_enhancement_service import get_continuous_enhancement_service

            activity_log = get_activity_log_service()
            engine = get_continuous_enhancement_service()

            summary = await activity_log.get_summary(hours=12)
            engine_status = await engine.get_status()

            if summary.get("total_events", 0) > 0:
                items.append(
                    f"Enhancement Engine: {summary['improvements_completed']} improvement(s) completed, "
                    f"{summary['files_changed']} file(s) changed"
                )
                if summary.get("by_project"):
                    project_parts = [f"{p}: {c}" for p, c in summary["by_project"].items() if p != "engine"]
                    if project_parts:
                        items.append(f"  Projects: {', '.join(project_parts)}")
                errors = summary.get("by_status", {}).get("error", 0)
                if errors:
                    items.append(f"  {errors} error(s) encountered")

            if engine_status.get("enabled"):
                items.append(
                    f"Engine status: active, {engine_status.get('cycle_count', 0)} cycles, "
                    f"{engine_status.get('improvements_today', 0)} improvements today"
                )
            else:
                items.append("Engine status: disabled")
        except Exception:
            pass

        if items:
            sections.append(BriefingSection(
                title="Overnight Activity",
                icon="🤖",
                items=items,
                priority=2  # Same priority as sprint section
            ))

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
