"""Fix-140 — legion_client Legion-v2 route alignment + write-404 trust boundary.

Covers the live defect found by supervise run 1f1bf3ed (2026-07-11):
Legion v2 serves the sprints collection at ``/api/sprints/`` ONLY (the bare
path hard-404s, no redirect), while ``_do_request`` converted every 404 to
``None``. Net effect on the delegation surface:

- ``list_sprints`` -> 404 -> None -> ``None.get("sprints")`` AttributeError.
- ``create_sprint`` -> 404 -> silent None; callers (sprints router proxy,
  content/research/tiktok sprint auto-filers) recorded success with no row —
  the same failure-treated-as-success class as Fix-137 F1 / Fix-139 BUG-A.

Fix: trailing-slash canonical paths for the sprints collection, 404->None
kept for GET only, and POST/PATCH/DELETE 404s raise LegionAPIError without
retrying.
"""

import pytest

import aiohttp

from app.services.legion_client import (
    LegionAPIError,
    LegionClient,
    LegionConfig,
)


class _PassthroughBreaker:
    """Circuit breaker stand-in so tests never trip the shared 'legion' breaker."""

    async def call(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)


class _FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None, history=(), status=self.status, message="err"
            )

    async def json(self):
        return self._payload


class _FakeSession:
    """Records every request; returns the configured response each time."""

    def __init__(self, response):
        self._response = response
        self.calls = []
        self.closed = False

    def request(self, method, url, params=None, json=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json})
        resp = self._response

        class _Ctx:
            async def __aenter__(self):
                return resp

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _client_with(response):
    client = LegionClient(LegionConfig(retry_count=3, retry_delay_seconds=0.0))
    session = _FakeSession(response)
    client._session = session  # bypass _get_session
    client._circuit_breaker = _PassthroughBreaker()
    return client, session


# ---------------------------------------------------------------------------
# 404 semantics per verb
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_404_returns_none():
    client, session = _client_with(_FakeResponse(status=404))
    result = await client._get("/sprints/999999")
    assert result is None
    assert len(session.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["POST", "PATCH", "DELETE"])
async def test_write_404_raises_legion_api_error(verb):
    client, session = _client_with(_FakeResponse(status=404))
    method = {"POST": client._post, "PATCH": client._patch}.get(verb)
    with pytest.raises(LegionAPIError) as exc:
        if verb == "DELETE":
            await client._delete("/sprints/999999")
        else:
            await method("/sprints/999999", {"x": 1})
    assert "404" in str(exc.value)


@pytest.mark.asyncio
async def test_write_404_does_not_retry():
    """A 404 on a write is terminal — must not burn the 3-attempt retry loop."""
    client, session = _client_with(_FakeResponse(status=404))
    with pytest.raises(LegionAPIError):
        await client._post("/sprints", {"x": 1})
    assert len(session.calls) == 1


# ---------------------------------------------------------------------------
# Canonical trailing-slash paths (Legion v2 hard-404s the bare collection path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sprints_uses_trailing_slash():
    client, session = _client_with(_FakeResponse(status=200, payload=[]))
    await client.list_sprints(project_id=7, limit=5)
    assert session.calls[0]["url"].endswith("/api/sprints/")


@pytest.mark.asyncio
async def test_create_sprint_uses_trailing_slash_and_returns_payload():
    payload = {"id": 12345, "name": "Fix-140", "status": "planned"}
    client, session = _client_with(_FakeResponse(status=200, payload=payload))
    result = await client.create_sprint({"name": "Fix-140", "project_id": 7})
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["url"].endswith("/api/sprints/")
    assert result == payload


# ---------------------------------------------------------------------------
# list_sprints result-shape hardening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sprints_none_result_returns_empty_list(monkeypatch):
    """404/None from the transport must degrade to [], not AttributeError."""
    client, _ = _client_with(_FakeResponse(status=404))
    result = await client.list_sprints(project_id=7)
    assert result == []


@pytest.mark.asyncio
async def test_list_sprints_list_and_dict_shapes():
    rows = [{"id": 1}, {"id": 2}]
    client, _ = _client_with(_FakeResponse(status=200, payload=rows))
    assert await client.list_sprints() == rows

    client2, _ = _client_with(_FakeResponse(status=200, payload={"sprints": rows}))
    assert await client2.list_sprints() == rows

    client3, _ = _client_with(_FakeResponse(status=200, payload={"unexpected": True}))
    assert await client3.list_sprints() == []
