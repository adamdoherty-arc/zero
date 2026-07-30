"""Fix-158: primary-provider availability breaker in UnifiedLLMClient.

Context (measured 2026-07-30, supervise run 8cb0bc26): the shared vLLM lane runs
at max_num_seqs=1 behind Bifrost's only concurrency=1 lane, so one long generation
head-of-line-blocks every project. This client made it worse — each logical call
fired 3 primary attempts, and every attempt injected another request into the very
single-slot lane it was timing out on. Between 07:12 and 08:09 Zero logged ~60
consecutive LLM failures against 2 successes (23-126s latencies) while a direct
vLLM completion answered in 0.517s.

These tests pin the contract that stops the amplification:
  1. N consecutive TRANSIENT failures open the breaker.
  2. Once open, the primary is not called AT ALL — the fallback chain serves.
  3. A success closes it and restores normal retry behaviour.
  4. Non-transient (caller-error) failures never trip it.
  5. Tripping mid-loop abandons the remaining primary attempts.
"""

import asyncio

import httpx
import pytest

from app.infrastructure import unified_llm_client as ullm
from app.infrastructure.circuit_breaker import CircuitState, _registry
from app.infrastructure.unified_llm_client import UnifiedLLMClient


@pytest.fixture(autouse=True)
def _clean_breaker_registry():
    """Breakers are process-singletons; isolate each test."""
    _registry.clear()
    yield
    _registry.clear()


def _client() -> UnifiedLLMClient:
    return UnifiedLLMClient()


async def _drive(client, *, calls, fallbacks=(), provider="bifrost"):
    """Run _execute_with_fallbacks with _call_provider stubbed by `calls`."""
    return await client._execute_with_fallbacks(
        provider_name=provider,
        model_name="qwen3-chat",
        fallbacks=list(fallbacks),
        messages=[{"role": "user", "content": "hi"}],
        task_type="test",
        temperature=0.0,
        max_tokens=8,
    )


@pytest.mark.asyncio
async def test_transient_failures_open_breaker_then_primary_is_skipped(monkeypatch):
    """The core anti-amplification contract: an open breaker means ZERO primary calls."""
    monkeypatch.setattr(ullm, "_LLM_BREAKER_THRESHOLD", 5)
    monkeypatch.setattr(ullm, "_LLM_BREAKER_RECOVERY_S", 60.0)

    primary_calls = 0
    fallback_calls = 0

    async def fake_call_provider(provider, model, *a, **kw):
        nonlocal primary_calls, fallback_calls
        if provider == "bifrost":
            primary_calls += 1
            raise httpx.ReadTimeout("")
        fallback_calls += 1
        return "from-fallback"

    client = _client()
    monkeypatch.setattr(client, "_call_provider", fake_call_provider)

    # Two logical calls at 3 attempts each = 6 transient failures >= threshold 5.
    for _ in range(2):
        out = await _drive(client, calls=None, fallbacks=[("groq", "gpt-oss-120b")])
        assert out == "from-fallback"

    breaker = ullm._primary_breaker("bifrost")
    assert breaker.state == CircuitState.OPEN, breaker.status()

    calls_before = primary_calls
    fb_before = fallback_calls

    # Third call: primary must be skipped ENTIRELY, fallback still serves.
    out = await _drive(client, calls=None, fallbacks=[("groq", "gpt-oss-120b")])
    assert out == "from-fallback"
    assert primary_calls == calls_before, (
        f"primary was called {primary_calls - calls_before}x while breaker OPEN; "
        "the whole point is to stop loading a stalled lane"
    )
    assert fallback_calls == fb_before + 1


@pytest.mark.asyncio
async def test_breaker_trip_abandons_remaining_primary_attempts(monkeypatch):
    """Threshold 2 => the 3-attempt loop must stop at attempt 2, not run all 3."""
    monkeypatch.setattr(ullm, "_LLM_BREAKER_THRESHOLD", 2)
    monkeypatch.setattr(ullm, "_LLM_BREAKER_RECOVERY_S", 60.0)

    primary_calls = 0

    async def fake_call_provider(provider, model, *a, **kw):
        nonlocal primary_calls
        if provider == "bifrost":
            primary_calls += 1
            raise httpx.ConnectTimeout("")
        return "fb"

    client = _client()
    monkeypatch.setattr(client, "_call_provider", fake_call_provider)

    await _drive(client, calls=None, fallbacks=[("groq", "m")])

    assert primary_calls == 2, (
        f"expected the loop to abandon after tripping at 2 failures, got {primary_calls}"
    )
    assert ullm._primary_breaker("bifrost").state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_success_resets_consecutive_failures(monkeypatch):
    """A success must clear the streak so a flaky-but-alive gateway stays primary."""
    monkeypatch.setattr(ullm, "_LLM_BREAKER_THRESHOLD", 5)

    seq = [httpx.ReadTimeout(""), httpx.ReadTimeout(""), "ok"]

    async def fake_call_provider(provider, model, *a, **kw):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client = _client()
    monkeypatch.setattr(client, "_call_provider", fake_call_provider)

    out = await _drive(client, calls=None)
    assert out == "ok"

    breaker = ullm._primary_breaker("bifrost")
    assert breaker.state == CircuitState.CLOSED
    assert breaker.stats.consecutive_failures == 0


@pytest.mark.asyncio
async def test_non_transient_failure_does_not_trip_breaker(monkeypatch):
    """A caller's own bad request must not fail over every other call."""
    monkeypatch.setattr(ullm, "_LLM_BREAKER_THRESHOLD", 2)

    async def fake_call_provider(provider, model, *a, **kw):
        if provider == "bifrost":
            raise ValueError("invalid request payload")  # not transport, not 5xx
        return "fb"

    client = _client()
    monkeypatch.setattr(client, "_call_provider", fake_call_provider)

    for _ in range(4):
        await _drive(client, calls=None, fallbacks=[("groq", "m")])

    breaker = ullm._primary_breaker("bifrost")
    assert breaker.state == CircuitState.CLOSED, (
        "client-side errors tripped the shared breaker: one buggy caller would "
        "now divert every other call to fallbacks"
    )


@pytest.mark.asyncio
async def test_half_open_spends_exactly_one_probe(monkeypatch):
    """After recovery_timeout, HALF_OPEN probes with 1 attempt — not 3."""
    monkeypatch.setattr(ullm, "_LLM_BREAKER_THRESHOLD", 2)
    monkeypatch.setattr(ullm, "_LLM_BREAKER_RECOVERY_S", 0.05)

    primary_calls = 0

    async def fake_call_provider(provider, model, *a, **kw):
        nonlocal primary_calls
        if provider == "bifrost":
            primary_calls += 1
            raise httpx.ReadTimeout("")
        return "fb"

    client = _client()
    monkeypatch.setattr(client, "_call_provider", fake_call_provider)

    await _drive(client, calls=None, fallbacks=[("groq", "m")])
    assert ullm._primary_breaker("bifrost").state == CircuitState.OPEN
    calls_after_trip = primary_calls

    await asyncio.sleep(0.08)  # let OPEN -> HALF_OPEN elapse

    await _drive(client, calls=None, fallbacks=[("groq", "m")])
    assert primary_calls == calls_after_trip + 1, (
        f"HALF_OPEN spent {primary_calls - calls_after_trip} attempts; expected 1 probe"
    )
    # Failed probe must reopen, not stay half-open.
    assert ullm._primary_breaker("bifrost").state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_breaker_open_reports_real_reason_when_everything_fails(monkeypatch):
    """No 'Last error: None' — the record must show the primary was never tried."""
    monkeypatch.setattr(ullm, "_LLM_BREAKER_THRESHOLD", 1)

    async def fake_call_provider(provider, model, *a, **kw):
        raise httpx.ReadTimeout("")

    client = _client()
    monkeypatch.setattr(client, "_call_provider", fake_call_provider)

    # threshold=1 and no fallback chain, so this first call also raises; it exists
    # only to trip the breaker.
    with pytest.raises(Exception):
        await _drive(client, calls=None)
    assert ullm._primary_breaker("bifrost").state == CircuitState.OPEN

    with pytest.raises(Exception) as exc:
        await _drive(client, calls=None)

    assert "None" not in str(exc.value), str(exc.value)
    assert "llm_primary:bifrost" in str(exc.value), str(exc.value)
