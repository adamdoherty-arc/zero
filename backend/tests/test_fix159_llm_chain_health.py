"""Fix-159: Zero's LLM chain was dead at all three tiers while readiness said green.

Context (measured 2026-07-31, supervise run 07935288): over the preceding 24h Zero
logged 622 failed LLM calls against 86 successes — an 87.8% failure rate, sustained
at ~16 rate-limit rejections per hour for more than a day — while
``GET /health/ready`` reported ``local_llm: "ok"`` throughout. Every tier of the
chain was down at once:

  1. primary   ``bifrost/vllm-local/qwen3-chat``      -> breaker OPEN (lane stalled)
  2. fallback  ``bifrost/groq/openai/gpt-oss-120b``   -> HTTP 429, every call
  3. emergency ``shared-freellmapi``                  -> HTTP 401, every call

and four separate defects kept it that way, each pinned by a test below:

  1. ``structured_chat`` retried the WHOLE provider chain on provider exhaustion.
     The retry exists to correct a model that returned prose instead of JSON; when
     no model answered at all there is nothing to correct, so the 3 attempts only
     tripled this call's contribution to the 429 that caused its own failure.
     488 of the 622 failures were those amplified 429s.
  2. ``BifrostProvider._message_content`` substituted the ``reasoning`` block for
     an empty ``content``. On a response truncated by the token budget
     (``finish_reason == "length"``) the reasoning is an unfinished internal
     monologue, so the user-visible reply became literally
     ``'The user says: "Reply with exactly: OK"...'``.
  3. ``is_freellm_available()`` returned True whenever a bearer token was *set*,
     never whether it *worked*. Zero's token had been rotated out of
     shared-freellmapi (Legion, ADA and shared-infra all carried the current key;
     Zero alone was stale) so the emergency tier 401'd on every call and reported
     itself available.
  4. The durable ``llm_usage.error_message`` was written from ``str(e)``, which is
     the EMPTY STRING for every httpx transport exception — 132 of the 622 failure
     rows recorded that a call failed but not how.
"""


import httpx
import pytest

from app.infrastructure import freellm_client as fl
from app.infrastructure import unified_llm_client as ullm
from app.infrastructure.circuit_breaker import CircuitState, _registry
from app.infrastructure.llm_providers.bifrost_provider import BifrostProvider
from app.infrastructure.unified_llm_client import (
    AllProvidersFailedError,
    UnifiedLLMClient,
)


@pytest.fixture(autouse=True)
def _clean_state():
    _registry.clear()
    fl._AUTH_REJECTED.update({"at": None, "status": None, "token_suffix": None})
    yield
    _registry.clear()
    fl._AUTH_REJECTED.update({"at": None, "status": None, "token_suffix": None})


# --------------------------------------------------------------------------
# 1. structured_chat must not re-traverse an exhausted chain
# --------------------------------------------------------------------------

async def test_structured_chat_does_not_retry_when_all_providers_failed(monkeypatch):
    """One chain traversal, not three, when nothing answered.

    This is the amplification fix: each extra pass re-hits the rate-limited
    fallback, so retrying makes the 429 that caused the failure worse.
    """
    calls = {"n": 0}

    async def _boom(*a, **kw):
        calls["n"] += 1
        raise AllProvidersFailedError("All LLM providers failed. Last error: HTTP 429")

    client = UnifiedLLMClient()
    monkeypatch.setattr(client, "chat", _boom)

    with pytest.raises(ullm.StructuredOutputError):
        await client.structured_chat("extract something", max_retries=2)

    assert calls["n"] == 1, (
        f"expected exactly 1 chain traversal, got {calls['n']} — "
        "provider exhaustion is being retried again"
    )


async def test_structured_chat_still_retries_invalid_json(monkeypatch):
    """The corrective-prompt retry must survive: it fixes a real failure mode."""
    calls = {"n": 0}

    async def _prose_then_json(*a, **kw):
        calls["n"] += 1
        return "here you go!" if calls["n"] == 1 else '{"ok": true}'

    client = UnifiedLLMClient()
    monkeypatch.setattr(client, "chat", _prose_then_json)

    result = await client.structured_chat("extract something", max_retries=2)
    assert result == {"ok": True}
    assert calls["n"] == 2, "invalid-JSON retry must still fire"


# --------------------------------------------------------------------------
# 2. reasoning is not an answer when the response was truncated
# --------------------------------------------------------------------------

def test_truncated_response_does_not_leak_reasoning_as_answer():
    """finish_reason=length + empty content -> raise, never return the monologue.

    Verbatim shape of the live groq/openai/gpt-oss-120b response at max_tokens=8.
    """
    message = {
        "content": "",
        "reasoning": 'The user asks: "Reply with exactly: OK". Must respond',
    }
    with pytest.raises(RuntimeError, match="truncated"):
        BifrostProvider._message_content(message, "length")


def test_completed_reasoning_model_still_answers_from_reasoning():
    """Qwen3-thinking / Kimi put the ANSWER in reasoning and finish with stop."""
    message = {"content": "", "reasoning_content": "42"}
    assert BifrostProvider._message_content(message, "stop") == "42"


def test_content_always_wins_over_reasoning():
    message = {"content": "OK", "reasoning": "The user says: ..."}
    assert BifrostProvider._message_content(message, "stop") == "OK"
    # ...even on a truncated response: a partial answer beats no answer.
    assert BifrostProvider._message_content(message, "length") == "OK"


def test_missing_finish_reason_keeps_legacy_behaviour():
    """Absent finish_reason must not newly break callers that never sent one."""
    message = {"content": "", "reasoning": "answer here"}
    assert BifrostProvider._message_content(message) == "answer here"


def test_all_three_extraction_paths_guard_truncation():
    """The reasoning-for-content substitution exists in three separate files.

    Fixing one and leaving the others is how this class of defect has kept
    resurfacing (str(e) survived in four places across three runs). Pin all
    three at the source so a future edit to one is visibly incomplete.
    """
    import inspect

    from app.infrastructure.llm_providers import vllm_provider

    sources = {
        "bifrost_provider": inspect.getsource(BifrostProvider._message_content),
        "vllm_provider": inspect.getsource(vllm_provider.VllmProvider.chat),
        "freellm_client": inspect.getsource(fl.FreeLLMAPIClient.generate),
    }
    for name, src in sources.items():
        assert "finish_reason" in src, (
            f"{name} substitutes reasoning for empty content without checking "
            "finish_reason — a truncated response will leak the model's "
            "internal monologue as the answer"
        )
        assert '"length"' in src or "'length'" in src, (
            f"{name} reads finish_reason but does not test for 'length'"
        )


# --------------------------------------------------------------------------
# 3. a configured credential is not a working credential
# --------------------------------------------------------------------------

def test_freellm_available_requires_more_than_a_token(monkeypatch):
    monkeypatch.setenv("ZERO_FREELLM_BEARER_TOKEN", "freellmapi-whatever")
    assert fl.is_freellm_available() is True

    fl.note_auth_rejected(401, "freellmapi-whatever")

    assert fl.is_freellm_available() is False, (
        "a 401'd tier must not keep reporting itself available — that is what "
        "kept the emergency tier dead and silent"
    )
    assert fl.freellm_auth_state()["status"] == 401


def test_freellm_auth_latch_logs_once(monkeypatch):
    monkeypatch.setenv("ZERO_FREELLM_BEARER_TOKEN", "freellmapi-abc123")
    fl.note_auth_rejected(401, "freellmapi-abc123")
    first = fl.freellm_auth_state()["at"]
    fl.note_auth_rejected(403, "freellmapi-abc123")
    assert fl.freellm_auth_state()["at"] == first, "latch must not re-arm"
    assert fl.freellm_auth_state()["status"] == 401, "first verdict is retained"


# --------------------------------------------------------------------------
# 4. the durable record must carry the exception TYPE
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("", request=None),
        httpx.ConnectTimeout("", request=None),
        httpx.PoolTimeout("", request=None),
        httpx.ConnectError("", request=None),
        httpx.RemoteProtocolError("", request=None),
    ],
)
def test_transport_exceptions_stringify_empty_but_describe_nonempty(exc):
    """The premise of the bug, pinned so it cannot be re-introduced."""
    assert str(exc) == "", "premise changed — httpx now carries a message"
    described = ullm._describe_exc(exc)
    assert described == type(exc).__name__
    assert described.strip(), "durable error text must never be empty"


async def test_record_usage_persists_exception_type_not_empty_string(monkeypatch):
    """The failing DB write path records `ReadTimeout`, not ``''``.

    Asserted at the source level: this is the exact substitution whose absence
    left 132 rows unreadable, and a green unit test on the log line did not
    cover it (2026-07-30 lesson — the log and the row are different code paths).
    """
    import inspect

    src = inspect.getsource(ullm.UnifiedLLMClient._call_provider)
    assert "error_msg = _describe_exc(e)" in src, (
        "the DURABLE llm_usage record is being written from str(e) again"
    )
    assert "error_msg = str(e)" not in src


# --------------------------------------------------------------------------
# 5. health probes must observe without mutating
# --------------------------------------------------------------------------

async def test_peek_state_does_not_transition_an_open_breaker():
    """A readiness probe must not consume the breaker's recovery slot."""
    from app.infrastructure.circuit_breaker import get_circuit_breaker

    br = get_circuit_breaker("llm_primary:probe-test", failure_threshold=1,
                             recovery_timeout=0.0)
    await br.record_failure()
    assert br.peek_state is CircuitState.OPEN
    # recovery_timeout=0 means `state` would immediately flip to HALF_OPEN...
    assert br.peek_state is CircuitState.OPEN, "peek_state must not transition"
    assert br.state is CircuitState.HALF_OPEN, "state still auto-transitions"


def test_primary_breaker_states_are_exposed_for_readiness():
    from app.infrastructure.circuit_breaker import get_circuit_breaker

    get_circuit_breaker("llm_primary:bifrost")
    get_circuit_breaker("searxng")  # non-LLM breaker must not leak in
    states = ullm.get_primary_breaker_states()
    assert "bifrost" in states
    assert "searxng" not in states
