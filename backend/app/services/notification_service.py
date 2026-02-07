"""
Notification service for ZERO.
Manages notifications and cross-channel delivery.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime
import structlog

from app.models.assistant import Notification, NotificationChannel

logger = structlog.get_logger()

# Gateway notification endpoint (internal Docker network or localhost)
_GATEWAY_URL = os.getenv("ZERO_GATEWAY_URL", "http://localhost:18789")


class NotificationService:
    """Service for managing notifications."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.assistant_path = self.workspace_path / "assistant"
        self.assistant_path.mkdir(parents=True, exist_ok=True)
        self.notifications_file = self.assistant_path / "notifications.json"
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure storage file exists."""
        if not self.notifications_file.exists():
            self.notifications_file.write_text(json.dumps({"notifications": []}))

    def _load_notifications(self) -> List[Dict[str, Any]]:
        """Load notifications from storage."""
        try:
            data = json.loads(self.notifications_file.read_text())
            return data.get("notifications", [])
        except Exception:
            return []

    def _save_notifications(self, notifications: List[Dict[str, Any]]):
        """Save notifications to storage."""
        self.notifications_file.write_text(
            json.dumps({"notifications": notifications}, indent=2, default=str)
        )

    async def create_notification(
        self,
        title: str,
        message: str,
        channel: NotificationChannel = NotificationChannel.UI,
        source: Optional[str] = None,
        source_id: Optional[str] = None,
        action_url: Optional[str] = None
    ) -> Notification:
        """Create a new notification."""
        notifications = self._load_notifications()

        notification = Notification(
            id=str(uuid.uuid4()),
            title=title,
            message=message,
            channel=channel,
            source=source,
            source_id=source_id,
            action_url=action_url,
            created_at=datetime.utcnow()
        )

        notifications.insert(0, notification.model_dump())  # Newest first

        # Keep only last 100 notifications
        notifications = notifications[:100]

        self._save_notifications(notifications)

        logger.info("notification_created", id=notification.id, channel=channel.value)

        # Attempt to deliver to external channels
        if channel != NotificationChannel.UI:
            await self._deliver_to_channel(notification)

        return notification

    async def _deliver_to_channel(self, notification: Notification):
        """Deliver notification to external channel via the Zero gateway."""
        token = os.getenv("CLAWDBOT_GATEWAY_TOKEN")
        if not token:
            logger.warning("notification_delivery_skipped", reason="no CLAWDBOT_GATEWAY_TOKEN")
            return

        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(
                    f"{_GATEWAY_URL}/notifications",
                    json={
                        "channel": notification.channel.value,
                        "title": notification.title,
                        "message": notification.message,
                        "source": notification.source,
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )

                if resp.status_code < 400:
                    logger.info(
                        "notification_delivered",
                        id=notification.id,
                        channel=notification.channel.value,
                    )
                else:
                    logger.warning(
                        "notification_delivery_failed",
                        id=notification.id,
                        channel=notification.channel.value,
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
        except Exception as e:
            logger.error(
                "notification_delivery_error",
                id=notification.id,
                channel=notification.channel.value,
                error=str(e),
            )

    async def get_notification(self, notification_id: str) -> Optional[Notification]:
        """Get a notification by ID."""
        notifications = self._load_notifications()
        for n in notifications:
            if n.get("id") == notification_id:
                return Notification(**n)
        return None

    async def list_notifications(
        self,
        unread_only: bool = False,
        channel: Optional[NotificationChannel] = None,
        limit: int = 50
    ) -> List[Notification]:
        """List notifications with optional filters."""
        notifications = self._load_notifications()

        if unread_only:
            notifications = [n for n in notifications if not n.get("read", False)]

        if channel:
            notifications = [n for n in notifications if n.get("channel") == channel.value]

        return [Notification(**n) for n in notifications[:limit]]

    async def mark_as_read(self, notification_id: str) -> Optional[Notification]:
        """Mark a notification as read."""
        notifications = self._load_notifications()

        for i, n in enumerate(notifications):
            if n.get("id") == notification_id:
                notifications[i]["read"] = True
                self._save_notifications(notifications)
                return Notification(**notifications[i])

        return None

    async def mark_all_as_read(self) -> int:
        """Mark all notifications as read. Returns count of marked notifications."""
        notifications = self._load_notifications()
        count = 0

        for i, n in enumerate(notifications):
            if not n.get("read", False):
                notifications[i]["read"] = True
                count += 1

        if count > 0:
            self._save_notifications(notifications)
            logger.info("notifications_marked_read", count=count)

        return count

    async def delete_notification(self, notification_id: str) -> bool:
        """Delete a notification."""
        notifications = self._load_notifications()
        original_len = len(notifications)
        notifications = [n for n in notifications if n.get("id") != notification_id]

        if len(notifications) < original_len:
            self._save_notifications(notifications)
            return True
        return False

    async def clear_all(self) -> int:
        """Clear all notifications. Returns count of deleted notifications."""
        notifications = self._load_notifications()
        count = len(notifications)
        self._save_notifications([])
        return count

    async def get_unread_count(self) -> int:
        """Get count of unread notifications."""
        notifications = self._load_notifications()
        return len([n for n in notifications if not n.get("read", False)])

    async def notify_reminder(self, reminder) -> Notification:
        """Create notification for a triggered reminder."""
        return await self.create_notification(
            title=f"⏰ Reminder: {reminder.title}",
            message=reminder.description or "Time for your reminder!",
            channel=reminder.channels[0] if reminder.channels else NotificationChannel.UI,
            source="reminder",
            source_id=reminder.id
        )

    async def notify_email(self, subject: str, from_email: str, email_id: str) -> Notification:
        """Create notification for an important email."""
        return await self.create_notification(
            title="📧 New Email",
            message=f"From {from_email}: {subject}",
            channel=NotificationChannel.UI,
            source="email",
            source_id=email_id,
            action_url=f"/email/{email_id}"
        )

    async def notify_task(self, task_title: str, message: str, task_id: str) -> Notification:
        """Create notification for a task event."""
        return await self.create_notification(
            title="✅ Task Update",
            message=f"{task_title}: {message}",
            channel=NotificationChannel.UI,
            source="task",
            source_id=task_id,
            action_url=f"/tasks/{task_id}"
        )


@lru_cache()
def get_notification_service() -> NotificationService:
    """Get singleton NotificationService instance."""
    return NotificationService()
