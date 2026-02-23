"""
Abstract base class for all LLM providers.

Each provider (Ollama, Gemini, OpenRouter, HuggingFace, Kimi) implements
this interface so the UnifiedLLMClient can route to any of them.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional


class BaseLLMProvider(ABC):
    """Abstract base for LLM provider clients."""

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """Non-streaming chat completion. Returns full response text."""

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Streaming chat completion. Yields content chunks."""

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Check if provider API is reachable."""

    @abstractmethod
    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        """Estimate USD cost for a call with the given token counts."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier string (e.g., 'ollama', 'gemini')."""

    @property
    def is_configured(self) -> bool:
        """Whether this provider has valid credentials configured."""
        return True
