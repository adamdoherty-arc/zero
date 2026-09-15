from __future__ import annotations

import pytest


class _DummyTrace:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def update(self, **kwargs):
        return None


class _DummyTracer:
    def trace_generation(self, **kwargs):
        return _DummyTrace()


@pytest.mark.asyncio
async def test_chat_forwards_reasoning_flag_to_local_provider(monkeypatch):
    from app.infrastructure.unified_llm_client import UnifiedLLMClient

    client = UnifiedLLMClient()
    captured: dict[str, object] = {}

    async def fake_call_provider(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(client, "_call_provider", fake_call_provider)

    result = await client.chat(
        prompt="status",
        model="vllm/Qwen3.6-35B-A3B",
        max_tokens=96,
        reasoning=False,
    )

    assert result == "ok"
    assert captured["reasoning"] is False


def test_explicit_model_without_task_type_has_no_router_fallbacks(monkeypatch):
    from app.infrastructure.unified_llm_client import UnifiedLLMClient

    client = UnifiedLLMClient()
    provider, model, fallbacks = client._resolve(
        "bifrost/vllm-local/Qwen3-32B-AWQ",
        None,
    )

    assert provider == "bifrost"
    assert model == "vllm-local/Qwen3-32B-AWQ"
    assert fallbacks == []


def test_bifrost_provider_clamps_kimi_k2_temperature():
    from app.infrastructure.llm_providers.bifrost_provider import BifrostProvider

    provider = BifrostProvider.__new__(BifrostProvider)

    payload = provider._payload(
        [{"role": "user", "content": "hi"}],
        "moonshot/kimi-k2.6",
        temperature=0.3,
        max_tokens=128,
    )

    assert payload["temperature"] == 1.0


def test_bifrost_provider_clamps_kimi_k2_temperature_on_live_hf_router_id():
    """2026-09-15: Bifrost parked the `moonshot` provider — the live id is
    hf-router/moonshotai/Kimi-K2.6. The temperature clamp must still fire
    when a caller already passes the live id directly (not just the legacy
    moonshot/ alias covered by the test above)."""
    from app.infrastructure.llm_providers.bifrost_provider import BifrostProvider

    provider = BifrostProvider.__new__(BifrostProvider)

    payload = provider._payload(
        [{"role": "user", "content": "hi"}],
        "hf-router/moonshotai/Kimi-K2.6",
        temperature=0.3,
        max_tokens=128,
    )

    assert payload["temperature"] == 1.0


def test_bifrost_provider_translates_legacy_moonshot_alias_to_live_hf_router_id():
    """The legacy `moonshot/`/`kimi/` prefixes must resolve to the live
    hf-router id, not the dead moonshot provider — moonshot has no route
    left on the gateway at all as of the 2026-09-15 provider park."""
    from app.infrastructure.llm_providers.bifrost_provider import BifrostProvider

    provider = BifrostProvider.__new__(BifrostProvider)

    assert provider._resolve_model("moonshot/kimi-k2.6") == "hf-router/moonshotai/Kimi-K2.6"
    assert provider._resolve_model("kimi/kimi-k2.6") == "hf-router/moonshotai/Kimi-K2.6"
    assert provider._resolve_model("bifrost/moonshot/kimi-k2.6") == "hf-router/moonshotai/Kimi-K2.6"
    assert provider._resolve_model("minimax/MiniMax-M2.7") == "hf-router/MiniMaxAI/MiniMax-M2.7"
    assert provider._resolve_model("zai/glm-4.5-flash") == "nvidia-nim/nvidia/nemotron-3-super-120b-a12b"
    assert provider._resolve_model("gemini/gemini-3.1-flash") == "nvidia-nim/nvidia/nemotron-3.5-lightning-30b-a3b"


def test_bifrost_provider_disables_local_qwen_thinking_at_payload_root():
    from app.infrastructure.llm_providers.bifrost_provider import BifrostProvider

    provider = BifrostProvider.__new__(BifrostProvider)

    payload = provider._payload(
        [{"role": "user", "content": "hi"}],
        "vllm-local/Qwen3-32B-AWQ",
        temperature=0.3,
        max_tokens=128,
        reasoning=False,
    )

    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert "extra_params" not in payload


@pytest.mark.asyncio
async def test_call_provider_passes_reasoning_false_to_vllm(monkeypatch):
    import app.infrastructure.langfuse_client as langfuse_client
    from app.infrastructure.unified_llm_client import UnifiedLLMClient

    client = UnifiedLLMClient()
    captured: dict[str, object] = {}

    class FakeProvider:
        async def chat(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        def estimate_cost(self, prompt_tokens, completion_tokens, model):
            return 0.0

    monkeypatch.setattr(client, "_get_provider", lambda name: FakeProvider())
    monkeypatch.setattr(langfuse_client, "get_langfuse_tracer", lambda: _DummyTracer())
    monkeypatch.setattr(client, "_record_usage", lambda *args, **kwargs: None)

    result = await client._call_provider(
        "vllm",
        "Qwen3-32B-AWQ",
        [{"role": "user", "content": "hi"}],
        None,
        0.3,
        96,
        reasoning=False,
    )

    assert result == "ok"
    assert captured["reasoning"] is False


@pytest.mark.asyncio
async def test_call_provider_passes_reasoning_false_to_bifrost(monkeypatch):
    import app.infrastructure.langfuse_client as langfuse_client
    from app.infrastructure.unified_llm_client import UnifiedLLMClient

    client = UnifiedLLMClient()
    captured: dict[str, object] = {}

    class FakeProvider:
        async def chat(self, **kwargs):
            captured.update(kwargs)
            return "ok"

        def estimate_cost(self, prompt_tokens, completion_tokens, model):
            return 0.0

    monkeypatch.setattr(client, "_get_provider", lambda name: FakeProvider())
    monkeypatch.setattr(langfuse_client, "get_langfuse_tracer", lambda: _DummyTracer())
    monkeypatch.setattr(client, "_record_usage", lambda *args, **kwargs: None)

    result = await client._call_provider(
        "bifrost",
        "openrouter/google/gemini-3.1-flash-lite",
        [{"role": "user", "content": "hi"}],
        None,
        0.3,
        96,
        reasoning=False,
    )

    assert result == "ok"
    assert captured["reasoning"] is False
