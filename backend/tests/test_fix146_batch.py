"""Fix-146 — regression tests for the resumed Fix-145 batch (runs ed70fd7f → ffb7c729).

The Fix-145 executor died in flight (sprint 12428 watchdog-cancelled with 0
tasks); its edits were recovered from the working tree, orchestrator-verified,
and shipped here as Fix-146. Covered surfaces:

- A7: tiktok_api_client / ai_content_tools_client previously called
  CircuitBreaker methods that DO NOT EXIST (allow_request / record_success /
  record_failure) → AttributeError on every real call; both integrations were
  dead-on-use. Now routed through ``breaker.call()``.
- Per-client 4xx breaker semantics (Fix-144 pattern): vllm / notion / gmail
  each exempt CLIENT-side errors from tripping their shared breaker while
  429/5xx/connection failures still count.
- Gmail reauth cache eviction (invalidate_cached_service).
- workflow_engine F4 (step-failure dicts no longer report "completed") and
  F6 (unresolved {{ }} conditions fail CLOSED, not truthy-open).
- character_research_sources: one uncaught source exception no longer aborts
  every other source's results.
"""

import pytest
import aiohttp
import httpx

from app.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerError,
)


# ---------------------------------------------------------------------------
# Fakes for the aiohttp-based clients
# ---------------------------------------------------------------------------

class _FakeReqInfo:
    """aiohttp.ClientResponseError.__str__ dereferences request_info.real_url."""

    real_url = "http://fake.test/x"


class FakeResp:
    def __init__(self, status, json_data=None, text_data=""):
        self.status = status
        self._json = json_data if json_data is not None else {}
        self._text = text_data
        self.request_info = _FakeReqInfo()
        self.history = ()

    async def json(self):
        return self._json

    async def text(self):
        return self._text


class _FakeCM:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Returns the queued responses in order; repeats the last one."""

    def __init__(self, resps):
        self._resps = list(resps)
        self.calls = 0

    def request(self, method, url, **kwargs):
        resp = self._resps[min(self.calls, len(self._resps) - 1)]
        self.calls += 1
        return _FakeCM(resp)


async def _true():
    return True


# ---------------------------------------------------------------------------
# A7 — TikTokApiClient breaker call-path
# ---------------------------------------------------------------------------

def _tiktok_client(resps, breaker):
    from app.infrastructure.tiktok_api_client import TikTokApiClient

    client = TikTokApiClient()
    client._breaker = breaker
    client._access_token = "tok"
    session = FakeSession(resps)

    async def _get_session():
        return session

    client._get_session = _get_session
    client._ensure_valid_token = _true
    return client, session


async def test_tiktok_request_success_via_breaker_call():
    cb = CircuitBreaker("t146_tiktok_ok", failure_threshold=3)
    client, session = _tiktok_client([FakeResp(200, {"data": {"id": "v1"}})], cb)
    result = await client._api_request("GET", "/x/")
    assert result == {"data": {"id": "v1"}}
    assert session.calls == 1
    assert cb.state == CircuitState.CLOSED
    assert cb.stats.total_failures == 0


async def test_tiktok_4xx_returns_error_dict_and_does_not_trip_breaker():
    cb = CircuitBreaker("t146_tiktok_4xx", failure_threshold=2)
    client, session = _tiktok_client([FakeResp(400, text_data="bad payload")], cb)
    result = await client._api_request("POST", "/x/")
    assert result == {"error": "bad payload", "status": 400}
    # A 4xx is the caller's fault — recorded as breaker SUCCESS, never opens.
    assert cb.state == CircuitState.CLOSED
    assert cb.stats.total_failures == 0
    assert session.calls == 1


async def test_tiktok_5xx_counts_failures_and_retries_then_none():
    cb = CircuitBreaker("t146_tiktok_5xx", failure_threshold=5)
    client, session = _tiktok_client([FakeResp(500, text_data="boom")], cb)
    result = await client._api_request("GET", "/x/")
    assert result is None
    assert session.calls == 3  # one breaker.call per attempt
    assert cb.stats.total_failures == 3


async def test_tiktok_open_breaker_short_circuits_to_none():
    cb = CircuitBreaker("t146_tiktok_open", failure_threshold=1, recovery_timeout=300.0)

    async def _boom():
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        await cb.call(_boom)
    assert cb.state == CircuitState.OPEN

    client, session = _tiktok_client([FakeResp(200, {"ok": 1})], cb)
    result = await client._api_request("GET", "/x/")
    assert result is None
    assert session.calls == 0  # never reached the network


async def test_tiktok_401_reauth_then_retry_succeeds():
    cb = CircuitBreaker("t146_tiktok_401", failure_threshold=3)
    client, session = _tiktok_client([FakeResp(401), FakeResp(200, {"ok": True})], cb)

    async def _refresh():
        client._access_token = "fresh"
        return True

    client.refresh_access_token = _refresh
    result = await client._api_request("GET", "/x/")
    assert result == {"ok": True}
    assert session.calls == 2
    assert client._access_token == "fresh"


# ---------------------------------------------------------------------------
# A7 — AIContentToolsClient breaker call-path
# ---------------------------------------------------------------------------

def _act_client(resps, breaker):
    from app.services.ai_content_tools_client import AIContentToolsClient

    client = AIContentToolsClient()
    client._breaker = breaker
    session = FakeSession(resps)

    async def _get_session():
        return session

    client._get_session = _get_session
    return client, session


async def test_act_success_and_4xx_do_not_trip_breaker():
    cb = CircuitBreaker("t146_act_ok", failure_threshold=2)
    client, session = _act_client([FakeResp(200, {"a": 1}), FakeResp(400, text_data="x")], cb)
    assert await client._request("GET", "/t") == {"a": 1}
    assert await client._request("GET", "/t") is None  # 4xx → None, not counted
    assert cb.state == CircuitState.CLOSED
    assert cb.stats.total_failures == 0
    assert session.calls == 2


async def test_act_open_breaker_returns_none():
    cb = CircuitBreaker("t146_act_open", failure_threshold=1, recovery_timeout=300.0)

    async def _boom():
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        await cb.call(_boom)

    client, session = _act_client([FakeResp(200, {"a": 1})], cb)
    assert await client._request("GET", "/t") is None
    assert session.calls == 0


# ---------------------------------------------------------------------------
# F6 — evaluate_condition fails CLOSED on unresolved templates
# ---------------------------------------------------------------------------

def test_condition_unresolved_template_fails_closed():
    from app.services.workflow_engine import evaluate_condition

    # steps.x is a plain string → the ".output.y" path can't resolve and the
    # {{ }} stays verbatim. Before F6, bool("{{ steps.x.output.y }}") == True
    # meant the gated step RAN on a condition that never evaluated.
    context = {"steps": {"x": "notadict"}}
    assert evaluate_condition("{{ steps.x.output.y }}", context) is False


def test_condition_resolved_values_still_work():
    from app.services.workflow_engine import evaluate_condition

    context = {"steps": {"a": {"output": {"ok": "yes", "n": "5"}}}}
    assert evaluate_condition("{{ steps.a.output.ok }}", context) is True
    assert evaluate_condition("{{ steps.a.output.n }} > 3", context) is True
    assert evaluate_condition("{{ steps.a.output.n }} > 9", context) is False


# ---------------------------------------------------------------------------
# F4 — workflow no longer reports "completed" when steps failed
# ---------------------------------------------------------------------------

class StubStateManager:
    def __init__(self):
        self.completed = []

    def save_state(self, execution_id, state):
        pass

    def complete_execution(self, execution_id, state):
        self.completed.append((execution_id, dict(state)))


def _wf(steps):
    from app.services.workflow_engine import WorkflowDefinition

    return WorkflowDefinition({"name": "t146", "steps": steps})


async def test_workflow_failed_step_dict_fails_execution():
    from app.services.workflow_engine import DAGExecutor

    executor = DAGExecutor(state_manager=StubStateManager())

    async def _failed_step(step_def, context, state):
        return {"output": None, "status": "failed", "error": "handler boom"}

    executor._execute_step = _failed_step
    state = await executor.execute_workflow(_wf([{"id": "s1", "type": "http"}]))
    assert state["status"] == "failed"
    assert "s1" in state["error"]
    assert state["steps"]["s1"]["status"] == "failed"


async def test_workflow_on_error_continue_still_completes():
    from app.services.workflow_engine import DAGExecutor

    executor = DAGExecutor(state_manager=StubStateManager())

    async def _failed_step(step_def, context, state):
        return {"output": None, "status": "failed", "error": "handler boom"}

    executor._execute_step = _failed_step
    state = await executor.execute_workflow(
        _wf([{"id": "s1", "type": "http", "on_error": "continue"}])
    )
    assert state["status"] == "completed"


# ---------------------------------------------------------------------------
# Per-client 4xx semantics — vLLM
# ---------------------------------------------------------------------------

async def test_vllm_client_error_is_exempt_and_carries_httpx_attrs():
    from app.infrastructure.llm_providers.vllm_provider import (
        VllmProvider,
        VLLMClientError,
    )

    provider = VllmProvider()
    assert VLLMClientError in provider._breaker.ignore_exceptions

    req = httpx.Request("POST", "http://vllm/v1/chat/completions")
    resp = httpx.Response(400, request=req)
    err = VLLMClientError("400 bad request", response=resp, request=req)
    assert err.response is resp
    assert err.request is req

    cb = CircuitBreaker("t146_vllm", failure_threshold=2, ignore_exceptions=(VLLMClientError,))

    async def _bad_request():
        raise err

    for _ in range(5):
        with pytest.raises(VLLMClientError):
            await cb.call(_bad_request)
    assert cb.state == CircuitState.CLOSED
    assert cb.stats.total_failures == 0


# ---------------------------------------------------------------------------
# Per-client 4xx semantics — Notion
# ---------------------------------------------------------------------------

def _notion_error(status_code, code="object_not_found"):
    from notion_client.errors import APIResponseError

    return APIResponseError(code, status_code, "err", httpx.Headers(), "")


async def test_notion_4xx_converted_and_not_counted():
    from app.services.notion_service import NotionService, NotionClientError

    svc = NotionService(api_key="secret_test")
    svc._breaker = CircuitBreaker(
        "t146_notion", failure_threshold=3, ignore_exceptions=(NotionClientError,)
    )

    async def _stale_page():
        raise _notion_error(404)

    for _ in range(5):
        with pytest.raises(NotionClientError):
            await svc._breaker_call(_stale_page)
    assert svc._breaker.state == CircuitState.CLOSED
    assert svc._breaker.stats.total_failures == 0


async def test_notion_429_still_counts():
    from app.services.notion_service import NotionService, NotionClientError
    from notion_client.errors import APIResponseError

    svc = NotionService(api_key="secret_test")
    svc._breaker = CircuitBreaker(
        "t146_notion_429", failure_threshold=3, ignore_exceptions=(NotionClientError,)
    )

    async def _rate_limited():
        raise _notion_error(429, code="rate_limited")

    with pytest.raises(APIResponseError):
        await svc._breaker_call(_rate_limited)
    assert svc._breaker.stats.consecutive_failures == 1


# ---------------------------------------------------------------------------
# Per-client 4xx semantics + cache eviction — Gmail
# ---------------------------------------------------------------------------

def _gmail_http_error(status):
    import httplib2
    from googleapiclient.errors import HttpError

    return HttpError(httplib2.Response({"status": str(status)}), b"err")


def _gmail_service(tmp_path):
    from app.services.gmail_service import GmailService

    return GmailService(workspace_path=str(tmp_path / "ws"))


async def test_gmail_stale_id_404_exempt_from_breaker(tmp_path):
    from app.services.gmail_service import GmailStaleIdError

    svc = _gmail_service(tmp_path)
    svc._breaker = CircuitBreaker(
        "t146_gmail_404", failure_threshold=3, ignore_exceptions=(GmailStaleIdError,)
    )

    async def _stale():
        raise _gmail_http_error(404)

    for _ in range(5):
        with pytest.raises(GmailStaleIdError):
            await svc._breaker_call(_stale)
    assert svc._breaker.state == CircuitState.CLOSED
    assert svc._breaker.stats.total_failures == 0


async def test_gmail_401_still_counts(tmp_path):
    from googleapiclient.errors import HttpError

    svc = _gmail_service(tmp_path)
    svc._breaker = CircuitBreaker("t146_gmail_401", failure_threshold=3)

    async def _expired():
        raise _gmail_http_error(401)

    with pytest.raises(HttpError):
        await svc._breaker_call(_expired)
    assert svc._breaker.stats.consecutive_failures == 1


def test_gmail_invalidate_cached_service(tmp_path):
    svc = _gmail_service(tmp_path)
    svc._services = {"acct1": object(), "_default": object(), "acct2": object()}
    svc.invalidate_cached_service("acct1")
    assert set(svc._services) == {"acct2"}  # acct1 AND _default evicted

    svc._services = {"acct1": object(), "acct2": object()}
    svc.invalidate_cached_service(None)
    assert svc._services == {}


# ---------------------------------------------------------------------------
# character_research_sources — one bad source no longer aborts the batch
# ---------------------------------------------------------------------------

async def test_research_all_isolates_uncaught_source_exception():
    from app.services.character_research_sources import (
        CharacterResearchSources,
        ResearchFragment,
    )

    svc = CharacterResearchSources()

    async def _check(*args):
        return False

    async def _boom(*args):
        # RuntimeError is NOT in _safe_research's except tuple — before the
        # fix, the bare asyncio.gather() re-raised it and every other
        # source's results were lost.
        raise RuntimeError("uncaught provider bug")

    async def _reddit(*args):
        return [ResearchFragment(source="reddit", content="Homelander detail")]

    async def _empty(*args):
        return []

    svc._check_firecrawl = _check
    svc.research_fandom_wiki = _boom
    svc.research_reddit = _reddit
    svc.research_tvtropes = _empty
    svc.research_imdb_trivia = _empty
    svc.research_quotes = _empty
    svc.research_entertainment_articles = _empty
    svc.research_wikipedia_deep = _empty
    svc.research_power_databases = _empty

    fragments = await svc.research_from_all_sources("Homelander", "the_boys", "The Boys")
    assert len(fragments) == 1
    assert fragments[0].source == "reddit"


async def test_safe_research_swallows_typeerror():
    from app.services.character_research_sources import CharacterResearchSources

    svc = CharacterResearchSources()

    async def _null_url(*args):
        raise TypeError("'NoneType' object is not subscriptable")

    assert await svc._safe_research(_null_url) == []
