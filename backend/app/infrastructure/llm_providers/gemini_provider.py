"""
Google Gemini provider via google-generativeai SDK.

Primary model: gemini-3.1-pro-preview ($2.00/1M input, $12.00/1M output).
Circuit breaker protected. Only active if ZERO_GEMINI_API_KEY is set.
"""

import asyncio
from typing import AsyncIterator, Dict, List

import structlog

from app.infrastructure.circuit_breaker import get_circuit_breaker
from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)

# Pricing per 1M tokens (USD)
GEMINI_PRICING = {
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3-pro-preview": {"input": 1.25, "output": 5.00},
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash-lite": {"input": 0.025, "output": 0.10},
}
DEFAULT_PRICING = {"input": 2.00, "output": 12.00}


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API provider."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._breaker = get_circuit_breaker(
            "llm_gemini",
            failure_threshold=5,
            recovery_timeout=120.0,
        )
        self._genai = None

    def _get_genai(self):
        """Lazy-init the google.generativeai module."""
        if self._genai is None:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            self._genai = genai
        return self._genai

    def _convert_messages(self, messages: List[Dict[str, str]]):
        """Convert standard messages to Gemini format.

        Gemini uses a 'contents' list with 'user' and 'model' roles.
        System messages become a system_instruction parameter.
        """
        system_parts = []
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [content]})
            else:
                contents.append({"role": "user", "parts": [content]})

        return system_parts, contents

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        genai = self._get_genai()
        system_parts, contents = self._convert_messages(messages)

        gen_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        model_kwargs = {}
        if system_parts:
            model_kwargs["system_instruction"] = "\n\n".join(system_parts)

        gen_model = genai.GenerativeModel(model, **model_kwargs)

        async def _call():
            response = await gen_model.generate_content_async(
                contents,
                generation_config=gen_config,
            )
            return response.text

        return await self._breaker.call(_call)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        genai = self._get_genai()
        system_parts, contents = self._convert_messages(messages)

        gen_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        model_kwargs = {}
        if system_parts:
            model_kwargs["system_instruction"] = "\n\n".join(system_parts)

        gen_model = genai.GenerativeModel(model, **model_kwargs)

        response = await gen_model.generate_content_async(
            contents,
            generation_config=gen_config,
            stream=True,
        )
        async for chunk in response:
            if chunk.text:
                yield chunk.text

    async def is_healthy(self) -> bool:
        if not self._api_key:
            return False
        try:
            genai = self._get_genai()
            # List models as a lightweight health check
            models = await asyncio.to_thread(lambda: list(genai.list_models()))
            return len(models) > 0
        except Exception as e:
            logger.warning("gemini_health_check_failed", error=str(e))
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        pricing = GEMINI_PRICING.get(model, DEFAULT_PRICING)
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)
