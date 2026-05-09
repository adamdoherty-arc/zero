"""
Centralized LLM Router. Multi-Provider Model Routing.

Every service that needs an LLM model should call:
    get_llm_router().resolve(task_type)

for backward compat (returns model name string), or:
    get_llm_router().resolve_provider_model(task_type)

for the full (provider, model, fallbacks) tuple.

Supports:
- provider/model specs: "gemini/gemini-3.1-pro-preview", "ollama/qwen3.6:35b-a3b-q8_0"
- Fallback chains: primary -> fallback1 -> fallback2
- Daily budget enforcement: global spend + per-provider caps
- Runtime reconfiguration via API without restart
- Persisted config in workspace/llm/router_config.json
"""

import asyncio
import os
from datetime import date
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import structlog

from app.infrastructure.config import get_workspace_path
from app.infrastructure.storage import JsonStorage
from app.models.llm import LlmRouterConfig, ModelAssignment, parse_provider_model

logger = structlog.get_logger(__name__)

CONFIG_FILE = "router_config.json"


# Local backend toggle — flips every ollama ↔ vllm routing decision.
# Cloud providers (gemini, kimi, minimax, openrouter, huggingface) are unaffected.
_LOCAL_PROVIDERS = ("ollama", "vllm")


def _active_local_backend() -> str:
    """Read LOCAL_LLM_BACKEND env var at call time (not module import) so tests can monkeypatch."""
    value = os.getenv("LOCAL_LLM_BACKEND", "").strip().lower()
    return value if value in _LOCAL_PROVIDERS else ""


def _apply_local_backend_remap(provider: str, model: str) -> Tuple[str, str]:
    """
    If LOCAL_LLM_BACKEND is set and this is a local-tier provider, rewrite it.

    Examples (with LOCAL_LLM_BACKEND=vllm):
      ("ollama", "qwen3.6:35b-a3b") → ("vllm", VLLM_CHAT_MODEL)
      ("gemini", "gemini-3-pro")    → ("gemini", "gemini-3-pro")  (unchanged)
    """
    override = _active_local_backend()
    if not override or provider not in _LOCAL_PROVIDERS or provider == override:
        return provider, model

    if override == "vllm":
        return "vllm", os.getenv("VLLM_CHAT_MODEL", "qwen3-chat")
    # override == "ollama"
    return "ollama", os.getenv("OLLAMA_CHAT_MODEL", "qwen3.6:35b-a3b-q8_0")


class LlmRouter:
    """Resolves which provider and model to use for a given task type."""

    def __init__(self):
        self._storage = JsonStorage(get_workspace_path("llm"))
        self._config = LlmRouterConfig()
        self._initialized = False
        self._budget_lock = asyncio.Lock()

    async def initialize(self):
        """Load persisted config from storage."""
        data = await self._storage.read(CONFIG_FILE)
        if data:
            try:
                self._config = LlmRouterConfig(**data)
            except Exception as e:
                logger.warning("llm_router_config_load_error", error=str(e))
        else:
            await self._save()
        self._initialized = True
        logger.info(
            "llm_router_initialized",
            default_model=self._config.default_model,
            task_count=len(self._config.task_assignments),
            budget=self._config.daily_budget_usd,
        )

    # ------------------------------------------------------------------
    # Resolution (backward compat)
    # ------------------------------------------------------------------

    def resolve(self, task_type: Optional[str] = None) -> str:
        """Resolve the model name for a given task type.

        Returns the raw model string (may include provider prefix).
        For backward compat with OllamaClient which strips provider prefix.
        """
        if task_type and task_type in self._config.task_assignments:
            return self._config.task_assignments[task_type].model
        return self._config.default_model

    def resolve_with_params(self, task_type: Optional[str] = None) -> Tuple[str, Optional[ModelAssignment]]:
        """Resolve model and full assignment params for a task type."""
        if task_type and task_type in self._config.task_assignments:
            assignment = self._config.task_assignments[task_type]
            return assignment.model, assignment
        return self._config.default_model, None

    # ------------------------------------------------------------------
    # Multi-provider resolution
    # ------------------------------------------------------------------

    # Default cross-provider fallback used when a task_type has no explicit
    # fallback chain (or when the caller didn't pass a task_type at all).
    # Ensures a circuit-breaker trip on the primary provider doesn't cascade
    # into "All LLM providers failed" for every downstream job.
    _DEFAULT_FALLBACKS: List[str] = [
        "minimax/MiniMax-M2.7",
        "kimi/kimi-k2.6",
        "vllm/qwen3-chat",
    ]

    def resolve_provider_model(
        self,
        task_type: Optional[str] = None,
    ) -> Tuple[str, str, List[Tuple[str, str]]]:
        """Resolve (provider, model, fallback_chain) for a task.

        Returns:
            (provider, model, [(fb_provider, fb_model), ...])
        """
        model_spec, assignment = self.resolve_with_params(task_type)
        provider, model = parse_provider_model(model_spec)

        # LOCAL_LLM_BACKEND override: rewrite local-tier picks to the active backend.
        provider, model = _apply_local_backend_remap(provider, model)

        fallbacks: List[Tuple[str, str]] = []
        if assignment and assignment.fallbacks:
            for fb_spec in assignment.fallbacks:
                fb_provider, fb_model = parse_provider_model(fb_spec)
                fb_provider, fb_model = _apply_local_backend_remap(fb_provider, fb_model)
                fallbacks.append((fb_provider, fb_model))
        else:
            for fb_spec in self._DEFAULT_FALLBACKS:
                fb_provider, fb_model = parse_provider_model(fb_spec)
                fb_provider, fb_model = _apply_local_backend_remap(fb_provider, fb_model)
                if fb_provider == provider and fb_model == model:
                    continue  # don't fallback to the same primary
                fallbacks.append((fb_provider, fb_model))

        return provider, model, fallbacks

    def check_budget(self, estimated_cost: float) -> bool:
        """Check if estimated cost fits within remaining daily budget.

        Returns True if within budget, False if would exceed.
        """
        if self._config.daily_budget_usd <= 0:
            return True  # No limit
        remaining = self._config.daily_budget_usd - self._config.current_spend_usd
        return estimated_cost <= remaining

    def get_remaining_budget(self) -> float:
        """Get remaining daily budget in USD."""
        if self._config.daily_budget_usd <= 0:
            return float("inf")
        return max(0.0, self._config.daily_budget_usd - self._config.current_spend_usd)

    async def record_spend(self, cost_usd: float, provider: Optional[str] = None):
        """Add to daily spend counter and persist (thread-safe).

        Also records per-provider spend to the llm_daily_spend DB table when
        a provider is supplied.
        """
        async with self._budget_lock:
            self._config.current_spend_usd += cost_usd
            await self._save()
        if provider and cost_usd > 0:
            try:
                await self._record_provider_spend(provider, cost_usd)
            except Exception as e:
                logger.warning("llm_provider_spend_record_failed", provider=provider, error=str(e))

    async def reset_daily_budget(self):
        """Reset daily spend to 0. Called by midnight scheduler job."""
        old = self._config.current_spend_usd
        self._config.current_spend_usd = 0.0
        await self._save()
        logger.info("llm_budget_reset", previous_spend=old)

    # ------------------------------------------------------------------
    # Per-provider daily spend (backed by llm_daily_spend table)
    # ------------------------------------------------------------------

    async def _record_provider_spend(self, provider: str, cost_usd: float):
        """Upsert into llm_daily_spend(provider, day, spend_usd)."""
        from app.infrastructure.database import get_session
        from sqlalchemy import text

        today = date.today()
        async with get_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO llm_daily_spend (provider, day, spend_usd)
                    VALUES (:provider, :day, :amount)
                    ON CONFLICT (provider, day)
                    DO UPDATE SET spend_usd = llm_daily_spend.spend_usd + :amount
                    """
                ),
                {"provider": provider, "day": today, "amount": float(cost_usd)},
            )
            await session.commit()

    async def get_daily_spend(self, provider: str) -> float:
        """Get today's total spend for a specific provider."""
        from app.infrastructure.database import get_session
        from sqlalchemy import text

        today = date.today()
        try:
            async with get_session() as session:
                result = await session.execute(
                    text(
                        "SELECT spend_usd FROM llm_daily_spend "
                        "WHERE provider = :provider AND day = :day"
                    ),
                    {"provider": provider, "day": today},
                )
                row = result.first()
                return float(row[0]) if row else 0.0
        except Exception as e:
            logger.warning("llm_provider_spend_read_failed", provider=provider, error=str(e))
            return 0.0

    async def is_budget_exceeded(self, provider: str, daily_cap_usd: float) -> bool:
        """Check if provider has exceeded its configured daily cap."""
        if daily_cap_usd <= 0:
            return False  # No cap
        spent = await self.get_daily_spend(provider)
        return spent >= daily_cap_usd

    async def get_all_daily_spend(self) -> Dict[str, float]:
        """Return today's spend for all providers."""
        from app.infrastructure.database import get_session
        from sqlalchemy import text

        today = date.today()
        try:
            async with get_session() as session:
                result = await session.execute(
                    text(
                        "SELECT provider, spend_usd FROM llm_daily_spend WHERE day = :day"
                    ),
                    {"day": today},
                )
                return {row[0]: float(row[1]) for row in result.all()}
        except Exception as e:
            logger.warning("llm_all_spend_read_failed", error=str(e))
            return {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def default_model(self) -> str:
        return self._config.default_model

    @property
    def config(self) -> LlmRouterConfig:
        return self._config

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def set_default_model(self, model: str, update_all_tasks: bool = False):
        """Change the default model. Optionally update all task assignments too."""
        old = self._config.default_model
        self._config.default_model = model
        if update_all_tasks:
            for assignment in self._config.task_assignments.values():
                assignment.model = model
        await self._save()
        logger.info("llm_router_default_changed", old=old, new=model, update_all=update_all_tasks)

    async def set_task_model(
        self,
        task_type: str,
        model: str,
        fallbacks: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        num_predict: Optional[int] = None,
        keep_alive: Optional[str] = None,
    ):
        """Set or update the model assignment for a task type."""
        if task_type in self._config.task_assignments:
            assignment = self._config.task_assignments[task_type]
            assignment.model = model
            if fallbacks is not None:
                assignment.fallbacks = fallbacks
            if temperature is not None:
                assignment.temperature = temperature
            if num_predict is not None:
                assignment.num_predict = num_predict
            if keep_alive is not None:
                assignment.keep_alive = keep_alive
        else:
            self._config.task_assignments[task_type] = ModelAssignment(
                model=model,
                fallbacks=fallbacks,
                temperature=temperature,
                num_predict=num_predict,
                keep_alive=keep_alive,
            )
        await self._save()
        logger.info("llm_router_task_updated", task_type=task_type, model=model)

    async def remove_task_override(self, task_type: str):
        """Remove a task-specific override so it falls back to default."""
        if task_type in self._config.task_assignments:
            del self._config.task_assignments[task_type]
            await self._save()

    async def _save(self):
        await self._storage.write(CONFIG_FILE, self._config.model_dump())


@lru_cache()
def get_llm_router() -> LlmRouter:
    """Get the singleton LLM router instance."""
    return LlmRouter()
