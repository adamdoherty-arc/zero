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
from app.infrastructure.llm_providers.ollama_provider import OllamaProvider
from app.infrastructure.llm_providers.openrouter_provider import OpenRouterProvider

logger = structlog.get_logger(__name__)


@lru_cache()
def get_provider_registry() -> Dict[str, BaseLLMProvider]:
    """Singleton registry of all LLM providers.

    Returns all providers (configured or not). Check provider.is_configured
    before using cloud providers.
    """
    providers = {
        "ollama": OllamaProvider(),
        "gemini": GeminiProvider(),
        "openrouter": OpenRouterProvider(),
        "huggingface": HuggingFaceProvider(),
        "kimi": KimiProvider(),
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
