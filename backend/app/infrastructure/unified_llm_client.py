"""
Unified LLM Client — Central hub for all LLM calls across providers.

Routes requests through the enhanced LLM Router with:
- Automatic provider selection based on task type
- Fallback chains (primary → fallback1 → fallback2 → ...)
- Daily budget enforcement (force Ollama when budget exceeded)
- Circuit breaker per provider
- Usage tracking to PostgreSQL (llm_usage table)
- Metrics recording for dashboards

All existing services continue to work via get_ollama_client() which
delegates here transparently.
"""

import time
from functools import lru_cache
from typing import AsyncIterator, Dict, List, Optional, Tuple

import structlog

from app.infrastructure.llm_router import get_llm_router
from app.models.llm import parse_provider_model

logger = structlog.get_logger(__name__)


class UnifiedLLMClient:
    """Routes LLM calls to the best provider with fallback and cost tracking."""

    async def chat(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """Execute chat with automatic provider routing.

        Model resolution:
        1. Explicit model param (can be 'provider/model' or just 'model')
        2. Task type routing via LLM router
        3. Router default model
        """
        msgs = self._build_messages(prompt, messages, system)

        provider_name, model_name, fallbacks = self._resolve(model, task_type)

        # Budget check — force Ollama if budget exceeded for paid providers
        if provider_name != "ollama":
            provider_obj = self._get_provider(provider_name)
            est_tokens = sum(len(m.get("content", "")) for m in msgs) // 4
            est_cost = provider_obj.estimate_cost(est_tokens, est_tokens // 2, model_name)
            if not get_llm_router().check_budget(est_cost):
                logger.warning(
                    "llm_budget_exceeded_forcing_ollama",
                    provider=provider_name,
                    estimated_cost=est_cost,
                    remaining=get_llm_router().get_remaining_budget(),
                )
                provider_name, model_name = "ollama", "qwen3:8b"
                fallbacks = []

        return await self._execute_with_fallbacks(
            provider_name, model_name, fallbacks,
            msgs, task_type, temperature, max_tokens,
        )

    async def chat_stream(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Streaming chat. Yields content chunks."""
        msgs = self._build_messages(prompt, messages, system)
        provider_name, model_name, _ = self._resolve(model, task_type)

        provider = self._get_provider(provider_name)
        async for chunk in provider.chat_stream(
            msgs, model_name, temperature, max_tokens,
        ):
            yield chunk

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        prompt: str,
        messages: Optional[List[Dict[str, str]]],
        system: Optional[str],
    ) -> List[Dict[str, str]]:
        if messages is not None:
            return messages
        result = []
        if system:
            result.append({"role": "system", "content": system})
        if prompt:
            result.append({"role": "user", "content": prompt})
        return result

    def _resolve(
        self,
        model: Optional[str],
        task_type: Optional[str],
    ) -> Tuple[str, str, List[Tuple[str, str]]]:
        """Resolve provider, model, and fallbacks."""
        if model:
            provider, model_name = parse_provider_model(model)
            # Get fallbacks from router if task_type provided
            _, _, fallbacks = get_llm_router().resolve_provider_model(task_type)
            return provider, model_name, fallbacks

        return get_llm_router().resolve_provider_model(task_type)

    def _get_provider(self, name: str):
        from app.infrastructure.llm_providers import get_provider
        return get_provider(name)

    async def _execute_with_fallbacks(
        self,
        provider_name: str,
        model_name: str,
        fallbacks: List[Tuple[str, str]],
        messages: List[Dict[str, str]],
        task_type: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Try primary provider, then fallback chain on failure."""
        last_error = None

        # Try primary
        try:
            return await self._call_provider(
                provider_name, model_name, messages,
                task_type, temperature, max_tokens,
            )
        except Exception as e:
            last_error = e
            logger.warning(
                "llm_primary_failed",
                provider=provider_name,
                model=model_name,
                error=str(e),
            )

        # Try fallbacks
        for fb_provider, fb_model in fallbacks:
            try:
                logger.info("llm_fallback_attempt", provider=fb_provider, model=fb_model)
                return await self._call_provider(
                    fb_provider, fb_model, messages,
                    task_type, temperature, max_tokens,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "llm_fallback_failed",
                    provider=fb_provider,
                    model=fb_model,
                    error=str(e),
                )

        raise Exception(f"All LLM providers failed. Last error: {last_error}")

    async def _call_provider(
        self,
        provider_name: str,
        model_name: str,
        messages: List[Dict[str, str]],
        task_type: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call a specific provider with metrics + cost tracking."""
        provider = self._get_provider(provider_name)
        t0 = time.monotonic()
        prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        success = True
        error_msg = None
        result = ""

        try:
            result = await provider.chat(
                messages=messages,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return result
        except Exception as e:
            success = False
            error_msg = str(e)
            raise
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000
            completion_tokens = len(result) // 4 if result else 0
            cost = provider.estimate_cost(prompt_tokens, completion_tokens, model_name)

            # Record spend
            if cost > 0:
                try:
                    await get_llm_router().record_spend(cost)
                except Exception:
                    pass

            # Record to DB (fire-and-forget)
            try:
                await self._record_usage(
                    provider_name, model_name, task_type,
                    prompt_tokens, completion_tokens, cost,
                    elapsed_ms, success, error_msg,
                )
            except Exception:
                pass

            # Record to metrics service
            try:
                from app.services.metrics_service import get_metrics_service
                metrics = get_metrics_service()
                metrics.record("llm_response_time", elapsed_ms, {"provider": provider_name})
                metrics.increment("llm_requests", {"provider": provider_name, "success": str(success)})
            except Exception:
                pass

    async def _record_usage(
        self,
        provider: str,
        model: str,
        task_type: Optional[str],
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        latency_ms: float,
        success: bool,
        error_message: Optional[str],
    ):
        """Persist usage record to PostgreSQL."""
        from app.infrastructure.database import get_session
        from app.db.models import LlmUsageModel

        async with get_session() as session:
            usage = LlmUsageModel(
                provider=provider,
                model=model,
                task_type=task_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
            )
            session.add(usage)


@lru_cache()
def get_unified_llm_client() -> UnifiedLLMClient:
    """Get the singleton unified LLM client."""
    return UnifiedLLMClient()
