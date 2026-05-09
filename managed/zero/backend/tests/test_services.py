import pytest
from unittest.mock import AsyncMock, patch
from zero.services import (
    CalendarService,
    EmailService,
    TaskService,
    NotificationService,
)
from zero.models import CalendarEvent, Email, Task, Notification

@pytest.fixture
def calendar_service():
    return CalendarService()

@pytest.fixture
def email_service():
    return EmailService()

@pytest.fixture
def task_service():
    return TaskService()

@pytest.fixture
def notification_service():
    return NotificationService()

class TestCalendarService:
    @pytest.mark.asyncio
    async def test_get_events(self, calendar_service):
        calendar_service.client = AsyncMock()
        calendar_service.client.get_events = AsyncMock(
            return_value=[
                CalendarEvent(title="Meeting", start="2023-10-01T10:00:00"),
            ]
        )
        events = await calendar_service.get_events()
        assert len(events) == 1
        assert events[0].title == "Meeting"

    @pytest.mark.asyncio
    async def test_create_event(self, calendar_service):
        calendar_service.client = AsyncMock()
        calendar_service.client.create_event = AsyncMock(
            return_value=CalendarEvent(title="New Event", start="2023-10-02T11:00:00")
        )
        event = await calendar_service.create_event(title="New Event", start="2023-10-02T11:00:00")
        assert event.title == "New Event"

class TestEmailService:
    @pytest.mark.asyncio
    async def test_get_emails(self, email_service):
        email_service.client = AsyncMock()
        email_service.client.get_emails = AsyncMock(
            return_value=[
                Email(subject="Hello", sender="user@example.com"),
            ]
        )
        emails = await email_service.get_emails()
        assert len(emails) == 1
        assert emails[0].subject == "Hello"

    @pytest.mark.asyncio
    async def test_send_email(self, email_service):
        email_service.client = AsyncMock()
        email_service.client.send_email = AsyncMock(return_value=True)
        result = await email_service.send_email(to="recipient@example.com", subject="Test", body="Body")
        assert result is True

class TestTaskService:
    @pytest.mark.asyncio
    async def test_get_tasks(self, task_service):
        task_service.client = AsyncMock()
        task_service.client.get_tasks = AsyncMock(
            return_value=[
                Task(title="Task 1", status="pending"),
            ]
        )
        tasks = await task_service.get_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Task 1"

    @pytest.mark.asyncio
    async def test_create_task(self, task_service):
        task_service.client = AsyncMock()
        task_service.client.create_task = AsyncMock(
            return_value=Task(title="New Task", status="pending")
        )
        task = await task_service.create_task(title="New Task")
        assert task.title == "New Task"

class TestNotificationService:
    @pytest.mark.asyncio
    async def test_get_notifications(self, notification_service):
        notification_service.client = AsyncMock()
        notification_service.client.get_notifications = AsyncMock(
            return_value=[
                Notification(message="Alert 1", type="info"),
            ]
        )
        notifications = await notification_service.get_notifications()
        assert len(notifications) == 1
        assert notifications[0].message == "Alert 1"

    @pytest.mark.asyncio
    async def test_send_notification(self, notification_service):
        notification_service.client = AsyncMock()
        notification_service.client.send_notification = AsyncMock(return_value=True)
        result = await notification_service.send_notification(message="Test", type="info")
        assert result is True