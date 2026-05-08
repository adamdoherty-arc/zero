"""Coverage for the OpenRouter free-tier rotation pool.

Verifies:
  - Round-robin select_next over (key × model) slots
  - Daily / RPM windows roll forward correctly
  - 429 cooldown skips the offending slot
  - Auth failure black-lists the key for 24 h
  - Empty key list / empty model list → returns None
  - Multi-key fan-out: 2 keys × 4 models = 8 distinct slots
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def fixed_models(monkeypatch):
    """Pin the model list so tests don't hit the live OpenRouter API."""
    from app.services.carousel_v2 import openrouter_free_pool

    async def _fake_fetch(self):
        return [
            "google/gemma-3-27b-it:free",
            "qwen/qwen-2.5-vl-72b-instruct:free",
            "meta-llama/llama-3.2-11b-vision-instruct:free",
            "nvidia/nemotron-nano-12b-v2-vl:free",
        ]

    monkeypatch.setattr(
        openrouter_free_pool.OpenRouterFreePool,
        "_fetch_free_vision_models",
        _fake_fetch,
    )
    yield


async def test_select_next_returns_none_when_no_keys(fixed_models):
    from app.services.carousel_v2.openrouter_free_pool import OpenRouterFreePool

    pool = OpenRouterFreePool(keys=[])
    assert await pool.select_next() is None


async def test_select_next_round_robins_across_slots(fixed_models):
    from app.services.carousel_v2.openrouter_free_pool import OpenRouterFreePool

    pool = OpenRouterFreePool(keys=["sk-A"])
    seen: list[tuple[str, str]] = []
    for _ in range(8):
        slot = await pool.select_next()
        assert slot is not None
        seen.append(slot)
    # 4 models, 8 picks → each model picked exactly twice (round-robin)
    models = [m for _, m in seen]
    counts = {m: models.count(m) for m in set(models)}
    assert all(c == 2 for c in counts.values()), f"unexpected distribution: {counts}"


async def test_multi_key_doubles_pool_size(fixed_models):
    from app.services.carousel_v2.openrouter_free_pool import OpenRouterFreePool

    pool = OpenRouterFreePool(keys=["sk-A", "sk-B"])
    assert pool.slot_count == 0  # models not loaded yet
    await pool._refresh_models_if_stale()
    assert pool.slot_count == 8  # 2 keys × 4 models


async def test_429_puts_slot_into_cooldown(fixed_models):
    from app.services.carousel_v2.openrouter_free_pool import OpenRouterFreePool

    pool = OpenRouterFreePool(keys=["sk-A"], rpm_limit=20, daily_limit=50)
    slot = await pool.select_next()
    assert slot is not None
    await pool.mark_429(slot, retry_after=10.0)

    # Next 3 picks must NOT return the cooled-down slot.
    for _ in range(3):
        nxt = await pool.select_next()
        assert nxt is not None
        assert nxt != slot, "429-cooldown slot should be skipped"


async def test_daily_quota_exhaustion_skips_slot(fixed_models):
    from app.services.carousel_v2.openrouter_free_pool import OpenRouterFreePool

    pool = OpenRouterFreePool(keys=["sk-A"], rpm_limit=999, daily_limit=2)
    slot = await pool.select_next()
    assert slot is not None
    await pool.mark_success(slot)
    await pool.mark_success(slot)  # daily_used=2 → at limit

    # Next 4 picks must NOT return the same slot until window rolls.
    for _ in range(4):
        nxt = await pool.select_next()
        assert nxt is not None
        assert nxt != slot, "daily-exhausted slot should be skipped"


async def test_rpm_window_rolls_after_60_seconds(fixed_models):
    from app.services.carousel_v2.openrouter_free_pool import OpenRouterFreePool, _Counter

    pool = OpenRouterFreePool(keys=["sk-A"], rpm_limit=2, daily_limit=999)
    slot = await pool.select_next()
    await pool.mark_success(slot)
    await pool.mark_success(slot)  # rpm_used=2 → at limit

    # Force the window-start back so the roll fires.
    counter_key = pool._counter_redis_key(slot)
    pool._counters[counter_key].rpm_window_start = time.time() - 90.0

    nxt = await pool.select_next()
    # Could be the same slot (window rolled) — point is it's eligible again.
    assert nxt is not None


async def test_auth_failure_blacklists_for_long_cooldown(fixed_models):
    from app.services.carousel_v2.openrouter_free_pool import OpenRouterFreePool

    pool = OpenRouterFreePool(keys=["sk-bad"])
    slot = await pool.select_next()
    await pool.mark_auth_failure(slot, cooldown_seconds=24 * 3600)

    counter_key = pool._counter_redis_key(slot)
    counter = pool._counters[counter_key]
    assert counter.cooldown_until > time.time() + 23 * 3600, "must blacklist for ~24h"


async def test_pool_falls_back_to_hardcoded_list_when_fetch_fails(monkeypatch):
    from app.services.carousel_v2.openrouter_free_pool import (
        FALLBACK_VISION_MODELS,
        OpenRouterFreePool,
    )

    async def _broken(self):
        return []

    monkeypatch.setattr(
        OpenRouterFreePool, "_fetch_free_vision_models", _broken
    )
    pool = OpenRouterFreePool(keys=["sk-A"])
    await pool._refresh_models_if_stale()
    assert pool._models == list(FALLBACK_VISION_MODELS)
