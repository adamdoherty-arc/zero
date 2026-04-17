"""
Kimi (Moonshot AI) provider — paid LLM provider.

Uses OpenAI-compatible API at configurable base URL (default: api.moonshot.ai/v1).
Models: K2.5 (batch/legacy), K2 family (primary reasoning), V1 series (legacy).
Only active if ZERO_KIMI_API_KEY is set.
"""

import json
from typing import AsyncIterator, Dict, List

import httpx
import structlog

from app.infrastructure.circuit_breaker import CircuitState, get_circuit_breaker
from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)

KIMI_PRICING = {
    # K2.5 - batch API eligible, thinking enabled by default on API side
    "kimi-k2.5": {"input": 0.60, "output": 3.00},
    # K2 family - primary reasoning models, cheaper output than K2.5
    "kimi-k2-0905-preview": {"input": 0.60, "output": 2.50},
    "kimi-k2-0711-preview": {"input": 0.60, "output": 2.50},
    "kimi-k2-turbo-preview": {"input": 1.15, "output": 8.00},
    "kimi-k2-thinking": {"input": 0.60, "output": 2.50},
    "kimi-k2-thinking-turbo": {"input": 1.15, "output": 8.00},
    # V1 legacy models - official pricing from platform.kimi.ai
    "moonshot-v1-8k": {"input": 0.20, "output": 2.00},
    "moonshot-v1-32k": {"input": 1.00, "output": 3.00},
    "moonshot-v1-128k": {"input": 2.00, "output": 5.00},
}
DEFAULT_PRICING = {"input": 0.60, "output": 2.50}


class KimiProvider(BaseLLMProvider):
    """Moonshot/Kimi API provider (OpenAI-compatible, long context)."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.kimi_api_key
        self._base_url = settings.kimi_base_url
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
        thinking_mode = kwargs.get("thinking_mode", False)

        async def _call():
            # kimi-k2.5 ONLY accepts temperature=1 (API enforced since ~March 2026).
            # K2-thinking models also work best with higher temperature.
            # Other Kimi/moonshot models accept variable temperature.
            if model == "kimi-k2.5":
                temp = 1.0
            elif model.startswith("kimi-k2-thinking"):
                temp = max(temperature, 0.6)
            elif thinking_mode:
                temp = max(temperature, 0.6)
            else:
                temp = temperature

            payload = {
                "model": model,
                "messages": messages,
                "temperature": temp,
                "max_tokens": max_tokens,
            }

            if kwargs.get("json_mode"):
                payload["response_format"] = {"type": "json_object"}

            # K2.5 API defaults to thinking=enabled, so we must explicitly
            # disable it when not requested to avoid paying for thinking tokens.
            if model == "kimi-k2.5":
                if thinking_mode:
                    payload["thinking"] = {"type": "enabled"}
                else:
                    payload["thinking"] = {"type": "disabled"}

            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"].get("content", "")

            # Kimi K2.5 sometimes puts response in reasoning_content even without
            # explicit thinking mode. Always check this field when content is empty.
            if not content:
                reasoning = data["choices"][0]["message"].get("reasoning_content", "")
                if reasoning:
                    content = reasoning

            return content

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
            f"{self._base_url}/chat/completions",
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
        # Kimi /models endpoint is unreliable for health checks.
        # Trust the circuit breaker for real failure detection.
        return self._breaker.state != CircuitState.OPEN

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
