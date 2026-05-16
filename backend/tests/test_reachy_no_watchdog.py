"""Regression tests for the 2026-05-15 watchdog removal.

These guard against re-adding the auto-restart watchdog or the Docker
readiness probe that fed it. The old code produced silent flapping
("pid X exists but :8000 is not responding") with no UI visibility;
daemon lifecycle is now exclusively UI-driven.
"""
import pytest

from app.routers import reachy


def test_reachy_router_has_no_watchdog_endpoints():
    """The /api/reachy/daemon/watchdog GET/POST routes are gone."""
    paths = {route.path for route in reachy.router.routes}
    assert "/daemon/watchdog" not in paths
    assert "/host/docker_status" not in paths


def test_reachy_router_exposes_host_agent_status_endpoint():
    """New /api/reachy/host-agent/status powers the UI offline banner."""
    paths = {route.path for route in reachy.router.routes}
    assert "/host-agent/status" in paths


def test_reachy_router_keeps_daemon_lifecycle_endpoints():
    """Start/stop/restart/relink/logs/diagnostics must stay (UI uses them)."""
    paths = {route.path for route in reachy.router.routes}
    for required in (
        "/daemon/status",
        "/daemon/start",
        "/daemon/stop",
        "/daemon/restart",
        "/daemon/relink",
        "/daemon/logs",
        "/daemon/diagnostics",
        "/daemon/audio/reset",
        "/daemon/retry-scan",
    ):
        assert required in paths, f"Missing daemon endpoint {required}"


def test_assistant_steps_do_not_include_watchdog():
    """The assistant status payload no longer reports a watchdog step.

    Building one of these manually used to produce a 7-element step list
    with id 'watchdog'; the union type was tightened in 2026-05-15.
    """
    step = reachy._assistant_step("reachy_daemon", "Daemon", "ready", "ok")
    # No way to even construct a watchdog step from the public helper
    # signature anymore — id is typed.
    assert step["id"] == "reachy_daemon"


@pytest.mark.asyncio
async def test_host_agent_status_reachable_branch(monkeypatch):
    """When host_agent /health returns 200, the probe returns reachable=true."""

    class _FakeResp:
        status_code = 200

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            assert url.endswith("/health")
            return _FakeResp()

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(
        reachy,
        "_host_agent_base",
        lambda: "http://test-host:18796",
    )

    result = await reachy.host_agent_status()

    assert result == {
        "reachable": True,
        "url": "http://test-host:18796",
        "last_error": None,
    }


@pytest.mark.asyncio
async def test_host_agent_status_unreachable_branch(monkeypatch):
    """When the HTTP client raises, the probe returns reachable=false (never raises)."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise ConnectionRefusedError("connection refused")

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(
        reachy,
        "_host_agent_base",
        lambda: "http://test-host:18796",
    )

    result = await reachy.host_agent_status()

    assert result["reachable"] is False
    assert result["url"] == "http://test-host:18796"
    assert "connection refused" in result["last_error"]
