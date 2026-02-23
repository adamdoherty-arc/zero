"""
OpenRouter provider — OpenAI-compatible API supporting 100+ models.

Uses https://openrouter.ai/api/v1 with standard chat completions format.
Circuit breaker protected. Only active if ZERO_OPENROUTER_API_KEY is set.
"""

import json
from typing import AsyncIterator, Dict, List

import httpx
import structlog

from app.infrastructure.circuit_breaker import get_circuit_breaker
from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"

# Approximate pricing per 1M tokens (USD) for common models
OPENROUTER_PRICING = {
    "meta-llama/llama-4-maverick": {"input": 0.20, "output": 0.60},
    "meta-llama/llama-4-scout": {"input": 0.10, "output": 0.30},
    "anthropic/claude-3.7-sonnet": {"input": 3.00, "output": 15.00},
    "openai/gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "google/gemini-2.5-flash": {"input": 0.075, "output": 0.30},
}
DEFAULT_PRICING = {"input": 1.00, "output": 3.00}


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter API provider (OpenAI-compatible)."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.openrouter_api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
        self._breaker = get_circuit_breaker(
            "llm_openrouter",
            failure_threshold=5,
            recovery_timeout=120.0,
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://zero-ai.local",
            "X-Title": "Zero AI",
        }

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        async def _call():
            response = await self._client.post(
                f"{BASE_URL}/chat/completions",
                headers=self._headers(),
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

        return await self._breaker.call(_call)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        async with self._client.stream(
            "POST",
            f"{BASE_URL}/chat/completions",
            headers=self._headers(),
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    return
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue

    async def is_healthy(self) -> bool:
        if not self._api_key:
            return False
        try:
            response = await self._client.get(
                f"{BASE_URL}/models",
                headers=self._headers(),
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("openrouter_health_check_failed", error=str(e))
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        pricing = OPENROUTER_PRICING.get(model, DEFAULT_PRICING)
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)
