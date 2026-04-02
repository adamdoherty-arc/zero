"""
Proactive Notification Service

Monitors all domains and pushes notifications when action is needed.
Calendar-aware: won't notify during meetings.
"""

import asyncio
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class ProactiveService:
    """Generates proactive notifications across all domains."""

    _running = False

    async def check_and_notify(self) -> List[Dict[str, Any]]:
        """Run all proactive checks and send notifications for urgent items."""
        notifications = []

        # Check availability first — don't notify during meetings
        try:
            from app.services.context_awareness_service import get_context_awareness_service
            ctx = get_context_awareness_service()
            avail = await ctx.is_user_available()
            if avail.get("in_meeting"):
                logger.debug("[Proactive] User in meeting, skipping notifications")
                return []
        except Exception:
            pass

        # 1. Goal deadline alerts
        try:
            from app.services.goal_tracking_service import get_goal_tracking_service
            alerts = await get_goal_tracking_service().get_anticipatory_alerts()
            for alert in alerts:
                if alert["severity"] in ("high", "medium"):
                    notifications.append({
                        "type": "goal_alert",
                        "severity": alert["severity"],
                        "title": f"Goal: {alert['title']}",
                        "message": alert["message"],
                        "domain": "goals",
                    })
        except Exception as e:
            logger.debug(f"[Proactive] Goal check failed: {e}")

        # 2. Blocked tasks
        try:
            from app.services.task_service import get_task_service
            tasks = await get_task_service().list_tasks(limit=50)
            blocked = [t for t in tasks if t.status == "blocked"] if tasks else []
            if len(blocked) >= 3:
                notifications.append({
                    "type": "task_alert",
                    "severity": "medium",
                    "title": f"{len(blocked)} tasks blocked",
                    "message": f"Tasks stuck: {', '.join(t.title[:30] for t in blocked[:3])}",
                    "domain": "tasks",
                })
        except Exception as e:
            logger.debug(f"[Proactive] Task check failed: {e}")

        # 3. Email overload
        try:
            from app.services.gmail_service import get_gmail_service
            from app.models.email import EmailStatus
            emails = await get_gmail_service().list_emails(status=EmailStatus.UNREAD, limit=50)
            unread = len(emails) if emails else 0
            if unread > 20:
                notifications.append({
                    "type": "email_alert",
                    "severity": "low",
                    "title": f"{unread} unread emails",
                    "message": "Inbox needs attention",
                    "domain": "email",
                })
        except Exception as e:
            logger.debug(f"[Proactive] Email check failed: {e}")

        # Send notifications via Discord
        if notifications:
            await self._send_notifications(notifications)

        return notifications

    async def _send_notifications(self, notifications: List[Dict[str, Any]]):
        """Send notifications to Discord."""
        try:
            from app.services.discord_notifier import get_discord_notifier
            notifier = get_discord_notifier()
            for notif in notifications[:5]:
                severity_icon = {"high": "\U0001f534", "medium": "\U0001f7e1", "low": "\U0001f535"}.get(notif["severity"], "\u2139\ufe0f")
                msg = f"{severity_icon} **{notif['title']}**\n{notif['message']}"
                await notifier.send(msg)
        except Exception as e:
            logger.debug(f"[Proactive] Discord notification failed: {e}")

    async def start_monitoring(self, interval_minutes: int = 30):
        """Start periodic proactive monitoring."""
        self._running = True
        logger.info(f"[Proactive] Starting monitoring every {interval_minutes}m")
        while self._running:
            try:
                notifications = await self.check_and_notify()
                if notifications:
                    logger.info(f"[Proactive] Sent {len(notifications)} notification(s)")
            except Exception as e:
                logger.error(f"[Proactive] Monitoring error: {e}")
            await asyncio.sleep(interval_minutes * 60)

    def stop_monitoring(self):
        self._running = False


_proactive_service: Optional[ProactiveService] = None

def get_proactive_service() -> ProactiveService:
    global _proactive_service
    if _proactive_service is None:
        _proactive_service = ProactiveService()
    return _proactive_service
