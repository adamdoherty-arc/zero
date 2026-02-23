"""
HuggingFace Inference API provider.

Uses the serverless Inference API for text generation models.
Good for specialized open models. Free tier available (rate-limited).
Only active if ZERO_HUGGINGFACE_API_KEY is set.
"""

from typing import AsyncIterator, Dict, List

import httpx
import structlog

from app.infrastructure.circuit_breaker import get_circuit_breaker
from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)

BASE_URL = "https://api-inference.huggingface.co/models"


class HuggingFaceProvider(BaseLLMProvider):
    """HuggingFace Inference API provider."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.huggingface_api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=1),
        )
        self._breaker = get_circuit_breaker(
            "llm_huggingface",
            failure_threshold=5,
            recovery_timeout=120.0,
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_prompt(self, messages: List[Dict[str, str]]) -> str:
        """Convert messages to a single prompt string for HF text generation."""
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"<|system|>\n{content}")
            elif role == "assistant":
                parts.append(f"<|assistant|>\n{content}")
            else:
                parts.append(f"<|user|>\n{content}")
        parts.append("<|assistant|>\n")
        return "\n".join(parts)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        prompt = self._build_prompt(messages)

        async def _call():
            response = await self._client.post(
                f"{BASE_URL}/{model}",
                headers=self._headers(),
                json={
                    "inputs": prompt,
                    "parameters": {
                        "temperature": temperature,
                        "max_new_tokens": max_tokens,
                        "return_full_text": False,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and data:
                return data[0].get("generated_text", "")
            return ""

        return await self._breaker.call(_call)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        # HF Inference API has limited streaming support; fall back to full call
        result = await self.chat(messages, model, temperature, max_tokens, **kwargs)
        yield result

    async def is_healthy(self) -> bool:
        if not self._api_key:
            return False
        try:
            response = await self._client.get(
                "https://huggingface.co/api/whoami-v2",
                headers=self._headers(),
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("huggingface_health_check_failed", error=str(e))
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        # Free tier for most models; PRO models ~$0.10/1M tokens
        return 0.0

    @property
    def name(self) -> str:
        return "huggingface"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)
