import pytest
from unittest.mock import AsyncMock, MagicMock
from services.user_service import UserService
from services.task_service import TaskService
from models.user import User
from models.task import Task

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def user_service(mock_db):
    return UserService(db=mock_db)

@pytest.fixture
def task_service(mock_db):
    return TaskService(db=mock_db)

@pytest.mark.asyncio
async def test_create_user(user_service, mock_db):
    mock_db.users.insert_one = AsyncMock(return_value={"inserted_id": "123"})
    user_data = {"name": "Alice", "email": "alice@example.com"}
    result = await user_service.create_user(user_data)
    assert result["inserted_id"] == "123"
    mock_db.users.insert_one.assert_called_once()

@pytest.mark.asyncio
async def test_get_user(user_service, mock_db):
    mock_db.users.find_one = AsyncMock(return_value={"_id": "123", "name": "Alice", "email": "alice@example.com"})
    result = await user_service.get_user("123")
    assert result["name"] == "Alice"
    mock_db.users.find_one.assert_called_once()

@pytest.mark.asyncio
async def test_create_task(task_service, mock_db):
    mock_db.tasks.insert_one = AsyncMock(return_value={"inserted_id": "456"})
    task_data = {"title": "Test Task", "user_id": "123"}
    result = await task_service.create_task(task_data)
    assert result["inserted_id"] == "456"
    mock_db.tasks.insert_one.assert_called_once()

@pytest.mark.asyncio
async def test_get_tasks(task_service, mock_db):
    mock_db.tasks.find = AsyncMock(return_value=[{"_id": "456", "title": "Test Task", "user_id": "123"}])
    result = await task_service.get_tasks(user_id="123")
    assert len(result) == 1
    assert result[0]["title"] == "Test Task"
    mock_db.tasks.find.assert_called_once()
