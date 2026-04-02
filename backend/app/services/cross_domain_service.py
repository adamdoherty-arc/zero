"""
Cross-Domain Reasoning Service

Synthesizes data across email, calendar, goals, tasks, and sprints
to provide unified recommendations and insights.
"""

from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class CrossDomainService:
    """Synthesizes insights across all Zero domains."""

    async def what_should_i_focus_on(self) -> Dict[str, Any]:
        """Generate prioritized focus recommendations considering all domains."""
        recommendations = []
        context = {}

        # 1. Calendar — what's coming up?
        try:
            from app.services.calendar_service import get_calendar_service
            cal = get_calendar_service()
            schedule = await cal.get_today_schedule()
            events = schedule.events if hasattr(schedule, 'events') else []
            context["events_today"] = len(events)
            if events:
                next_event = events[0]
                summary = next_event.get("summary", "Unknown") if isinstance(next_event, dict) else str(next_event)
                recommendations.append({
                    "priority": 1,
                    "domain": "calendar",
                    "action": f"Prepare for: {summary}",
                    "reason": "Upcoming calendar event",
                })
        except Exception as e:
            logger.debug(f"cross_domain_calendar: {e}")

        # 2. Email — anything urgent?
        try:
            from app.services.gmail_service import get_gmail_service
            from app.models.email import EmailStatus
            svc = get_gmail_service()
            emails = await svc.list_emails(status=EmailStatus.UNREAD, limit=20)
            unread = len(emails) if emails else 0
            context["unread_emails"] = unread
            if unread > 10:
                recommendations.append({
                    "priority": 2,
                    "domain": "email",
                    "action": f"Process {unread} unread emails",
                    "reason": "Inbox getting full",
                })
        except Exception as e:
            logger.debug(f"cross_domain_email: {e}")

        # 3. Tasks — what's blocked or overdue?
        try:
            from app.services.task_service import get_task_service
            svc = get_task_service()
            tasks = await svc.list_tasks(limit=50)
            blocked = [t for t in tasks if t.status == "blocked"] if tasks else []
            context["blocked_tasks"] = len(blocked)
            if blocked:
                recommendations.append({
                    "priority": 2,
                    "domain": "tasks",
                    "action": f"Unblock {len(blocked)} stuck task(s): {blocked[0].title}",
                    "reason": f"Task blocked" + (f": {blocked[0].blocked_reason}" if blocked[0].blocked_reason else ""),
                })
        except Exception as e:
            logger.debug(f"cross_domain_tasks: {e}")

        # 4. Goals — any at risk?
        try:
            from app.services.goal_tracking_service import get_goal_tracking_service
            svc = get_goal_tracking_service()
            alerts = await svc.get_anticipatory_alerts()
            high_alerts = [a for a in alerts if a.get("severity") == "high"]
            context["goal_alerts"] = len(alerts)
            for alert in high_alerts[:2]:
                recommendations.append({
                    "priority": 1,
                    "domain": "goals",
                    "action": alert["message"],
                    "reason": f"Goal at risk ({alert['type']})",
                })
        except Exception as e:
            logger.debug(f"cross_domain_goals: {e}")

        # 5. Sprints — anything behind?
        try:
            from app.services.sprint_service import get_sprint_service
            svc = get_sprint_service()
            sprints = await svc.list_sprints(status="active")
            if sprints:
                for s in sprints[:2]:
                    if s.total_points > 0 and s.completed_points / s.total_points < 0.3:
                        recommendations.append({
                            "priority": 2,
                            "domain": "sprints",
                            "action": f"Sprint '{s.name}' is behind ({s.completed_points}/{s.total_points} points)",
                            "reason": "Less than 30% complete",
                        })
        except Exception as e:
            logger.debug(f"cross_domain_sprints: {e}")

        # 6. Time context
        from app.services.context_awareness_service import get_context_awareness_service
        ctx = get_context_awareness_service()
        time_ctx = ctx.get_time_context()
        context["time_period"] = time_ctx["period"]

        # Sort by priority
        recommendations.sort(key=lambda r: r["priority"])

        # Generate summary
        if not recommendations:
            summary = f"{time_ctx['greeting']}! You're all caught up. No urgent items."
        elif len(recommendations) == 1:
            summary = f"{time_ctx['greeting']}. Top priority: {recommendations[0]['action']}"
        else:
            summary = f"{time_ctx['greeting']}. {len(recommendations)} items need attention. Top: {recommendations[0]['action']}"

        return {
            "summary": summary,
            "recommendations": recommendations[:10],
            "context": context,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def daily_synthesis(self) -> str:
        """Generate a synthesis report for daily briefing."""
        focus = await self.what_should_i_focus_on()
        lines = [focus["summary"], ""]

        for i, rec in enumerate(focus["recommendations"][:5], 1):
            icon = "\U0001f534" if rec["priority"] == 1 else "\U0001f7e1"
            lines.append(f"{i}. {icon} [{rec['domain']}] {rec['action']}")
            if rec.get("reason"):
                lines.append(f"   \u2192 {rec['reason']}")

        return "\n".join(lines)


_cross_domain_service: Optional[CrossDomainService] = None

def get_cross_domain_service() -> CrossDomainService:
    global _cross_domain_service
    if _cross_domain_service is None:
        _cross_domain_service = CrossDomainService()
    return _cross_domain_service
