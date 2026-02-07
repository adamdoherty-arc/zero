"""
Enhanced Legion Integration Service for Zero.
Sprint 43: Proactive intelligence linking Zero's data sources to Legion tasks.

Features:
- Enhancement scanner auto-creates Legion tasks (T78)
- Email-to-Legion-task conversion (T79)
- Meeting-to-task flow from calendar events (T80)
- Blocked task escalation via Discord (T81)
- Cross-project smart task suggestions (T82)
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from functools import lru_cache

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Zero project ID in Legion
ZERO_PROJECT_ID = 8


class LegionIntegrationService:
    """
    Proactive intelligence service connecting Zero's data sources
    (email, calendar, enhancement scanner) to Legion task management.
    """

    def __init__(self):
        self._blocked_task_cache: Dict[int, datetime] = {}
        self._suggestion_cache: Optional[Dict] = None
        self._suggestion_cache_time: Optional[datetime] = None

    # =========================================================================
    # T78: Enhancement Scanner → Legion Tasks
    # =========================================================================

    async def auto_create_enhancement_tasks(
        self,
        confidence_threshold: float = 0.75,
        project_mapping: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Scan all projects for TODO/FIXME signals and auto-create
        high-confidence signals as Legion tasks.
        """
        from app.services.enhancement_service import get_enhancement_service
        from app.services.legion_client import get_legion_client

        enhancement_svc = get_enhancement_service()
        legion = get_legion_client()

        if not await legion.health_check():
            return {"status": "legion_unavailable", "tasks_created": 0}

        # Default project mapping: directory name → Legion project ID
        if not project_mapping:
            project_mapping = {
                "zero": ZERO_PROJECT_ID,
            }

        # Scan for signals
        scan_result = await enhancement_svc.scan_for_signals()
        signals = enhancement_svc.get_signals(status="pending")

        tasks_created = 0
        skipped = 0

        for signal in signals:
            if signal.confidence < confidence_threshold:
                skipped += 1
                continue

            # Determine project ID
            project_id = ZERO_PROJECT_ID
            for proj_name, pid in project_mapping.items():
                if proj_name.lower() in (signal.source_file or "").lower():
                    project_id = pid
                    break

            # Get or create an active sprint for this project
            sprint = await self._get_or_create_sprint(
                legion, project_id, f"Auto: Enhancement Tasks"
            )
            if not sprint:
                continue

            # Create the Legion task
            task_data = {
                "title": f"[{signal.type.upper()}] {signal.message[:100]}",
                "description": (
                    f"Source: {signal.source_file}:{signal.line_number}\n"
                    f"Confidence: {signal.confidence:.0%}\n"
                    f"Context: {signal.context[:200] if signal.context else 'N/A'}"
                ),
                "priority": self._severity_to_priority(signal.severity),
                "order": tasks_created + 1,
                "source": "enhancement_engine",
            }

            try:
                await legion.create_task(sprint["id"], task_data)
                tasks_created += 1
                enhancement_svc.mark_signal_converted(signal.id)
            except Exception as e:
                logger.warning("enhancement_task_create_failed", error=str(e))

        logger.info(
            "enhancement_auto_tasks",
            scanned=scan_result.get("total_signals", 0),
            created=tasks_created,
            skipped=skipped,
        )

        return {
            "status": "completed",
            "signals_scanned": len(signals),
            "tasks_created": tasks_created,
            "skipped_low_confidence": skipped,
        }

    # =========================================================================
    # T79: Email → Legion Task Conversion
    # =========================================================================

    async def convert_emails_to_tasks(self) -> Dict[str, Any]:
        """
        Analyze recent emails for action items and create Legion tasks.
        Detects deadlines, requests, follow-ups.
        """
        from app.services.gmail_service import get_gmail_service
        from app.services.legion_client import get_legion_client

        gmail = get_gmail_service()
        legion = get_legion_client()

        if not gmail.is_connected():
            return {"status": "gmail_disconnected", "tasks_created": 0}
        if not await legion.health_check():
            return {"status": "legion_unavailable", "tasks_created": 0}

        # Get recent unread emails
        emails = await gmail.get_emails(max_results=20, unread_only=True)
        if not emails:
            return {"status": "no_emails", "tasks_created": 0}

        tasks_created = 0
        sprint = await self._get_or_create_sprint(
            legion, ZERO_PROJECT_ID, "Auto: Email Action Items"
        )
        if not sprint:
            return {"status": "no_sprint", "tasks_created": 0}

        for email in emails:
            action_items = await self._extract_action_items(email)
            if not action_items:
                continue

            for item in action_items:
                task_data = {
                    "title": f"[Email] {item['action'][:100]}",
                    "description": (
                        f"From: {email.from_address}\n"
                        f"Subject: {email.subject}\n"
                        f"Deadline: {item.get('deadline', 'None detected')}\n"
                        f"Context: {item.get('context', '')[:300]}"
                    ),
                    "priority": item.get("priority", 3),
                    "order": tasks_created + 1,
                    "source": "email_pipeline",
                }
                try:
                    await legion.create_task(sprint["id"], task_data)
                    tasks_created += 1
                except Exception as e:
                    logger.warning("email_task_create_failed", error=str(e))

        logger.info("email_to_tasks", emails_checked=len(emails), tasks_created=tasks_created)
        return {"status": "completed", "emails_checked": len(emails), "tasks_created": tasks_created}

    async def _extract_action_items(self, email) -> List[Dict[str, Any]]:
        """Use Ollama to extract action items from an email."""
        subject = email.subject or ""
        body = email.snippet or ""
        from_addr = str(email.from_address) if email.from_address else ""

        prompt = f"""Analyze this email and extract action items. Return JSON array.
Each item: {{"action": "what to do", "deadline": "date or null", "priority": 1-4, "context": "brief reason"}}

From: {from_addr}
Subject: {subject}
Preview: {body[:500]}

If no action items, return empty array []. Only return real actionable tasks.
Return ONLY the JSON array, no other text."""

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": "qwen3:32b",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3},
                    },
                )
                if resp.status_code == 200:
                    import json
                    text = resp.json().get("response", "[]")
                    # Extract JSON from response
                    text = text.strip()
                    if text.startswith("```"):
                        text = text.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]
                    items = json.loads(text.strip())
                    return items if isinstance(items, list) else []
        except Exception as e:
            logger.debug("action_item_extraction_failed", error=str(e))
        return []

    # =========================================================================
    # T80: Calendar Meeting → Prep Task Flow
    # =========================================================================

    async def create_meeting_prep_tasks(self) -> Dict[str, Any]:
        """
        Scan upcoming calendar events for meetings needing prep.
        Create Legion tasks with due dates based on meeting start times.
        """
        from app.services.calendar_service import get_calendar_service
        from app.services.legion_client import get_legion_client

        calendar_svc = get_calendar_service()
        legion = get_legion_client()

        sync_status = calendar_svc.get_sync_status()
        if not sync_status.connected:
            return {"status": "calendar_disconnected", "tasks_created": 0}
        if not await legion.health_check():
            return {"status": "legion_unavailable", "tasks_created": 0}

        # Get events in next 48 hours
        now = datetime.utcnow()
        upcoming = await calendar_svc.list_events(
            start_date=now,
            end_date=now + timedelta(hours=48),
            limit=20,
        )

        tasks_created = 0
        sprint = await self._get_or_create_sprint(
            legion, ZERO_PROJECT_ID, "Auto: Meeting Prep"
        )
        if not sprint:
            return {"status": "no_sprint", "tasks_created": 0}

        for event in upcoming:
            if event.is_all_day:
                continue
            if not event.has_attendees:
                continue  # Solo events don't need prep

            # Determine prep needs via LLM
            prep_items = await self._determine_meeting_prep(event)
            if not prep_items:
                continue

            # Calculate due date (1 hour before meeting)
            event_start = event.start.dateTime or event.start.date
            if isinstance(event_start, str):
                try:
                    due = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
                    due = due - timedelta(hours=1)
                except Exception:
                    due = None
            else:
                due = None

            task_data = {
                "title": f"[Meeting Prep] {event.summary[:80]}",
                "description": (
                    f"Meeting: {event.summary}\n"
                    f"Time: {event_start}\n"
                    f"Location: {event.location or 'N/A'}\n\n"
                    f"Prep needed:\n" + "\n".join(f"- {p}" for p in prep_items)
                ),
                "priority": 2,  # High - time-sensitive
                "order": tasks_created + 1,
                "source": "calendar_pipeline",
            }
            try:
                await legion.create_task(sprint["id"], task_data)
                tasks_created += 1
            except Exception as e:
                logger.warning("meeting_task_create_failed", error=str(e))

        logger.info(
            "meeting_prep_tasks",
            events_checked=len(upcoming),
            tasks_created=tasks_created,
        )
        return {
            "status": "completed",
            "events_checked": len(upcoming),
            "tasks_created": tasks_created,
        }

    async def _determine_meeting_prep(self, event) -> List[str]:
        """Use LLM to determine what prep is needed for a meeting."""
        prompt = f"""Given this calendar event, list preparation items needed.
Event: {event.summary}
Location: {event.location or 'N/A'}
Has attendees: {event.has_attendees}

Return a JSON array of strings, each a prep action. Examples:
["Review Q4 metrics report", "Prepare slide deck", "Test demo environment"]

If no prep needed (casual chat, standup, etc.), return [].
Return ONLY the JSON array."""

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": "qwen3:32b",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3},
                    },
                )
                if resp.status_code == 200:
                    import json
                    text = resp.json().get("response", "[]").strip()
                    if text.startswith("```"):
                        text = text.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]
                    items = json.loads(text.strip())
                    return items if isinstance(items, list) else []
        except Exception:
            pass
        return []

    # =========================================================================
    # T81: Blocked Task Escalation via Discord
    # =========================================================================

    async def escalate_blocked_tasks(
        self, blocked_threshold_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Check Legion for tasks blocked longer than threshold.
        Send Discord notifications for escalation.
        """
        from app.services.legion_client import get_legion_client
        from app.services.notification_service import get_notification_service

        legion = get_legion_client()
        notification_svc = get_notification_service()

        if not await legion.health_check():
            return {"status": "legion_unavailable", "escalated": 0}

        blocked = await legion.get_blocked_tasks()
        if not blocked:
            return {"status": "no_blocked_tasks", "escalated": 0}

        now = datetime.utcnow()
        escalated = 0

        for task in blocked:
            task_id = task.get("id")
            blocked_since = task.get("started_at") or task.get("created_at")

            if not blocked_since:
                continue

            try:
                if isinstance(blocked_since, str):
                    blocked_dt = datetime.fromisoformat(blocked_since.replace("Z", "+00:00"))
                else:
                    blocked_dt = blocked_since
                hours_blocked = (now - blocked_dt.replace(tzinfo=None)).total_seconds() / 3600
            except Exception:
                hours_blocked = 0

            if hours_blocked < blocked_threshold_hours:
                continue

            # Check if we already escalated this task recently
            last_escalated = self._blocked_task_cache.get(task_id)
            if last_escalated and (now - last_escalated).total_seconds() < 86400:
                continue  # Already escalated in last 24h

            message = (
                f"**Blocked Task Escalation**\n\n"
                f"Task: **{task.get('title', 'Unknown')}**\n"
                f"Sprint: {task.get('sprint_name', 'N/A')}\n"
                f"Blocked for: {int(hours_blocked)} hours\n"
                f"Error: {task.get('last_error', 'No error recorded')[:200]}\n\n"
                f"Action needed: unblock or reassign this task."
            )

            try:
                await notification_svc.create_notification(
                    title="Blocked Task Alert",
                    message=message,
                    channel="discord",
                    source="legion_integration",
                    source_id=str(task_id),
                )
                self._blocked_task_cache[task_id] = now
                escalated += 1
            except Exception as e:
                logger.warning("escalation_failed", task_id=task_id, error=str(e))

        logger.info("blocked_task_escalation", total_blocked=len(blocked), escalated=escalated)
        return {
            "status": "completed",
            "total_blocked": len(blocked),
            "escalated": escalated,
        }

    # =========================================================================
    # T82: Cross-Project Smart Task Suggestions
    # =========================================================================

    async def generate_smart_suggestions(self) -> Dict[str, Any]:
        """
        Combine Legion tasks, calendar, and email data to suggest
        the best task to work on next. Included in morning briefing.
        """
        from app.services.legion_client import get_legion_client
        from app.services.calendar_service import get_calendar_service
        from app.services.gmail_service import get_gmail_service

        legion = get_legion_client()

        # Gather data from all sources
        suggestions = []
        context_parts = []

        # 1. Legion: high-priority tasks
        try:
            if await legion.health_check():
                summary = await legion.get_daily_summary()
                context_parts.append(
                    f"Active sprints: {summary.get('active_sprints', 0)}, "
                    f"Blocked: {summary.get('blocked_count', 0)}, "
                    f"Due today: {summary.get('tasks_due_today', 0)}"
                )

                # Get all active sprint tasks
                sprints_data = await legion.list_sprints(status="active")
                for sprint in (sprints_data or []):
                    tasks = await legion.get_sprint_tasks(sprint.get("id"))
                    for task in (tasks or []):
                        if task.get("status") in ("pending", "ready", "in_progress"):
                            suggestions.append({
                                "source": "legion",
                                "title": task.get("title"),
                                "priority": task.get("priority", 3),
                                "sprint": sprint.get("name"),
                                "project": sprint.get("project_name", "Unknown"),
                                "reason": f"Priority {task.get('priority', 3)} in active sprint",
                            })
        except Exception as e:
            logger.debug("legion_suggestions_failed", error=str(e))

        # 2. Calendar: upcoming deadlines
        try:
            calendar_svc = get_calendar_service()
            schedule = await calendar_svc.get_today_schedule()
            if schedule.free_slots:
                context_parts.append(
                    f"Free slots today: {len(schedule.free_slots)}"
                )
        except Exception as e:
            logger.debug("calendar_suggestions_failed", error=str(e))

        # 3. Email: urgent items
        try:
            gmail = get_gmail_service()
            if gmail.is_connected():
                alerts = gmail.get_recent_alerts(hours=24)
                for alert in alerts[:3]:
                    suggestions.append({
                        "source": "email",
                        "title": f"Respond to: {alert.get('subject', 'N/A')[:60]}",
                        "priority": 2,
                        "reason": "Urgent email requiring response",
                    })
        except Exception as e:
            logger.debug("email_suggestions_failed", error=str(e))

        # Rank suggestions by priority (lower = higher priority)
        suggestions.sort(key=lambda s: s.get("priority", 5))
        top_suggestions = suggestions[:5]

        # Use LLM to generate a natural language recommendation
        recommendation = await self._generate_recommendation(
            top_suggestions, context_parts
        )

        result = {
            "status": "completed",
            "suggestions": top_suggestions,
            "recommendation": recommendation,
            "context": "; ".join(context_parts),
            "generated_at": datetime.utcnow().isoformat(),
        }

        self._suggestion_cache = result
        self._suggestion_cache_time = datetime.utcnow()

        return result

    async def _generate_recommendation(
        self, suggestions: List[Dict], context: List[str]
    ) -> str:
        """Generate natural language recommendation using Ollama."""
        if not suggestions:
            return "No pending tasks found. Great time to plan ahead or take a break!"

        suggestion_text = "\n".join(
            f"- [{s.get('source')}] {s.get('title')} (priority {s.get('priority')})"
            for s in suggestions[:5]
        )
        context_text = "; ".join(context) if context else "No additional context"

        prompt = f"""You are a productivity assistant. Based on these pending tasks and context,
recommend what to work on next in 2-3 sentences. Be specific and actionable.

Tasks:
{suggestion_text}

Context: {context_text}

Give a brief, friendly recommendation."""

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": "qwen3:32b",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.5},
                    },
                )
                if resp.status_code == 200:
                    return resp.json().get("response", "").strip()
        except Exception:
            pass

        # Fallback: simple text recommendation
        top = suggestions[0]
        return f"Focus on: {top.get('title')} ({top.get('source')} - priority {top.get('priority')})"

    def get_cached_suggestions(self) -> Optional[Dict]:
        """Get cached suggestions if recent (< 1 hour)."""
        if self._suggestion_cache and self._suggestion_cache_time:
            age = (datetime.utcnow() - self._suggestion_cache_time).total_seconds()
            if age < 3600:
                return self._suggestion_cache
        return None

    # =========================================================================
    # Helpers
    # =========================================================================

    async def _get_or_create_sprint(
        self, legion, project_id: int, name_prefix: str
    ) -> Optional[Dict]:
        """Get active sprint or create one for auto-generated tasks."""
        try:
            current = await legion.get_current_sprint(project_id)
            if current:
                return current

            # Create a new sprint for auto-generated tasks
            sprint_data = {
                "name": f"{name_prefix} - {datetime.utcnow().strftime('%Y-%m-%d')}",
                "description": f"Auto-created sprint for {name_prefix.lower()}",
                "project_id": project_id,
                "status": "active",
                "priority": 3,
            }
            return await legion.create_sprint(sprint_data)
        except Exception as e:
            logger.warning("get_or_create_sprint_failed", error=str(e))
            return None

    @staticmethod
    def _severity_to_priority(severity: str) -> int:
        """Map enhancement severity to Legion priority."""
        mapping = {
            "critical": 1,
            "high": 2,
            "medium": 3,
            "low": 4,
        }
        return mapping.get(severity, 3)


# Singleton
_service: Optional[LegionIntegrationService] = None


def get_legion_integration_service() -> LegionIntegrationService:
    global _service
    if _service is None:
        _service = LegionIntegrationService()
    return _service
