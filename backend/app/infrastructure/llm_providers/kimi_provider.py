"""
Kimi (Moonshot AI) provider — paid LLM provider.

Uses OpenAI-compatible API at configurable base URL (default: api.moonshot.ai/v1).
Flagship: K2.6 (released April 2026) — thinking-optimized, 256K context.
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
    "kimi-k2.6": {"input": 0.95, "output": 4.00},
    # Kimi vision models — same K2.6 backbone with MoonViT, same pricing.
    "kimi-k2.6-vision": {"input": 0.95, "output": 4.00},
}
DEFAULT_PRICING = {"input": 0.95, "output": 4.00}


def _attach_images_to_last_user(
    messages: List[Dict[str, str]], image_urls: List[str]
) -> List[Dict]:
    """Convert the trailing user message to OpenAI content-array shape with
    image_url parts. Kimi's MoonViT accepts both http(s) URLs and base64
    data URLs.
    """
    if not image_urls:
        return messages
    out: List[Dict] = []
    for m in messages[:-1]:
        out.append(m)
    last = messages[-1] if messages else {"role": "user", "content": ""}
    if last.get("role") != "user":
        out.append(last)
        out.append({
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": u}} for u in image_urls],
        })
        return out
    text = last.get("content", "")
    parts: List[Dict] = []
    if text:
        parts.append({"type": "text", "text": text})
    for url in image_urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    out.append({"role": "user", "content": parts})
    return out


class KimiProvider(BaseLLMProvider):
    """Moonshot/Kimi API provider (OpenAI-compatible, long context).

    Supports vision when the caller passes ``image_urls=[...]`` — the trailing
    user message is converted to the OpenAI content-array shape before the
    request. K2.6 ships with a native MoonViT image encoder.
    """

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
        image_urls = kwargs.get("image_urls") or []
        msgs = _attach_images_to_last_user(messages, image_urls) if image_urls else messages

        async def _call():
            temp = max(temperature, 0.6) if thinking_mode else temperature
            # Moonshot's K2.5/K2.6 flagship models REQUIRE temperature=1 and
            # reject any other value with a 400: "invalid temperature: only 1
            # is allowed for this model". Downstream callers pass 0.0-0.6 so
            # we force the clamp here rather than pushing that knowledge to
            # every call site. Non-k2 models (moonshot-v1-*) accept normal
            # temperatures so we leave those alone.
            if model.startswith("kimi-k2"):
                temp = 1.0

            payload = {
                "model": model,
                "messages": msgs,
                "temperature": temp,
                "max_tokens": max_tokens,
            }

            if kwargs.get("json_mode"):
                payload["response_format"] = {"type": "json_object"}

            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"].get("content", "")
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
