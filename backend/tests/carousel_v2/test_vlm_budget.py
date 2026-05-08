"""VLM spend cap coverage.

Confirms:
  - Calls within budget pass ``can_spend``
  - Per-carousel cap blocks once accumulated spend would exceed
  - Daily cap blocks once aggregate exceeds, even across carousels
  - Free tier (cost = 0.0) never gates
  - Different carousels have independent per-carousel buckets
  - Reset between tests via ``reset_vlm_budget_for_tests``
"""

from __future__ import annotations

import pytest


@pytest.fixture
def fresh_budget(monkeypatch):
    from app.services.carousel_v2 import vlm_budget as budget_mod
    budget_mod.reset_vlm_budget_for_tests()
    yield
    budget_mod.reset_vlm_budget_for_tests()


async def test_zero_cost_call_always_allowed(fresh_budget):
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=0.0, per_carousel_cap_usd=0.0, redis_url=None)
    # Even with zero caps, a $0 call passes — that's the free-pool path.
    assert await b.can_spend(generation_id="g1", estimated_cost_usd=0.0) is True


async def test_within_budget_allowed(fresh_budget):
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=1.0, per_carousel_cap_usd=0.10, redis_url=None)
    assert await b.can_spend(generation_id="g1", estimated_cost_usd=0.05) is True


async def test_per_carousel_cap_blocks_after_exceeding(fresh_budget):
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=10.0, per_carousel_cap_usd=0.10, redis_url=None)

    # First call $0.06 — within cap.
    assert await b.can_spend(generation_id="g1", estimated_cost_usd=0.06) is True
    await b.record(generation_id="g1", cost_usd=0.06)

    # Next $0.06 would total $0.12 > $0.10 cap → blocked.
    assert await b.can_spend(generation_id="g1", estimated_cost_usd=0.06) is False


async def test_per_carousel_buckets_are_independent(fresh_budget):
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=10.0, per_carousel_cap_usd=0.10, redis_url=None)
    await b.record(generation_id="g1", cost_usd=0.10)

    # g1 is at the cap → blocked.
    assert await b.can_spend(generation_id="g1", estimated_cost_usd=0.001) is False
    # g2 has its own bucket → allowed.
    assert await b.can_spend(generation_id="g2", estimated_cost_usd=0.05) is True


async def test_daily_cap_blocks_once_aggregate_exceeds(fresh_budget):
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=0.20, per_carousel_cap_usd=10.0, redis_url=None)

    # Fill up the daily cap across multiple carousels.
    await b.record(generation_id="g1", cost_usd=0.10)
    await b.record(generation_id="g2", cost_usd=0.08)
    # Aggregate = $0.18; another $0.05 would push to $0.23 > $0.20.
    assert await b.can_spend(generation_id="g3", estimated_cost_usd=0.05) is False
    # But $0.01 fits.
    assert await b.can_spend(generation_id="g3", estimated_cost_usd=0.01) is True


async def test_record_then_query_daily_total(fresh_budget):
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=1.0, per_carousel_cap_usd=0.10, redis_url=None)
    await b.record(generation_id="g1", cost_usd=0.05)
    await b.record(generation_id="g2", cost_usd=0.07)
    assert await b.daily_spent() == pytest.approx(0.12)


async def test_per_carousel_spent_query(fresh_budget):
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=1.0, per_carousel_cap_usd=0.10, redis_url=None)
    await b.record(generation_id="g1", cost_usd=0.04)
    await b.record(generation_id="g1", cost_usd=0.03)
    assert await b.per_carousel_spent("g1") == pytest.approx(0.07)
    assert await b.per_carousel_spent("g2") == 0.0


async def test_zero_caps_disabled_gates(fresh_budget):
    """When a cap is set to 0.0 it is treated as 'disabled' rather than
    'always block'. Otherwise the operator couldn't opt out without removing
    the budget service entirely.
    """
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=0.0, per_carousel_cap_usd=0.0, redis_url=None)
    # Both caps are off → any spend is allowed.
    assert await b.can_spend(generation_id="g1", estimated_cost_usd=99.0) is True


async def test_no_generation_id_skips_per_carousel_check(fresh_budget):
    from app.services.carousel_v2.vlm_budget import VlmBudget

    b = VlmBudget(daily_cap_usd=10.0, per_carousel_cap_usd=0.001, redis_url=None)
    # Without a generation_id the per-carousel cap can't gate; only daily.
    assert await b.can_spend(generation_id=None, estimated_cost_usd=0.05) is True


async def test_singleton_get_vlm_budget_is_cached(fresh_budget, monkeypatch):
    from app.services.carousel_v2 import vlm_budget as budget_mod

    real_settings = (await _settings(monkeypatch))
    monkeypatch.setattr(real_settings, "vlm_daily_budget_usd", 0.5, raising=False)
    monkeypatch.setattr(real_settings, "vlm_per_carousel_cap_usd", 0.05, raising=False)

    a = await budget_mod.get_vlm_budget()
    b = await budget_mod.get_vlm_budget()
    assert a is b
    assert a.daily_cap_usd == pytest.approx(0.5)
    assert a.per_carousel_cap_usd == pytest.approx(0.05)


async def _settings(monkeypatch):
    from app.infrastructure import config as cfg
    cfg.get_settings.cache_clear()
    return cfg.get_settings()
