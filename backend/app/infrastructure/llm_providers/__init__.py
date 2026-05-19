"""
LLM Provider Registry.

Manages all provider instances as singletons. Only providers with
configured API keys are returned as available.

Post 2026-05-14 Bifrost migration: all cloud LLM traffic (Kimi/Moonshot)
flows through the Bifrost gateway at :4445. The standalone Gemini,
OpenRouter, HuggingFace, Kimi, MiniMax, and Ollama providers were deleted
because the new policy only permits Kimi + local Qwen + local Qwen-Embed,
all of which Bifrost speaks natively. The ``ollama``, ``kimi``, ``gemini``,
``openrouter``, ``huggingface``, and ``minimax`` keys remain as
backwards-compat aliases so callers that hardcoded those names still
resolve — they all return the same Bifrost-backed handler. The router's
default fallback chain (see ``llm_router._DEFAULT_FALLBACKS``) and the
persisted ``router_config.json`` were rewritten to use bifrost-prefixed
model names ("bifrost/moonshot/kimi-k2.6", "bifrost/vllm-local/Qwen3-32B-AWQ").
"""

from functools import lru_cache
from typing import Dict

import structlog

from app.infrastructure.llm_providers.base import BaseLLMProvider
from app.infrastructure.llm_providers.bifrost_provider import BifrostProvider
from app.infrastructure.llm_providers.vllm_provider import VllmProvider

logger = structlog.get_logger(__name__)


@lru_cache()
def get_provider_registry() -> Dict[str, BaseLLMProvider]:
    """Singleton registry of all LLM providers.

    Only two real providers exist post-migration:
      - "bifrost" — shared gateway at :4445 (Kimi + local Qwen + local Embed)
      - "vllm"    — local vLLM/Bifrost endpoint via ZERO_VLLM_CHAT_URL

    Legacy provider keys (gemini/openrouter/huggingface/kimi/minimax/ollama)
    are aliased to Bifrost so existing callers don't crash; the upstream
    model name they pass through is what determines actual routing. Any
    such call that names a model Bifrost doesn't expose will fail-fast
    with a Bifrost 400, which is the intended behaviour under the new
    Kimi-only-cloud policy.
    """
    bifrost_provider = BifrostProvider()
    vllm_provider = VllmProvider()
    providers = {
        "bifrost": bifrost_provider,
        "vllm": vllm_provider,
        # Backwards-compat aliases — all route through Bifrost now.
        "ollama": vllm_provider,
        "gemini": bifrost_provider,
        "openrouter": bifrost_provider,
        "huggingface": bifrost_provider,
        "kimi": bifrost_provider,
        "minimax": bifrost_provider,
    }
    configured = [name for name, p in providers.items() if p.is_configured]
    logger.info("llm_provider_registry_initialized", configured=configured)
    return providers


def get_provider(name: str) -> BaseLLMProvider:
    """Get a specific provider by name. Raises KeyError if unknown."""
    registry = get_provider_registry()
    if name not in registry:
        raise KeyError(f"Unknown LLM provider: {name}. Available: {list(registry.keys())}")
    return registry[name]
