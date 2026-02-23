"""
Ollama provider — wraps the existing OllamaClient singleton.

Cost is always $0 (local inference). Preserves circuit breaker,
connection pooling, retry logic, and thinking-model handling.
"""

from typing import AsyncIterator, Dict, List

from app.infrastructure.llm_providers.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """Local Ollama provider — delegates to existing OllamaClient."""

    def _get_client(self):
        # Import lazily to avoid circular imports
        from app.infrastructure.ollama_client import OllamaClient
        if not hasattr(self, "_client"):
            self._client = OllamaClient()
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        client = self._get_client()
        return await client.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            num_predict=max_tokens,
            keep_alive=kwargs.get("keep_alive", "30m"),
            max_retries=kwargs.get("max_retries", 2),
        )

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        client = self._get_client()
        async for chunk in client.chat_stream(
            messages=messages,
            model=model,
            temperature=temperature,
            num_predict=max_tokens,
            keep_alive=kwargs.get("keep_alive", "30m"),
        ):
            yield chunk

    async def is_healthy(self) -> bool:
        client = self._get_client()
        return await client.is_healthy()

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        return 0.0  # Local inference is free

    @property
    def name(self) -> str:
        return "ollama"
