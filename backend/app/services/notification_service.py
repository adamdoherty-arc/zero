"""
Notification service for ZERO.
Manages notifications and cross-channel delivery.
"""

import os
import uuid
from typing import Optional, List
from functools import lru_cache
from datetime import datetime
import structlog

from sqlalchemy import select, func as sa_func, update

from app.models.assistant import Notification, NotificationChannel
from app.infrastructure.database import get_session
from app.db.models import NotificationModel

logger = structlog.get_logger()

# Gateway notification endpoint (internal Docker network or localhost)
_GATEWAY_URL = os.getenv("ZERO_GATEWAY_URL", "http://localhost:18789")


class NotificationService:
    """Service for managing notifications."""

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
        now = datetime.utcnow()
        notification_id = str(uuid.uuid4())

        async with get_session() as session:
            orm_obj = NotificationModel(
                id=notification_id,
                title=title,
                message=message,
                channel=channel.value if hasattr(channel, 'value') else channel,
                read=False,
                action_url=action_url,
                source=source,
                source_id=source_id,
                created_at=now,
            )
            session.add(orm_obj)
            await session.flush()

            # Prune old notifications: keep only the most recent 100
            # Find the created_at of the 100th most recent notification
            cutoff_query = (
                select(NotificationModel.created_at)
                .order_by(NotificationModel.created_at.desc())
                .offset(100)
                .limit(1)
            )
            cutoff_result = await session.execute(cutoff_query)
            cutoff_row = cutoff_result.scalar_one_or_none()

            if cutoff_row is not None:
                # Delete notifications older than the cutoff
                delete_query = select(NotificationModel).where(
                    NotificationModel.created_at < cutoff_row
                )
                old_result = await session.execute(delete_query)
                for old_row in old_result.scalars().all():
                    await session.delete(old_row)

        notification = Notification(
            id=notification_id,
            title=title,
            message=message,
            channel=channel,
            read=False,
            action_url=action_url,
            source=source,
            source_id=source_id,
            created_at=now,
        )

        logger.info("notification_created", id=notification.id, channel=channel.value)

        # Attempt to deliver to external channels
        if channel != NotificationChannel.UI:
            await self._deliver_to_channel(notification)

        return notification

    async def _deliver_to_channel(self, notification: Notification):
        """Deliver notification to external channel via the Zero gateway."""
        token = os.getenv("ZERO_GATEWAY_TOKEN")
        if not token:
            logger.warning("notification_delivery_skipped", reason="no ZERO_GATEWAY_TOKEN")
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
        async with get_session() as session:
            row = await session.get(NotificationModel, notification_id)
            if row is None:
                return None
            return self._orm_to_notification(row)

    async def list_notifications(
        self,
        unread_only: bool = False,
        channel: Optional[NotificationChannel] = None,
        limit: int = 50
    ) -> List[Notification]:
        """List notifications with optional filters."""
        async with get_session() as session:
            query = select(NotificationModel)

            if unread_only:
                query = query.where(NotificationModel.read == False)  # noqa: E712
            if channel:
                query = query.where(
                    NotificationModel.channel == (channel.value if hasattr(channel, 'value') else channel)
                )

            query = query.order_by(NotificationModel.created_at.desc()).limit(limit)

            result = await session.execute(query)
            rows = result.scalars().all()

            return [self._orm_to_notification(row) for row in rows]

    async def mark_as_read(self, notification_id: str) -> Optional[Notification]:
        """Mark a notification as read."""
        async with get_session() as session:
            row = await session.get(NotificationModel, notification_id)
            if row is None:
                return None

            row.read = True
            await session.flush()

            return self._orm_to_notification(row)

    async def mark_all_as_read(self) -> int:
        """Mark all notifications as read. Returns count of marked notifications."""
        async with get_session() as session:
            # Count unread first
            count_result = await session.execute(
                select(sa_func.count()).select_from(NotificationModel).where(
                    NotificationModel.read == False  # noqa: E712
                )
            )
            count = count_result.scalar_one()

            if count > 0:
                stmt = (
                    update(NotificationModel)
                    .where(NotificationModel.read == False)  # noqa: E712
                    .values(read=True)
                )
                await session.execute(stmt)

            logger.info("notifications_marked_read", count=count)

        return count

    async def delete_notification(self, notification_id: str) -> bool:
        """Delete a notification."""
        async with get_session() as session:
            row = await session.get(NotificationModel, notification_id)
            if row is None:
                return False

            await session.delete(row)

        return True

    async def clear_all(self) -> int:
        """Clear all notifications. Returns count of deleted notifications."""
        async with get_session() as session:
            count_result = await session.execute(
                select(sa_func.count()).select_from(NotificationModel)
            )
            count = count_result.scalar_one()

            if count > 0:
                all_result = await session.execute(select(NotificationModel))
                for row in all_result.scalars().all():
                    await session.delete(row)

        return count

    async def get_unread_count(self) -> int:
        """Get count of unread notifications."""
        async with get_session() as session:
            result = await session.execute(
                select(sa_func.count()).select_from(NotificationModel).where(
                    NotificationModel.read == False  # noqa: E712
                )
            )
            return result.scalar_one()

    async def notify_reminder(self, reminder) -> Notification:
        """Create notification for a triggered reminder."""
        return await self.create_notification(
            title=f"Reminder: {reminder.title}",
            message=reminder.description or "Time for your reminder!",
            channel=reminder.channels[0] if reminder.channels else NotificationChannel.UI,
            source="reminder",
            source_id=reminder.id
        )

    async def notify_email(self, subject: str, from_email: str, email_id: str) -> Notification:
        """Create notification for an important email."""
        return await self.create_notification(
            title="New Email",
            message=f"From {from_email}: {subject}",
            channel=NotificationChannel.UI,
            source="email",
            source_id=email_id,
            action_url=f"/email/{email_id}"
        )

    async def notify_task(self, task_title: str, message: str, task_id: str) -> Notification:
        """Create notification for a task event."""
        return await self.create_notification(
            title="Task Update",
            message=f"{task_title}: {message}",
            channel=NotificationChannel.UI,
            source="task",
            source_id=task_id,
            action_url=f"/tasks/{task_id}"
        )

    # ==========================================================================
    # Utility Methods
    # ==========================================================================

    @staticmethod
    def _orm_to_notification(row: NotificationModel) -> Notification:
        """Convert a NotificationModel ORM object to a Notification Pydantic model."""
        return Notification(
            id=row.id,
            title=row.title,
            message=row.message,
            channel=row.channel,
            read=row.read,
            action_url=row.action_url,
            source=row.source,
            source_id=row.source_id,
            created_at=row.created_at,
        )


@lru_cache()
def get_notification_service() -> NotificationService:
    """Get singleton NotificationService instance."""
    return NotificationService()
