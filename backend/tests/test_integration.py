"""
Integration and smoke tests for Zero API.
"""
import pytest


class TestHealthEndpoints:
    """Smoke tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "ZERO API"

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestSprintEndpoints:
    """Integration tests for sprint API endpoints."""

    @pytest.mark.asyncio
    async def test_list_sprints(self, client):
        response = await client.get("/api/sprints")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    @pytest.mark.asyncio
    async def test_sprint_stats(self, client):
        response = await client.get("/api/sprints/stats")
        # May return 200 or 404 depending on data -- just check it doesn't 500
        assert response.status_code in [200, 404]


class TestTaskEndpoints:
    """Integration tests for task API endpoints."""

    @pytest.mark.asyncio
    async def test_list_tasks(self, client):
        response = await client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))


class TestSystemEndpoints:
    """Integration tests for system endpoints."""

    @pytest.mark.asyncio
    async def test_system_status(self, client):
        response = await client.get("/api/system/status")
        # Accept 200 or 404 -- just ensure no 500
        assert response.status_code in [200, 404]
