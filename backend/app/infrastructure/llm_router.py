"""
Centralized LLM Router — Multi-Provider Model Routing.

Every service that needs an LLM model should call:
    get_llm_router().resolve(task_type)

for backward compat (returns model name string), or:
    get_llm_router().resolve_provider_model(task_type)

for the full (provider, model, fallbacks) tuple.

Supports:
- provider/model specs: "gemini/gemini-3.1-pro-preview", "ollama/qwen3:8b"
- Fallback chains: primary → fallback1 → fallback2
- Daily budget enforcement: expensive providers blocked when budget exceeded
- Runtime reconfiguration via API without restart
- Persisted config in workspace/llm/router_config.json
"""

from functools import lru_cache
from typing import List, Optional, Tuple

import structlog

from app.infrastructure.config import get_workspace_path
from app.infrastructure.storage import JsonStorage
from app.models.llm import LlmRouterConfig, ModelAssignment, parse_provider_model

logger = structlog.get_logger(__name__)

CONFIG_FILE = "router_config.json"


class LlmRouter:
    """Resolves which provider and model to use for a given task type."""

    def __init__(self):
        self._storage = JsonStorage(get_workspace_path("llm"))
        self._config = LlmRouterConfig()
        self._initialized = False

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

        fallbacks = []
        if assignment and assignment.fallbacks:
            for fb_spec in assignment.fallbacks:
                fb_provider, fb_model = parse_provider_model(fb_spec)
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

    async def record_spend(self, cost_usd: float):
        """Add to daily spend counter and persist."""
        self._config.current_spend_usd += cost_usd
        await self._save()

    async def reset_daily_budget(self):
        """Reset daily spend to 0. Called by midnight scheduler job."""
        old = self._config.current_spend_usd
        self._config.current_spend_usd = 0.0
        await self._save()
        logger.info("llm_budget_reset", previous_spend=old)

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
