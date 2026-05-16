import pytest


@pytest.mark.asyncio
async def test_loops_health_is_public(client, monkeypatch):
    monkeypatch.setenv("ZERO_GATEWAY_TOKEN", "test-token")

    response = await client.get("/api/loops/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_loops_registry_stays_protected(client, monkeypatch):
    monkeypatch.setenv("ZERO_GATEWAY_TOKEN", "test-token")

    response = await client.get("/api/loops")

    assert response.status_code == 401
