import pytest
from unittest.mock import AsyncMock, patch
from backend.services.user_service import UserService
from backend.services.task_service import TaskService
from backend.models.user import User
from backend.models.task import Task

@pytest.fixture
def mock_db():
    return AsyncMock()

@pytest.fixture
def user_service(mock_db):
    return UserService(db=mock_db)

@pytest.fixture
def task_service(mock_db):
    return TaskService(db=mock_db)

class TestUserService:
    @pytest.mark.asyncio
    async def test_create_user(self, user_service, mock_db):
        user_service.db.execute = AsyncMock(return_value={"id": 1, "name": "Alice"})
        user = await user_service.create_user(name="Alice")
        assert user.name == "Alice"
        assert user.id == 1
        user_service.db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_user(self, user_service, mock_db):
        user_service.db.execute = AsyncMock(return_value={"id": 1, "name": "Bob"})
        user = await user_service.get_user(user_id=1)
        assert user.name == "Bob"
        assert user.id == 1

    @pytest.mark.asyncio
    async def test_delete_user(self, user_service, mock_db):
        user_service.db.execute = AsyncMock(return_value={"success": True})
        result = await user_service.delete_user(user_id=1)
        assert result is True

class TestTaskService:
    @pytest.mark.asyncio
    async def test_create_task(self, task_service, mock_db):
        task_service.db.execute = AsyncMock(return_value={"id": 1, "title": "Test Task"})
        task = await task_service.create_task(title="Test Task")
        assert task.title == "Test Task"
        assert task.id == 1

    @pytest.mark.asyncio
    async def test_get_tasks(self, task_service, mock_db):
        task_service.db.execute = AsyncMock(return_value=[{"id": 1, "title": "Task 1"}])
        tasks = await task_service.get_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Task 1"

    @pytest.mark.asyncio
    async def test_update_task(self, task_service, mock_db):
        task_service.db.execute = AsyncMock(return_value={"id": 1, "title": "Updated Task"})
        task = await task_service.update_task(task_id=1, title="Updated Task")
        assert task.title == "Updated Task"

    @pytest.mark.asyncio
    async def test_delete_task(self, task_service, mock_db):
        task_service.db.execute = AsyncMock(return_value={"success": True})
        result = await task_service.delete_task(task_id=1)
        assert result is True