"""Coverage for the tiered cheap-VLM router.

NOTE 2026-05-14: skipped at module level after the Bifrost migration.
GeminiProvider and OpenRouterProvider were deleted under the new
Kimi-only-cloud policy, so the Tier 0 / Tier 1 dispatchers in
``cheap_vlm_router`` are now no-op stubs. The tests below exercise
that deleted machinery and would fail on the missing imports. They
will be rewritten when a local vision model lands and Stage-8 VLM
is re-enabled through Bifrost.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "cheap_vlm_router tiers disabled post-Bifrost migration (2026-05-14)",
    allow_module_level=True,
)


@pytest.fixture
def reset_pool(monkeypatch):
    """Reset the OpenRouter pool singleton between tests."""
    from app.services.carousel_v2 import openrouter_free_pool as pool_mod
    pool_mod.reset_openrouter_free_pool_for_tests()
    yield
    pool_mod.reset_openrouter_free_pool_for_tests()


@pytest.fixture
def reset_budget():
    """Reset the VLM budget singleton between tests so per-carousel +
    daily counters don't leak across cases.
    """
    from app.services.carousel_v2 import vlm_budget as budget_mod
    budget_mod.reset_vlm_budget_for_tests()
    yield
    budget_mod.reset_vlm_budget_for_tests()


def test_strip_fences_handles_json_blocks():
    from app.services.carousel_v2.cheap_vlm_router import _strip_fences

    assert _strip_fences("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert _strip_fences("```\n{\"a\": 1}\n```") == '{"a": 1}'
    assert _strip_fences("{\"a\": 1}") == '{"a": 1}'


def test_parse_json_recovers_from_trailing_prose():
    from app.services.carousel_v2.cheap_vlm_router import _parse_json

    payload = 'Here is the verdict: {"likeness": 0.9, "watermark": false} hope this helps.'
    result = _parse_json(payload)
    assert result == {"likeness": 0.9, "watermark": False}


def test_parse_json_returns_none_on_garbage():
    from app.services.carousel_v2.cheap_vlm_router import _parse_json

    assert _parse_json("not json at all") is None
    assert _parse_json("") is None


def test_normalise_likeness_clamps_to_unit_interval():
    from app.services.carousel_v2.cheap_vlm_router import _normalise_likeness

    out = _normalise_likeness({"likeness": 1.7})
    assert out["likeness"] == 1.0

    out = _normalise_likeness({"likeness": -0.3})
    assert out["likeness"] == 0.0

    out = _normalise_likeness({"likeness": "not a number"})
    assert out["likeness"] is None


async def test_tier0_gemini_success_short_circuits(monkeypatch, reset_pool, reset_budget):
    """Tier 0 = Gemini 3.1 Flash. When it parses cleanly the router never
    reaches Tier 1.
    """
    from app.services.carousel_v2 import cheap_vlm_router

    class _FakeGemini:
        async def chat(self, **kw):
            assert kw.get("image_urls") == ["https://i/x.jpg"]
            return '{"likeness": 0.91, "watermark": false, "text_overlay": false, "character": "Homelander"}'
        def estimate_cost(self, prompt_tokens, completion_tokens, model):
            assert "3.1" in model or "gemini" in model
            return 0.00012

    def _fake_get(name):
        if name == "gemini":
            return _FakeGemini()
        raise AssertionError(f"unexpected provider lookup: {name}")

    import app.infrastructure.llm_providers as llm_pkg
    monkeypatch.setattr(llm_pkg, "get_provider", _fake_get)

    real_settings = (await _settings(monkeypatch))
    monkeypatch.setattr(real_settings, "gemini_api_key", "sk-gemini-test", raising=False)
    monkeypatch.setattr(real_settings, "vlm_daily_budget_usd", 1.0, raising=False)
    monkeypatch.setattr(real_settings, "vlm_per_carousel_cap_usd", 0.10, raising=False)

    out = await cheap_vlm_router.verify_image(
        "https://i/x.jpg", character="Homelander", franchise="the_boys", generation_id="gen-test-1"
    )
    assert out["_tier"] == "gemini_paid"
    assert out["_model"].startswith("gemini/")
    assert out["likeness"] == pytest.approx(0.91)
    assert out["_cost_usd"] == pytest.approx(0.00012)


async def test_tier0_gemini_failure_falls_through_to_tier1(monkeypatch, reset_pool, reset_budget):
    """Gemini returns garbage → router must escalate to OpenRouter free pool."""
    from app.services.carousel_v2 import cheap_vlm_router, openrouter_free_pool

    class _FlakyGemini:
        async def chat(self, **kw):
            return "completely unparseable noise"
        def estimate_cost(self, *_a):
            return 0.00012

    class _OkOpenRouter:
        async def chat(self, **kw):
            assert "image_urls" in kw
            assert kw.get("api_key_override") == "sk-or-test"
            return '{"likeness": 0.7, "watermark": false, "character": "Homelander"}'

    def _fake_get(name):
        return _FlakyGemini() if name == "gemini" else _OkOpenRouter()

    import app.infrastructure.llm_providers as llm_pkg
    monkeypatch.setattr(llm_pkg, "get_provider", _fake_get)

    real_settings = (await _settings(monkeypatch))
    monkeypatch.setattr(real_settings, "gemini_api_key", "sk-gemini-test", raising=False)
    monkeypatch.setattr(real_settings, "openrouter_api_key", "sk-or-test", raising=False)
    monkeypatch.setattr(real_settings, "openrouter_api_keys", "", raising=False)
    monkeypatch.setattr(real_settings, "vlm_daily_budget_usd", 1.0, raising=False)
    monkeypatch.setattr(real_settings, "vlm_per_carousel_cap_usd", 0.10, raising=False)

    async def _models(self):
        return ["google/gemma-3-27b-it:free"]
    monkeypatch.setattr(
        openrouter_free_pool.OpenRouterFreePool,
        "_fetch_free_vision_models",
        _models,
    )

    out = await cheap_vlm_router.verify_image(
        "https://i/x.jpg", character="Homelander", franchise="the_boys", generation_id="gen-test-2"
    )
    assert out["_tier"] == "openrouter_free"
    assert out["_cost_usd"] == 0.0
    assert out["likeness"] == pytest.approx(0.7)


async def test_budget_cap_blocks_tier0_and_falls_through_to_free_pool(monkeypatch, reset_pool, reset_budget):
    """When the per-carousel cap is exhausted, Tier 0 (paid) is skipped and
    Tier 1 (free pool) catches the call.
    """
    from app.services.carousel_v2 import cheap_vlm_router, openrouter_free_pool, vlm_budget

    gemini_called = []

    class _Gemini:
        async def chat(self, **kw):
            gemini_called.append(True)
            return '{"likeness": 1.0}'
        def estimate_cost(self, *_a):
            return 0.5  # WAY over the per-carousel cap of $0.10

    class _OkOpenRouter:
        async def chat(self, **kw):
            return '{"likeness": 0.6, "character": "Homelander"}'

    def _fake_get(name):
        return _Gemini() if name == "gemini" else _OkOpenRouter()

    import app.infrastructure.llm_providers as llm_pkg
    monkeypatch.setattr(llm_pkg, "get_provider", _fake_get)

    real_settings = (await _settings(monkeypatch))
    monkeypatch.setattr(real_settings, "gemini_api_key", "sk-gemini-test", raising=False)
    monkeypatch.setattr(real_settings, "openrouter_api_key", "sk-or-test", raising=False)
    monkeypatch.setattr(real_settings, "openrouter_api_keys", "", raising=False)
    monkeypatch.setattr(real_settings, "vlm_daily_budget_usd", 1.0, raising=False)
    monkeypatch.setattr(real_settings, "vlm_per_carousel_cap_usd", 0.10, raising=False)

    async def _models(self):
        return ["google/gemma-3-27b-it:free"]
    monkeypatch.setattr(
        openrouter_free_pool.OpenRouterFreePool,
        "_fetch_free_vision_models",
        _models,
    )

    out = await cheap_vlm_router.verify_image(
        "https://i/x.jpg", character="Homelander", generation_id="gen-test-budget"
    )
    # Estimated $0.50 > $0.10 cap → Gemini is GATED before the call.
    assert gemini_called == [], "Gemini must NOT be called when budget would be exceeded"
    assert out["_tier"] == "openrouter_free"
    assert out["likeness"] == pytest.approx(0.6)


async def test_tier1_429_rotates_within_tier_before_escalating(monkeypatch, reset_pool, reset_budget):
    from app.services.carousel_v2 import cheap_vlm_router, openrouter_free_pool
    from app.infrastructure.llm_providers.openrouter_provider import RateLimitError

    call_log: list[str] = []

    class _OpenRouter429ThenOk:
        async def chat(self, **kw):
            model = kw["model"]
            call_log.append(model)
            if "gemma-3-27b-it" in model:
                raise RateLimitError(retry_after=5.0, model=model)
            return '{"likeness": 0.8, "watermark": false, "character": "Homelander"}'

    def _fake_get(name):
        # Gemini missing → Tier 0 short-circuits → Tier 1 fires.
        if name == "gemini":
            return None
        return _OpenRouter429ThenOk()

    import app.infrastructure.llm_providers as llm_pkg
    monkeypatch.setattr(llm_pkg, "get_provider", _fake_get)

    real_settings = (await _settings(monkeypatch))
    monkeypatch.setattr(real_settings, "gemini_api_key", None, raising=False)
    monkeypatch.setattr(real_settings, "openrouter_api_key", "sk-or-test", raising=False)
    monkeypatch.setattr(real_settings, "openrouter_api_keys", "", raising=False)

    async def _models(self):
        return [
            "google/gemma-3-27b-it:free",          # this one 429s
            "qwen/qwen-2.5-vl-72b-instruct:free",  # this one succeeds
        ]
    monkeypatch.setattr(
        openrouter_free_pool.OpenRouterFreePool,
        "_fetch_free_vision_models",
        _models,
    )

    out = await cheap_vlm_router.verify_image(
        "https://i/x.jpg", character="Homelander", franchise="the_boys"
    )
    assert out["_tier"] == "openrouter_free"
    assert "qwen-2.5-vl-72b-instruct" in out["_model"]
    assert call_log == [
        "google/gemma-3-27b-it:free",
        "qwen/qwen-2.5-vl-72b-instruct:free",
    ]


async def test_all_tiers_exhausted_returns_failure_soft_envelope(monkeypatch, reset_pool, reset_budget):
    from app.services.carousel_v2 import cheap_vlm_router, openrouter_free_pool

    class _AlwaysFails:
        async def chat(self, **kw):
            raise RuntimeError("upstream down")
        def estimate_cost(self, *_a):
            return 0.00012

    def _fake_get(name):
        return _AlwaysFails()

    import app.infrastructure.llm_providers as llm_pkg
    monkeypatch.setattr(llm_pkg, "get_provider", _fake_get)

    real_settings = (await _settings(monkeypatch))
    monkeypatch.setattr(real_settings, "gemini_api_key", "sk-gemini-test", raising=False)
    monkeypatch.setattr(real_settings, "openrouter_api_key", "sk-or-test", raising=False)
    monkeypatch.setattr(real_settings, "openrouter_api_keys", "", raising=False)
    monkeypatch.setattr(real_settings, "vlm_daily_budget_usd", 1.0, raising=False)
    monkeypatch.setattr(real_settings, "vlm_per_carousel_cap_usd", 0.10, raising=False)

    async def _models(self):
        return ["google/gemma-3-27b-it:free"]
    monkeypatch.setattr(
        openrouter_free_pool.OpenRouterFreePool,
        "_fetch_free_vision_models",
        _models,
    )

    out = await cheap_vlm_router.verify_image(
        "https://i/x.jpg", character="Homelander", franchise="the_boys"
    )
    assert out["_available"] is False
    assert out["_tier"] == "exhausted"
    assert out["likeness"] is None
    assert out["error"] == "all_tiers_exhausted"


async def _settings(monkeypatch):
    """Helper: return the cached Settings instance after clearing the lru_cache."""
    from app.infrastructure import config as cfg
    cfg.get_settings.cache_clear()
    return cfg.get_settings()
