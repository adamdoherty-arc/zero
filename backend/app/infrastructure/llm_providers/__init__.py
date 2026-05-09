"""
LLM Provider Registry.

Manages all provider instances as singletons. Only providers with
configured API keys are returned as available.
"""

from functools import lru_cache
from typing import Dict

import structlog

from app.infrastructure.llm_providers.base import BaseLLMProvider
from app.infrastructure.llm_providers.gemini_provider import GeminiProvider
from app.infrastructure.llm_providers.huggingface_provider import HuggingFaceProvider
from app.infrastructure.llm_providers.kimi_provider import KimiProvider
from app.infrastructure.llm_providers.minimax_provider import MinimaxProvider
from app.infrastructure.llm_providers.openrouter_provider import OpenRouterProvider
from app.infrastructure.llm_providers.vllm_provider import VllmProvider

logger = structlog.get_logger(__name__)


@lru_cache()
def get_provider_registry() -> Dict[str, BaseLLMProvider]:
    """Singleton registry of all LLM providers.

    Returns all providers (configured or not). Check provider.is_configured
    before using cloud providers.

    Note 2026-04-27: OllamaProvider retired. The legacy "ollama" key resolves
    to VllmProvider as a backwards-compat alias for any caller that still
    asks for it by name.
    """
    vllm_provider = VllmProvider()
    providers = {
        "vllm": vllm_provider,
        "ollama": vllm_provider,  # legacy alias — Ollama retired 2026-04-27
        "gemini": GeminiProvider(),
        "openrouter": OpenRouterProvider(),
        "huggingface": HuggingFaceProvider(),
        "kimi": KimiProvider(),
        "minimax": MinimaxProvider(),
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
