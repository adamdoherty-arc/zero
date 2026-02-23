"""
Kimi (Moonshot AI) provider — long-context specialist (128k-1M tokens).

Uses OpenAI-compatible API at https://api.moonshot.cn/v1.
Ideal for research and document analysis tasks.
Only active if ZERO_KIMI_API_KEY is set.
"""

import json
from typing import AsyncIterator, Dict, List

import httpx
import structlog

from app.infrastructure.circuit_breaker import get_circuit_breaker
from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.moonshot.cn/v1"

KIMI_PRICING = {
    "moonshot-v1-8k": {"input": 0.012, "output": 0.012},
    "moonshot-v1-32k": {"input": 0.024, "output": 0.024},
    "moonshot-v1-128k": {"input": 0.06, "output": 0.06},
}
DEFAULT_PRICING = {"input": 0.06, "output": 0.06}


class KimiProvider(BaseLLMProvider):
    """Moonshot/Kimi API provider (OpenAI-compatible, long context)."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.kimi_api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=10.0),
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=1),
        )
        self._breaker = get_circuit_breaker(
            "llm_kimi",
            failure_threshold=5,
            recovery_timeout=120.0,
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
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
            logger.warning("kimi_health_check_failed", error=str(e))
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        pricing = KIMI_PRICING.get(model, DEFAULT_PRICING)
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    @property
    def name(self) -> str:
        return "kimi"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)
