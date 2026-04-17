"""
MiniMax (MiniMaxAI) provider - frontier model for final-stage content polish.

Uses OpenAI-compatible API at api.minimax.io/v1.
Primary model: MiniMax-M2.7 ($0.30/1M input, $1.20/1M output, 200K context).
Agent-optimized, strong viral-instinct polish for carousel final review.
Only active if ZERO_MINIMAX_API_KEY is set.

Ported from Legion (c:/code/legion/backend/app/services/llm_clients/minimax_client.py)
with adaptations to Zero's BaseLLMProvider interface.
"""

import json
from typing import AsyncIterator, Dict, List

import httpx
import structlog

from app.infrastructure.circuit_breaker import CircuitState, get_circuit_breaker
from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)

MINIMAX_PRICING = {
    "MiniMax-M2.7": {"input": 0.30, "output": 1.20},
    "MiniMax-M2": {"input": 0.20, "output": 1.10},
}
DEFAULT_PRICING = {"input": 0.30, "output": 1.20}


def _is_insufficient_balance(response_text: str) -> bool:
    """Detect MiniMax insufficient_balance error wrapped in HTTP 429.

    Payload looks like: {"type":"error","error":{"type":"insufficient_balance_error",...}}
    Must NOT be treated as transient rate limit since retrying burns request budget.
    """
    if not response_text:
        return False
    return "insufficient_balance" in response_text.lower()


def _extract_content(choice: dict) -> str:
    """Extract content from a MiniMax response choice.

    Some MiniMax models echo reasoning into reasoning_content when content is empty.
    """
    msg = choice.get("message", {})
    content = msg.get("content", "") or ""
    if not content:
        content = msg.get("reasoning_content", "") or ""
    return content


class MinimaxProvider(BaseLLMProvider):
    """MiniMax (MiniMaxAI) API provider - OpenAI-compatible, 200K context."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.minimax_api_key
        self._base_url = settings.minimax_base_url
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=10.0),
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=1),
        )
        self._breaker = get_circuit_breaker(
            "llm_minimax",
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
            payload: Dict[str, object] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if kwargs.get("json_mode"):
                payload["response_format"] = {"type": "json_object"}

            json_schema = kwargs.get("json_schema")
            if isinstance(json_schema, dict):
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": json_schema},
                }

            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text or ""
                if exc.response.status_code == 429 and _is_insufficient_balance(body):
                    # Insufficient balance is a hard failure - do not retry.
                    logger.error(
                        "minimax_insufficient_balance",
                        model=model,
                        body=body[:200],
                    )
                    raise
                raise

            data = response.json()
            choice = data.get("choices", [{}])[0]
            return _extract_content(choice)

        return await self._breaker.call(_call)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        payload: Dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if kwargs.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}

        json_schema = kwargs.get("json_schema")
        if isinstance(json_schema, dict):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema},
            }

        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
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
                    content = (
                        delta.get("content", "")
                        or delta.get("reasoning_content", "")
                        or ""
                    )
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue

    async def is_healthy(self) -> bool:
        if not self._api_key:
            return False
        # Trust the circuit breaker for real failure detection rather than polling an endpoint.
        return self._breaker.state != CircuitState.OPEN

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        pricing = MINIMAX_PRICING.get(model, DEFAULT_PRICING)
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    @property
    def name(self) -> str:
        return "minimax"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)
