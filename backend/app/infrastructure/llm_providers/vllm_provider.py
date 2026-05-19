"""
vLLM provider — local OpenAI-compatible inference server.

Runs as a Docker service (`zero-vllm-chat`). Routes through the standard
OpenAI /v1/chat/completions and /v1/embeddings endpoints, so it behaves
identically to Kimi/OpenAI-style upstreams.

Cost is always $0 (local inference).
"""

import json
import re
from typing import AsyncIterator, Dict, List, Optional

import httpx
import structlog

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_think(text: str) -> str:
    """Strip Qwen3 <think>...</think> reasoning blocks from chat output.

    Qwen3 models emit their chain-of-thought wrapped in <think> tags
    when the reasoning mode is on (the default for the Instruct variants
    since 2025). We want the user-facing content only.
    """
    if "<think>" not in text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # If the model was cut off mid-thought (no closing </think>), drop
    # everything up to the last-seen opener so we never return raw CoT.
    if "<think>" in cleaned:
        after = cleaned.rsplit("</think>", 1)
        cleaned = after[-1] if len(after) == 2 else ""
    return cleaned.lstrip()

from app.infrastructure.circuit_breaker import CircuitState, get_circuit_breaker
from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)


class VllmProvider(BaseLLMProvider):
    """Local vLLM server (OpenAI-compatible)."""

    def __init__(self):
        settings = get_settings()
        self._base_url = settings.vllm_chat_url.rstrip("/")
        self._default_model = settings.vllm_chat_model
        api_key = settings.vllm_api_key or "EMPTY"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key and api_key != "EMPTY" else {}
        # Connect timeout 2s (was 10s): we serve voice latency-critical paths,
        # and a stalled local container should fail-fast so the voice loop's
        # asyncio.wait_for(20s) ceiling isn't fighting against a TCP backoff.
        # Read timeout stays at settings.vllm_timeout (default 600s) so long
        # batch jobs that legitimately stream for minutes still work.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.vllm_timeout, connect=2.0),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            headers=headers,
        )
        self._breaker = get_circuit_breaker(
            "llm_vllm",
            failure_threshold=5,
            recovery_timeout=60.0,
        )

    def _resolve_model(self, model: Optional[str]) -> str:
        if not model:
            return self._default_model
        # Accept config entries like "vllm/qwen3-chat" or bare name. Preserve
        # gateway-style "<provider>/<model>" prefixes that the upstream
        # gateway needs to route the request — Bifrost requires
        # "vllm-local/Qwen3-32B-AWQ" verbatim, and Qwen HF IDs ("Qwen/...")
        # are also already-qualified names.
        _PASSTHROUGH_PREFIXES = ("Qwen/", "vllm-local/", "embed-local/")
        if "/" in model and not model.startswith(_PASSTHROUGH_PREFIXES):
            return model.split("/", 1)[1]
        return model

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        resolved = self._resolve_model(model)

        # Qwen3 reasoning mode is kept ON — the <think> block improves answer
        # quality on structured / content-generation tasks. The cost is ~1000
        # hidden tokens of latency per call; we budget for this below by:
        #   1. Padding max_tokens so reasoning + answer both fit.
        #   2. Stripping <think>...</think> from the returned content via
        #      _strip_think so callers get only the final answer.
        # Callers that truly want to skip reasoning (e.g. trivial classifications)
        # can pass reasoning=False explicitly.
        reasoning_on = kwargs.get("reasoning", True)
        # Clamp below the server's max-model-len so a naive caller passing e.g.
        # num_predict=16384 + 1024 reasoning pad doesn't get rejected with HTTP 400.
        # Shared-infra vllm-chat serves --max-model-len=24576; reserve headroom
        # for the prompt itself.
        MAX_OUTPUT_CEILING = 20480  # 24576 - 4096 prompt headroom
        reasoning_pad = 1024 if reasoning_on else 0
        effective_max_tokens = min(max_tokens + reasoning_pad, MAX_OUTPUT_CEILING)

        async def _call():
            payload: Dict = {
                "model": resolved,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": effective_max_tokens,
                "chat_template_kwargs": {
                    "enable_thinking": bool(reasoning_on),
                },
            }
            if kwargs.get("json_mode"):
                payload["response_format"] = {"type": "json_object"}
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            # Defensive fallback: if a gateway (Bifrost v1.5.0) strips
            # chat_template_kwargs, Qwen3.6 emits the answer into
            # reasoning_content / reasoning while leaving content empty.
            # _strip_think still removes any leaked <think> tags inline.
            msg = data["choices"][0]["message"]
            content = (
                msg.get("content")
                or msg.get("reasoning_content")
                or msg.get("reasoning")
                or ""
            )
            return _strip_think(content)

        return await self._breaker.call(_call)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        resolved = self._resolve_model(model)
        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            json={
                "model": resolved,
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
                    # Defensive fallback (matches chat() above): if the
                    # gateway strips chat_template_kwargs, the model
                    # streams its answer into reasoning_content / reasoning
                    # instead of content.
                    content = (
                        delta.get("content")
                        or delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or ""
                    )
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue

    async def is_healthy(self) -> bool:
        if self._breaker.state == CircuitState.OPEN:
            return False
        try:
            response = await self._client.get(f"{self._base_url.replace('/v1', '')}/health", timeout=3)
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
        return "vllm"

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)
