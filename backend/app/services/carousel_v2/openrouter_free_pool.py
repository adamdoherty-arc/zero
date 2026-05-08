"""OpenRouter free-tier vision-model pool with rotation + per-key quota.

Carousel V2 Stage-8 image verification (`cheap_vlm_router.py`) consults this
pool when its Tier-1 fallback fires. We rotate over (key × model) slots,
respecting the documented free-tier limits (20 req/min, 50 req/day per key
× model — actually per-account, but per-model granularity gives us the right
rate-limit behavior because OpenRouter applies caps at the upstream provider).

State storage:
  - Quota counters live in Redis when ``ZERO_REDIS_URL`` resolves; in-memory
    dict otherwise. Tests use the in-memory path.
  - Free-model list is fetched from ``GET /api/v1/models?supported_parameters=image_input``
    and cached for 6 h.

Public surface::

    pool = await get_openrouter_free_pool()
    slot = await pool.select_next()       # → (key, model) | None
    if slot:
        try:
            ...call openrouter chat...
            await pool.mark_success(slot, tokens_used=512)
        except RateLimitError as exc:
            await pool.mark_429(slot, retry_after=exc.retry_after)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_LIST_TTL_SECONDS = 6 * 3600
DEFAULT_RPM_LIMIT = 20      # OpenRouter free tier caps (no credit card)
DEFAULT_DAILY_LIMIT = 50

# Hardcoded fallback list — used when the live model-list call fails. Keeps
# the worker functional even during OpenRouter outages or DNS hiccups.
FALLBACK_VISION_MODELS = [
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "google/gemma-3-4b-it:free",
    "qwen/qwen-2.5-vl-72b-instruct:free",
    "qwen/qwen-2.5-vl-32b-instruct:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
]


def _key_id(key: str) -> str:
    """Stable short hash for log lines + Redis key fragments."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


@dataclass
class _Slot:
    """A single (api_key, model) cell in the rotation grid."""
    key: str
    model: str

    @property
    def label(self) -> str:
        return f"{_key_id(self.key)}:{self.model}"


@dataclass
class _Counter:
    rpm_used: int = 0
    rpm_window_start: float = 0.0
    daily_used: int = 0
    daily_window_start: float = 0.0
    cooldown_until: float = 0.0


class OpenRouterFreePool:
    """Round-robin (key × model) rotation with per-slot quota state.

    The pool is **process-wide singleton**. Quota state survives process
    restarts via Redis; falls back to in-memory dict when Redis isn't
    configured (unit tests).
    """

    def __init__(
        self,
        keys: list[str],
        *,
        redis_url: Optional[str] = None,
        rpm_limit: int = DEFAULT_RPM_LIMIT,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
    ):
        self._keys = [k for k in keys if k]
        self._rpm_limit = rpm_limit
        self._daily_limit = daily_limit
        self._redis_url = redis_url
        self._redis = None
        self._models: list[str] = []
        self._models_fetched_at: float = 0.0
        self._counters: dict[str, _Counter] = {}
        self._cursor = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def select_next(self) -> Optional[tuple[str, str]]:
        """Return ``(key, model)`` for the next eligible slot, or ``None``
        when every slot in the pool is in cooldown / out of quota.
        """
        if not self._keys:
            return None
        await self._refresh_models_if_stale()
        if not self._models:
            return None

        slots = self._all_slots()
        if not slots:
            return None

        async with self._lock:
            now = time.time()
            n = len(slots)
            for offset in range(n):
                candidate = slots[(self._cursor + offset) % n]
                if await self._slot_eligible(candidate, now=now):
                    self._cursor = (self._cursor + offset + 1) % n
                    return (candidate.key, candidate.model)
        return None

    async def mark_success(
        self,
        slot: tuple[str, str],
        *,
        tokens_used: int = 0,
    ) -> None:
        async with self._lock:
            counter = await self._get_counter(slot)
            now = time.time()
            self._roll_windows(counter, now=now)
            counter.rpm_used += 1
            counter.daily_used += 1
            await self._save_counter(slot, counter)

    async def mark_429(
        self,
        slot: tuple[str, str],
        *,
        retry_after: float,
    ) -> None:
        # Defense in depth — even if a misbehaving 429 surfaces a
        # millennia-long retry_after, cap at 24h so a single bad header
        # doesn't permanently lock the slot.
        cooldown_seconds = max(1.0, min(86400.0, float(retry_after)))
        async with self._lock:
            counter = await self._get_counter(slot)
            counter.cooldown_until = time.time() + cooldown_seconds
            await self._save_counter(slot, counter)
        logger.warning(
            "openrouter_slot_cooldown",
            slot=f"{_key_id(slot[0])}:{slot[1]}",
            retry_after=retry_after,
        )

    async def mark_auth_failure(
        self,
        slot: tuple[str, str],
        *,
        cooldown_seconds: float = 24 * 3600,
    ) -> None:
        """4xx auth failures (401/403) — black-list the key for a full day."""
        async with self._lock:
            counter = await self._get_counter(slot)
            counter.cooldown_until = time.time() + cooldown_seconds
            await self._save_counter(slot, counter)

    @property
    def slot_count(self) -> int:
        return len(self._keys) * len(self._models)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _all_slots(self) -> list[_Slot]:
        return [_Slot(k, m) for k in self._keys for m in self._models]

    async def _slot_eligible(self, slot: _Slot, *, now: float) -> bool:
        counter = await self._get_counter((slot.key, slot.model))
        self._roll_windows(counter, now=now)
        if counter.cooldown_until > now:
            return False
        if counter.rpm_used >= self._rpm_limit:
            return False
        if counter.daily_used >= self._daily_limit:
            return False
        return True

    @staticmethod
    def _roll_windows(counter: _Counter, *, now: float) -> None:
        if now - counter.rpm_window_start >= 60.0:
            counter.rpm_window_start = now
            counter.rpm_used = 0
        if now - counter.daily_window_start >= 86400.0:
            counter.daily_window_start = now
            counter.daily_used = 0

    def _counter_redis_key(self, slot: tuple[str, str]) -> str:
        return f"carousel_v2:or_quota:{_key_id(slot[0])}:{slot[1]}"

    async def _get_counter(self, slot: tuple[str, str]) -> _Counter:
        """Read a slot's counter. Redis is authoritative when available — if
        the key is missing in Redis, we return a fresh ``_Counter`` even if
        the in-memory cache has stale data. Without this, an explicit Redis
        flush wouldn't clear the long-running worker's poisoned cooldowns.
        """
        key = self._counter_redis_key(slot)
        if self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    payload = json.loads(raw)
                    return _Counter(**payload)
                # Redis up + key missing → treat as fresh, drop stale memory.
                self._counters.pop(key, None)
                return _Counter()
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis_get_counter_failed", error=str(exc))
        # Redis unavailable — fall back to in-memory cache.
        return self._counters.get(key) or _Counter()

    async def _save_counter(self, slot: tuple[str, str], counter: _Counter) -> None:
        key = self._counter_redis_key(slot)
        self._counters[key] = counter
        if self._redis is not None:
            try:
                await self._redis.set(
                    key,
                    json.dumps(counter.__dict__),
                    ex=86400,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis_set_counter_failed", error=str(exc))

    async def connect_redis(self) -> None:
        """Lazy-connect Redis. Failure-soft — falls back to in-memory state."""
        if self._redis is not None or not self._redis_url:
            return
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=False)
            # Probe.
            await self._redis.ping()
        except Exception as exc:  # noqa: BLE001
            logger.warning("openrouter_pool_redis_unavailable", error=str(exc))
            self._redis = None

    async def _refresh_models_if_stale(self) -> None:
        if self._models and (time.time() - self._models_fetched_at) < MODEL_LIST_TTL_SECONDS:
            return
        models = await self._fetch_free_vision_models()
        if models:
            self._models = models
            self._models_fetched_at = time.time()
            logger.info("openrouter_free_vision_models_loaded", n=len(self._models))
        elif not self._models:
            self._models = list(FALLBACK_VISION_MODELS)
            self._models_fetched_at = time.time()
            logger.info("openrouter_free_vision_models_using_fallback", n=len(self._models))

    async def _fetch_free_vision_models(self) -> list[str]:
        if not self._keys:
            return []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{OPENROUTER_BASE}/models",
                    headers={
                        "Authorization": f"Bearer {self._keys[0]}",
                        "HTTP-Referer": "https://zero-ai.local",
                        "X-Title": "Zero AI",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("openrouter_models_fetch_failed", error=str(exc))
            return []

        out: list[str] = []
        for entry in payload.get("data", []) or []:
            model_id = entry.get("id", "")
            if not model_id.endswith(":free"):
                continue
            modalities = (entry.get("architecture") or {}).get("input_modalities") or []
            if "image" in modalities:
                out.append(model_id)
        return out


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_pool: Optional[OpenRouterFreePool] = None


def _split_keys(plural: str, singular: Optional[str]) -> list[str]:
    if plural:
        return [k.strip() for k in plural.split(",") if k.strip()]
    return [singular] if singular else []


async def get_openrouter_free_pool() -> OpenRouterFreePool:
    """Process-wide singleton. Reads keys from settings on first call."""
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    keys = _split_keys(
        getattr(settings, "openrouter_api_keys", "") or "",
        settings.openrouter_api_key,
    )
    redis_url = os.getenv("ZERO_REDIS_URL", "redis://zero-redis:6379/0")
    pool = OpenRouterFreePool(keys=keys, redis_url=redis_url)
    await pool.connect_redis()
    _pool = pool
    return pool


def reset_openrouter_free_pool_for_tests() -> None:
    """Test-only — clears the singleton so each test sees a fresh pool."""
    global _pool
    _pool = None
