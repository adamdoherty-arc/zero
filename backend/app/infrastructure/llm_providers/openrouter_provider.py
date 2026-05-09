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
    "google/gemini-3.1-flash": {"input": 0.10, "output": 0.40},
    "google/gemini-3.1-flash-lite": {"input": 0.025, "output": 0.10},
    "google/gemini-3.1-pro": {"input": 2.00, "output": 12.00},
}
DEFAULT_PRICING = {"input": 1.00, "output": 3.00}


class RateLimitError(Exception):
    """Raised on HTTP 429. Carries parsed ``Retry-After`` so the cheap-VLM
    router can cooldown the (key, model) slot and rotate to the next.
    """

    def __init__(self, *, retry_after: float, model: str):
        super().__init__(f"openrouter 429 model={model} retry_after={retry_after}s")
        self.retry_after = retry_after
        self.model = model


def _parse_retry_after(resp) -> float:
    """Pull the cooldown duration in seconds from a 429 response.

    OpenRouter sends ``X-RateLimit-Reset`` as **milliseconds since epoch**,
    not seconds. We detect by magnitude — anything above 10^12 is ms — and
    rescale before subtracting ``time.time()``. Without this guard, slot
    cooldowns get set ~30,000 years in the future and the rotator
    permanently locks every slot.
    """
    raw = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
    if raw:
        try:
            return max(1.0, min(86400.0, float(raw)))
        except (TypeError, ValueError):
            pass
    reset = resp.headers.get("x-ratelimit-reset") or resp.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            import time
            v = float(reset)
            if v > 1e12:        # milliseconds since epoch
                v = v / 1000.0
            delta = v - time.time()
            # Clamp to a reasonable upper bound (24h) to defend against
            # any other unit confusion.
            return max(1.0, min(86400.0, delta))
        except (TypeError, ValueError):
            pass
    return 60.0


def _attach_images_to_last_user(
    messages: List[Dict[str, str]], image_urls: List[str]
) -> List[Dict]:
    """OpenAI-compatible content-array conversion. Used by Stage-8 image
    verification when routing through an OpenRouter vision model.
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
        image_urls = kwargs.get("image_urls") or []
        msgs = _attach_images_to_last_user(messages, image_urls) if image_urls else messages
        # Caller can pass an alt API key (e.g. for the carousel-V2 free pool's
        # multi-key rotation). Falls back to the singleton ``self._api_key``.
        override_key = kwargs.get("api_key_override")
        headers = self._headers()
        if override_key:
            headers["Authorization"] = f"Bearer {override_key}"

        async def _call():
            payload: Dict = {
                "model": model,
                "messages": msgs,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if kwargs.get("json_mode"):
                payload["response_format"] = {"type": "json_object"}
            response = await self._client.post(
                f"{BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            # Surface 429 with retry-after so the free-pool rotator can react
            # without the breaker tripping for every rate-limit hit.
            if response.status_code == 429:
                raise RateLimitError(
                    retry_after=_parse_retry_after(response),
                    model=model,
                )
            response.raise_for_status()
            data = response.json()
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                # Some free-tier models return malformed responses. Surface as
                # 5xx-equivalent so the rotator escalates to the next slot
                # without tripping the circuit breaker.
                raise RuntimeError(f"openrouter_malformed_response: {str(data)[:200]}")

        # Carousel V2 free-pool rotation owns its own (key, model) cooldowns
        # via ``OpenRouterFreePool``. Skipping the global circuit breaker for
        # rotation calls prevents one bad slot from blacklisting the whole
        # provider for 120s.
        if override_key:
            return await _call()
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
