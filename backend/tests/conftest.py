"""
Shared test fixtures for Zero API tests.
"""
import os
import re
import sys
import asyncio
import pytest
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from unittest.mock import AsyncMock, patch, MagicMock

from httpx import AsyncClient, ASGITransport

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.infrastructure.config import Settings, get_settings

_TEST_DB_INITIALIZED = False


def _test_postgres_url() -> str:
    return os.getenv(
        "ZERO_TEST_POSTGRES_URL",
        "postgresql://zero:zero_dev@localhost:5434/zero_test",
    )


def _admin_postgres_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    db_name = parsed.path.strip("/") or "zero_test"
    if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
        raise ValueError(f"Unsafe test database name: {db_name!r}")
    admin = parsed._replace(path="/postgres", query="", fragment="")
    return urlunsplit(admin), db_name


def _ensure_test_database_exists(url: str) -> None:
    import psycopg

    admin_url, db_name = _admin_postgres_url(url)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (db_name,),
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{db_name}"')


async def _ensure_test_database(url: str) -> None:
    global _TEST_DB_INITIALIZED
    if _TEST_DB_INITIALIZED:
        return
    _ensure_test_database_exists(url)
    from app.infrastructure.database import init_database, create_tables
    import app.db.models  # noqa: F401 - register ORM models for tests

    await init_database(url)
    await create_tables()
    from app.db.models import ServiceConfigModel
    from app.infrastructure.database import get_session
    from app.services.content_production_control_service import (
        CONFIG_KEY,
        ContentProductionPolicy,
    )

    async with get_session() as session:
        row = await session.get(ServiceConfigModel, CONFIG_KEY)
        policy = ContentProductionPolicy(
            paused=False,
            reason="Content production is unpaused for the shared test client.",
            updated_by="pytest",
        )
        if row is None:
            session.add(ServiceConfigModel(service_name=CONFIG_KEY, config=policy.model_dump()))
        else:
            row.config = policy.model_dump()
    _TEST_DB_INITIALIZED = True


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
        postgres_url=_test_postgres_url(),
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
        await _ensure_test_database(override_settings.postgres_url)
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
