"""
FreeLLM provider — wraps shared-freellmapi as a BaseLLMProvider.

Emergency fallback tier (Bifrost-Chain-03). Aggregates ~14 free providers
(Google, Groq, Cerebras, Cloudflare, SambaNova, etc.) behind one endpoint.
Active when ZERO_FREELLM_BEARER_TOKEN is set and both Bifrost routes fail.
"""
from __future__ import annotations

from typing import AsyncIterator, Dict, List

import httpx
import structlog

from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)


class FreeLLMProvider(BaseLLMProvider):
    """Thin wrapper around FreeLLMAPIClient that implements BaseLLMProvider."""

    @property
    def name(self) -> str:
        return "freellm"

    @property
    def is_configured(self) -> bool:
        from app.infrastructure.freellm_client import is_freellm_available
        return is_freellm_available()

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 768,
        **kwargs,
    ) -> str:
        from app.infrastructure.freellm_client import get_freellm_client
        client = get_freellm_client()

        system: str | None = None
        user_parts: List[str] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            elif m["role"] == "user":
                user_parts.append(m["content"])

        prompt = user_parts[-1] if user_parts else ""
        result = await client.generate(
            prompt=prompt,
            model=model if (model and model != "auto") else "auto",
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return result.get("content", "")

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 768,
        **kwargs,
    ) -> AsyncIterator[str]:
        reply = await self.chat(messages, model, temperature, max_tokens, **kwargs)
        yield reply

    async def is_healthy(self) -> bool:
        from app.infrastructure.freellm_client import _default_base_url
        base = _default_base_url().replace("/v1", "")
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                resp = await c.get(f"{base}/health")
                return resp.status_code < 400
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, model: str) -> float:
        return 0.0
