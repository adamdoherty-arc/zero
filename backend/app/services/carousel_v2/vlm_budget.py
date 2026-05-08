"""Daily + per-carousel VLM spend caps for the cheap-VLM router.

Carousel V2 image verification routes through Gemini paid (Tier 0) and the
OpenRouter free pool (Tier 1). Even though Tier 1 is $0 and Gemini Flash is
~$0.0001/call, an unbounded loop or a buggy candidate flood could burn real
money. This module enforces two caps:

  - **Daily cap** (env ``ZERO_VLM_DAILY_BUDGET_USD``, default $1.00) — sums
    spend in a 24-hour rolling window keyed in Redis at
    ``carousel_v2:vlm_budget:daily:{YYYYMMDD}``.

  - **Per-carousel cap** (env ``ZERO_VLM_PER_CAROUSEL_CAP_USD``, default
    $0.10) — sums spend per ``generation_id`` so one runaway carousel can't
    eat the daily cap. In-memory keyed (carousel V2 always finishes within
    one process; the per-carousel state doesn't need to survive restarts).

The free OpenRouter pool is **always** allowed regardless of budget — it's
free by definition. Only paid tiers (Gemini, Kimi if re-enabled later)
consult the budget.

When a paid call would exceed either cap, the router skips that tier and
falls through. If every paid tier is gated and the free pool is also
exhausted, ``verify_image`` returns the failure-soft envelope and Stage 9
ranks on cheap-CV signals only.

Failure-soft: when Redis is unavailable the daily counter falls back to an
in-process dict so the worker still functions (with a soft warning that
budget tracking isn't durable).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("carousel_v2:vlm_budget:daily:%Y%m%d")


class VlmBudget:
    """Tracks daily total + per-carousel spend for paid VLM calls."""

    def __init__(
        self,
        *,
        daily_cap_usd: float,
        per_carousel_cap_usd: float,
        redis_url: Optional[str] = None,
    ) -> None:
        self.daily_cap_usd = max(0.0, float(daily_cap_usd))
        self.per_carousel_cap_usd = max(0.0, float(per_carousel_cap_usd))
        self._redis_url = redis_url
        self._redis = None
        self._lock = asyncio.Lock()
        self._fallback_daily: float = 0.0
        self._fallback_daily_key: str = ""
        self._per_carousel: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect_redis(self) -> None:
        if self._redis is not None or not self._redis_url:
            return
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=False)
            await self._redis.ping()
        except Exception as exc:  # noqa: BLE001
            logger.warning("vlm_budget_redis_unavailable", error=str(exc))
            self._redis = None

    async def can_spend(
        self,
        *,
        generation_id: Optional[str],
        estimated_cost_usd: float,
    ) -> bool:
        """Returns True when the (estimated) call would stay within both caps.

        Free-tier callers should bypass this entirely; only paid tiers gate.
        """
        if estimated_cost_usd <= 0.0:
            return True

        # Per-carousel cap.
        if generation_id and self.per_carousel_cap_usd > 0.0:
            spent = self._per_carousel.get(generation_id, 0.0)
            if spent + estimated_cost_usd > self.per_carousel_cap_usd:
                logger.info(
                    "vlm_budget_per_carousel_block",
                    generation_id=generation_id,
                    spent_usd=round(spent, 6),
                    estimated_usd=round(estimated_cost_usd, 6),
                    cap_usd=self.per_carousel_cap_usd,
                )
                return False

        # Daily cap.
        if self.daily_cap_usd > 0.0:
            daily = await self._daily_spent()
            if daily + estimated_cost_usd > self.daily_cap_usd:
                logger.warning(
                    "vlm_budget_daily_block",
                    spent_usd=round(daily, 6),
                    estimated_usd=round(estimated_cost_usd, 6),
                    cap_usd=self.daily_cap_usd,
                )
                return False

        return True

    async def record(
        self,
        *,
        generation_id: Optional[str],
        cost_usd: float,
    ) -> None:
        """Stamp the realized cost. Call after a successful paid VLM call."""
        if cost_usd <= 0.0:
            return
        async with self._lock:
            if generation_id:
                self._per_carousel[generation_id] = (
                    self._per_carousel.get(generation_id, 0.0) + cost_usd
                )

            key = _today_key()
            if self._redis is not None:
                try:
                    # INCRBYFLOAT + EXPIRE on first write so the key auto-expires
                    # ~26h after midnight UTC.
                    new_total = await self._redis.incrbyfloat(key, cost_usd)
                    if float(new_total) <= cost_usd + 1e-9:
                        await self._redis.expire(key, 26 * 3600)
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.debug("vlm_budget_redis_record_failed", error=str(exc))

            # In-memory fallback. Reset when the day rolls over.
            if self._fallback_daily_key != key:
                self._fallback_daily_key = key
                self._fallback_daily = 0.0
            self._fallback_daily += cost_usd

    async def daily_spent(self) -> float:
        return await self._daily_spent()

    async def per_carousel_spent(self, generation_id: str) -> float:
        return self._per_carousel.get(generation_id, 0.0)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _daily_spent(self) -> float:
        key = _today_key()
        if self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw is None:
                    return 0.0
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                return float(raw)
            except Exception as exc:  # noqa: BLE001
                logger.debug("vlm_budget_redis_get_failed", error=str(exc))

        if self._fallback_daily_key != key:
            return 0.0
        return self._fallback_daily


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_budget: Optional[VlmBudget] = None


async def get_vlm_budget() -> VlmBudget:
    """Process-wide singleton. Reads caps from Settings on first call."""
    global _budget
    if _budget is not None:
        return _budget
    s = get_settings()
    redis_url = os.getenv("ZERO_REDIS_URL", "redis://zero-redis:6379/0")
    budget = VlmBudget(
        daily_cap_usd=getattr(s, "vlm_daily_budget_usd", 1.0),
        per_carousel_cap_usd=getattr(s, "vlm_per_carousel_cap_usd", 0.10),
        redis_url=redis_url,
    )
    await budget.connect_redis()
    _budget = budget
    logger.info(
        "vlm_budget_initialized",
        daily_cap_usd=budget.daily_cap_usd,
        per_carousel_cap_usd=budget.per_carousel_cap_usd,
    )
    return budget


def reset_vlm_budget_for_tests() -> None:
    """Test-only — clears the singleton so each test sees a fresh budget."""
    global _budget
    _budget = None
