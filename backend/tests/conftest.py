"""
Shared test fixtures for Zero API tests.
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from httpx import AsyncClient, ASGITransport

from app.infrastructure.config import Settings, get_settings


@pytest.fixture
def test_workspace(tmp_path):
    """Create a temporary workspace with required subdirectories."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for subdir in ["sprints", "email", "calendar", "knowledge", "research", "enhancement", "ecosystem"]:
        (workspace / subdir).mkdir()
    return str(workspace)


@pytest.fixture
def test_settings(test_workspace):
    """Settings override pointing to temporary workspace."""
    return Settings(
        workspace_dir=test_workspace,
        ollama_base_url="http://localhost:11434/v1",
        ollama_model="test-model",
        legion_api_url="http://localhost:8005",
    )


@pytest.fixture
def override_settings(test_settings):
    """Override get_settings to use test configuration."""
    from app.main import app

    def _override():
        return test_settings

    app.dependency_overrides[get_settings] = _override
    yield test_settings
    app.dependency_overrides.clear()


@pytest.fixture
async def client(override_settings):
    """Async HTTP client for testing FastAPI endpoints.

    Patches the lifespan startup checks and scheduler to avoid
    network calls and external dependency requirements during tests.
    The lifespan calls get_settings() directly (not via Depends), so we
    clear the lru_cache and patch it at the config module level.
    """
    from app.main import app
    import app.infrastructure.config as config_module

    # Clear the lru_cache so our patched version is used
    get_settings.cache_clear()

    # Patch at the source modules where the lifespan imports from
    with patch.object(config_module, "get_settings", return_value=override_settings), \
         patch("app.infrastructure.startup.run_startup_checks", new_callable=AsyncMock, return_value=True), \
         patch("app.services.scheduler_service.start_scheduler", new_callable=AsyncMock), \
         patch("app.services.scheduler_service.stop_scheduler", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Restore the lru_cache after tests
    get_settings.cache_clear()


@pytest.fixture
def sample_sprint_data():
    """Sample sprint data for testing."""
    return {
        "id": "test-sprint-001",
        "name": "Test Sprint",
        "status": "active",
        "tasks": [
            {"id": "t1", "title": "Task 1", "status": "pending"},
            {"id": "t2", "title": "Task 2", "status": "completed"},
        ]
    }


@pytest.fixture
def sample_email_data():
    """Sample email data for testing."""
    return {
        "id": "email-001",
        "subject": "URGENT: Server Down",
        "from_address": "ops@company.com",
        "snippet": "The production server is currently experiencing issues...",
        "labels": ["INBOX", "UNREAD"],
    }


@pytest.fixture
def sample_calendar_events():
    """Sample calendar events for free slot calculation testing."""
    return [
        {
            "id": "ev1",
            "summary": "Morning Standup",
            "start": {"dateTime": "2025-01-15T09:00:00"},
            "end": {"dateTime": "2025-01-15T09:30:00"},
            "is_all_day": False,
        },
        {
            "id": "ev2",
            "summary": "Lunch",
            "start": {"dateTime": "2025-01-15T12:00:00"},
            "end": {"dateTime": "2025-01-15T13:00:00"},
            "is_all_day": False,
        },
        {
            "id": "ev3",
            "summary": "Team Meeting",
            "start": {"dateTime": "2025-01-15T14:00:00"},
            "end": {"dateTime": "2025-01-15T15:00:00"},
            "is_all_day": False,
        },
    ]
