"""
Bifrost provider - shared OpenAI-compatible gateway.

Bifrost is the current shared gateway for Reachy classic chat. Its model names
must include the upstream provider prefix, for example
``vllm-local/Qwen3-32B-AWQ``.
"""

from typing import AsyncIterator, Dict, List

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)


class BifrostProvider(BaseLLMProvider):
    """OpenAI-compatible client for the shared Bifrost gateway."""

    def __init__(self):
        from app.constants.models import LOCAL_CHAT
        settings = get_settings()
        self._base_url = settings.bifrost_url.rstrip("/")
        self._default_model = LOCAL_CHAT
        self._headers: dict[str, str] = {}
        if settings.bifrost_api_key:
            self._headers["Authorization"] = f"Bearer {settings.bifrost_api_key}"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.bifrost_timeout, connect=3.0),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            headers=self._headers,
        )

    def _resolve_model(self, model: str | None) -> str:
        if not model:
            return self._default_model
        if model.startswith("bifrost/"):
            return model.split("/", 1)[1]
        return model

    def _payload(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> dict:
        resolved = self._resolve_model(model)
        if resolved.startswith("moonshot/kimi-k2"):
            temperature = 1.0
        payload: dict = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if kwargs.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        if kwargs.get("reasoning") is False and resolved.startswith("vllm-local/"):
            # The local Bifrost OpenAI route forwards llama.cpp-compatible
            # template kwargs when passthrough is explicitly enabled.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    def _request_headers(self, payload: dict) -> dict[str, str]:
        headers = dict(self._headers)
        if "chat_template_kwargs" in payload:
            headers["x-bf-passthrough-extra-params"] = "true"
        return headers

    @staticmethod
    def _message_content(message: dict) -> str:
        content = message.get("content") or ""
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(item, str):
                    parts.append(item)
            content = "".join(parts)
        if isinstance(content, str) and content.strip():
            return content.strip()
        # Qwen3-thinking and Kimi-K2.6 (both reasoning models) frequently
        # return the answer in `reasoning` / `reasoning_content` with
        # `content=""`. Bifrost passes that field through. Treat reasoning
        # as the answer when content is empty, rather than raising —
        # callers (Reachy probes, RAG, etc.) expect a string, not an
        # exception about which JSON bucket the upstream populated.
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning.strip()
        raise RuntimeError("Bifrost response did not include assistant content.")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        payload = self._payload(messages, model, temperature, max_tokens, **kwargs)
        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=self._request_headers(payload),
        )
        response.raise_for_status()
        data = response.json()
        return self._message_content(data["choices"][0]["message"])

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, model, temperature, max_tokens, **kwargs)
        payload["stream"] = True
        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=self._request_headers(payload),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    return
                try:
                    import json

                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content") or ""
                    if content:
                        yield content
                except Exception as e:  # noqa: BLE001
                    logger.debug("bifrost_stream_chunk_parse_failed", error=str(e))
                    continue

    async def is_healthy(self) -> bool:
        try:
            gateway = self._base_url.removesuffix("/v1")
            response = await self._client.get(f"{gateway}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        return 0.0

    @property
    def name(self) -> str:
        return "bifrost"

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)
