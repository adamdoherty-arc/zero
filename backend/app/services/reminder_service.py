"""
Reminder service for ZERO.
Manages reminders with recurrence and notifications.
"""

import json
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime, timedelta
import structlog

from app.models.assistant import (
    Reminder, ReminderCreate, ReminderUpdate,
    ReminderStatus, ReminderRecurrence, NotificationChannel
)

logger = structlog.get_logger()


class ReminderService:
    """Service for managing reminders."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.assistant_path = self.workspace_path / "assistant"
        self.assistant_path.mkdir(parents=True, exist_ok=True)
        self.reminders_file = self.assistant_path / "reminders.json"
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure storage file exists."""
        if not self.reminders_file.exists():
            self.reminders_file.write_text(json.dumps({"reminders": []}))

    def _load_reminders(self) -> List[Dict[str, Any]]:
        """Load reminders from storage."""
        try:
            data = json.loads(self.reminders_file.read_text())
            return data.get("reminders", [])
        except Exception:
            return []

    def _save_reminders(self, reminders: List[Dict[str, Any]]):
        """Save reminders to storage."""
        self.reminders_file.write_text(json.dumps({"reminders": reminders}, indent=2, default=str))

    def _normalize_reminder(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize reminder data for serialization."""
        # Convert datetime strings back to datetime objects where needed
        if isinstance(data.get("trigger_at"), str):
            data["trigger_at"] = datetime.fromisoformat(data["trigger_at"].replace("Z", "+00:00"))
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if data.get("updated_at") and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
        if data.get("snooze_until") and isinstance(data["snooze_until"], str):
            data["snooze_until"] = datetime.fromisoformat(data["snooze_until"].replace("Z", "+00:00"))
        if data.get("last_triggered_at") and isinstance(data["last_triggered_at"], str):
            data["last_triggered_at"] = datetime.fromisoformat(data["last_triggered_at"].replace("Z", "+00:00"))
        return data

    async def create_reminder(self, data: ReminderCreate) -> Reminder:
        """Create a new reminder."""
        reminders = self._load_reminders()

        reminder = Reminder(
            id=str(uuid.uuid4()),
            title=data.title,
            description=data.description,
            trigger_at=data.trigger_at,
            recurrence=data.recurrence,
            cron_expression=data.cron_expression,
            channels=data.channels,
            task_id=data.task_id,
            project_id=data.project_id,
            tags=data.tags,
            created_at=datetime.utcnow()
        )

        reminders.append(reminder.model_dump())
        self._save_reminders(reminders)

        logger.info("reminder_created", id=reminder.id, title=reminder.title)
        return reminder

    async def get_reminder(self, reminder_id: str) -> Optional[Reminder]:
        """Get a reminder by ID."""
        reminders = self._load_reminders()
        for r in reminders:
            if r.get("id") == reminder_id:
                return Reminder(**self._normalize_reminder(r))
        return None

    async def update_reminder(self, reminder_id: str, updates: ReminderUpdate) -> Optional[Reminder]:
        """Update a reminder."""
        reminders = self._load_reminders()

        for i, r in enumerate(reminders):
            if r.get("id") == reminder_id:
                update_dict = updates.model_dump(exclude_unset=True)
                reminders[i].update(update_dict)
                reminders[i]["updated_at"] = datetime.utcnow().isoformat()
                self._save_reminders(reminders)
                logger.info("reminder_updated", id=reminder_id)
                return Reminder(**self._normalize_reminder(reminders[i]))

        return None

    async def delete_reminder(self, reminder_id: str) -> bool:
        """Delete a reminder."""
        reminders = self._load_reminders()
        original_len = len(reminders)
        reminders = [r for r in reminders if r.get("id") != reminder_id]

        if len(reminders) < original_len:
            self._save_reminders(reminders)
            logger.info("reminder_deleted", id=reminder_id)
            return True
        return False

    async def list_reminders(
        self,
        status: Optional[ReminderStatus] = None,
        limit: int = 50
    ) -> List[Reminder]:
        """List reminders with optional status filter."""
        reminders = self._load_reminders()

        if status:
            reminders = [r for r in reminders if r.get("status") == status.value]

        # Sort by trigger_at
        reminders.sort(key=lambda x: x.get("trigger_at", ""))

        return [Reminder(**self._normalize_reminder(r)) for r in reminders[:limit]]

    async def get_upcoming_reminders(self, hours: int = 24) -> List[Reminder]:
        """Get reminders due within the specified hours."""
        reminders = self._load_reminders()
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours)

        upcoming = []
        for r in reminders:
            if r.get("status") not in [ReminderStatus.ACTIVE.value, ReminderStatus.SNOOZED.value]:
                continue

            trigger_at = r.get("trigger_at")
            if isinstance(trigger_at, str):
                trigger_at = datetime.fromisoformat(trigger_at.replace("Z", "+00:00")).replace(tzinfo=None)

            # Check snooze
            snooze_until = r.get("snooze_until")
            if snooze_until:
                if isinstance(snooze_until, str):
                    snooze_until = datetime.fromisoformat(snooze_until.replace("Z", "+00:00")).replace(tzinfo=None)
                if snooze_until > now:
                    continue  # Still snoozed

            if now <= trigger_at <= cutoff:
                upcoming.append(Reminder(**self._normalize_reminder(r)))

        upcoming.sort(key=lambda x: x.trigger_at)
        return upcoming

    async def get_due_reminders(self) -> List[Reminder]:
        """Get reminders that are due now."""
        reminders = self._load_reminders()
        now = datetime.utcnow()

        due = []
        for r in reminders:
            if r.get("status") != ReminderStatus.ACTIVE.value:
                continue

            trigger_at = r.get("trigger_at")
            if isinstance(trigger_at, str):
                trigger_at = datetime.fromisoformat(trigger_at.replace("Z", "+00:00")).replace(tzinfo=None)

            # Check snooze
            snooze_until = r.get("snooze_until")
            if snooze_until:
                if isinstance(snooze_until, str):
                    snooze_until = datetime.fromisoformat(snooze_until.replace("Z", "+00:00")).replace(tzinfo=None)
                if snooze_until > now:
                    continue

            if trigger_at <= now:
                due.append(Reminder(**self._normalize_reminder(r)))

        return due

    async def snooze_reminder(self, reminder_id: str, minutes: int = 15) -> Optional[Reminder]:
        """Snooze a reminder for the specified minutes."""
        reminders = self._load_reminders()

        for i, r in enumerate(reminders):
            if r.get("id") == reminder_id:
                reminders[i]["status"] = ReminderStatus.SNOOZED.value
                reminders[i]["snooze_until"] = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()
                reminders[i]["updated_at"] = datetime.utcnow().isoformat()
                self._save_reminders(reminders)
                logger.info("reminder_snoozed", id=reminder_id, minutes=minutes)
                return Reminder(**self._normalize_reminder(reminders[i]))

        return None

    async def dismiss_reminder(self, reminder_id: str) -> Optional[Reminder]:
        """Dismiss a reminder."""
        return await self.update_reminder(
            reminder_id,
            ReminderUpdate(status=ReminderStatus.DISMISSED)
        )

    async def complete_reminder(self, reminder_id: str) -> Optional[Reminder]:
        """Mark a reminder as completed."""
        return await self.update_reminder(
            reminder_id,
            ReminderUpdate(status=ReminderStatus.COMPLETED)
        )

    async def trigger_reminder(self, reminder_id: str) -> Optional[Reminder]:
        """Mark a reminder as triggered and handle recurrence."""
        reminders = self._load_reminders()

        for i, r in enumerate(reminders):
            if r.get("id") == reminder_id:
                reminders[i]["last_triggered_at"] = datetime.utcnow().isoformat()

                recurrence = r.get("recurrence", ReminderRecurrence.ONCE.value)

                if recurrence == ReminderRecurrence.ONCE.value:
                    reminders[i]["status"] = ReminderStatus.TRIGGERED.value
                else:
                    # Calculate next trigger time based on recurrence
                    current_trigger = r.get("trigger_at")
                    if isinstance(current_trigger, str):
                        current_trigger = datetime.fromisoformat(current_trigger.replace("Z", "+00:00"))

                    if recurrence == ReminderRecurrence.DAILY.value:
                        next_trigger = current_trigger + timedelta(days=1)
                    elif recurrence == ReminderRecurrence.WEEKLY.value:
                        next_trigger = current_trigger + timedelta(weeks=1)
                    elif recurrence == ReminderRecurrence.MONTHLY.value:
                        # Add roughly a month
                        next_trigger = current_trigger + timedelta(days=30)
                    else:
                        # Keep as triggered for custom/unknown
                        reminders[i]["status"] = ReminderStatus.TRIGGERED.value
                        self._save_reminders(reminders)
                        return Reminder(**self._normalize_reminder(reminders[i]))

                    reminders[i]["trigger_at"] = next_trigger.isoformat()
                    reminders[i]["status"] = ReminderStatus.ACTIVE.value

                reminders[i]["updated_at"] = datetime.utcnow().isoformat()
                self._save_reminders(reminders)

                logger.info("reminder_triggered", id=reminder_id, recurrence=recurrence)
                return Reminder(**self._normalize_reminder(reminders[i]))

        return None

    async def get_stats(self) -> Dict[str, Any]:
        """Get reminder statistics."""
        reminders = self._load_reminders()

        by_status = {}
        for r in reminders:
            status = r.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1

        upcoming = await self.get_upcoming_reminders(24)

        return {
            "total": len(reminders),
            "by_status": by_status,
            "upcoming_24h": len(upcoming),
            "active": by_status.get(ReminderStatus.ACTIVE.value, 0)
        }


@lru_cache()
def get_reminder_service() -> ReminderService:
    """Get singleton ReminderService instance."""
    return ReminderService()
