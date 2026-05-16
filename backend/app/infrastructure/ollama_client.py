"""
Shared LLM client for ZERO API.

NOTE 2026-05-14: This file is misnamed for historical reasons. Direct
Ollama HTTP access (port 11434) was removed in the Bifrost migration;
every call routes through the multi-provider UnifiedLLMClient, which
exits via the Bifrost gateway at :4445.

The public API (``get_llm_client()`` / ``get_ollama_client()``) returns
the same ``UnifiedLLMClientWrapper`` that ~20 services already depend on,
so the rename is deferred to a follow-up sweep. ``OllamaClient`` remains
as a thin shim that exposes ``embed`` / ``embed_batch`` / ``warmup`` /
``is_healthy``; all of those now use the OpenAI-compatible Bifrost
endpoint (``/v1/embeddings``, ``/v1/chat/completions``) rather than
Ollama's native ``/api/embed`` and ``/api/chat`` routes.
"""

import asyncio
import random
from functools import lru_cache
from typing import AsyncIterator, Optional, List, Dict

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.infrastructure.circuit_breaker import get_circuit_breaker

logger = structlog.get_logger(__name__)


class OllamaClient:
    """Legacy-named LLM client. Now routes via the Bifrost-backed OpenAI API.

    All ``/api/*`` paths were removed 2026-05-14. ``chat`` / ``chat_stream``
    delegate to the multi-provider system (``UnifiedLLMClient``). ``embed``
    / ``embed_batch`` hit Bifrost's OpenAI-compatible ``/v1/embeddings``
    endpoint directly — the embed_provider setting is locked to ``vllm`` /
    ``embed-local`` and the URL now points at the Bifrost gateway.
    """

    def __init__(self):
        settings = get_settings()
        # The "base" URL is the OpenAI-style /v1 root for Bifrost.
        self._base_url = settings.vllm_chat_url.rstrip("/")
        self._embed_base_url = settings.vllm_embed_url.rstrip("/")
        self._default_model = settings.vllm_chat_model
        self._default_timeout = settings.vllm_timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._breaker = get_circuit_breaker(
            "ollama_shim",
            failure_threshold=5,
            recovery_timeout=120.0,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared httpx client with connection pooling."""
        if self._client is None or self._client.is_closed:
            settings = get_settings()
            api_key = settings.vllm_api_key or "EMPTY"
            headers = (
                {"Authorization": f"Bearer {api_key}"}
                if api_key and api_key != "EMPTY"
                else {}
            )
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._default_timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=4),
                headers=headers,
            )
        return self._client

    # ------------------------------------------------------------------
    # Chat — delegated to UnifiedLLMClient (which routes via Bifrost)
    # ------------------------------------------------------------------

    async def chat(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        num_predict: int = 2048,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        keep_alive: str = "30m",
    ) -> str:
        """Delegate to UnifiedLLMClient for multi-provider routing."""
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        return await get_unified_llm_client().chat(
            prompt,
            messages=messages,
            model=model,
            task_type=task_type,
            system=system,
            temperature=temperature,
            max_tokens=num_predict,
        )

    async def chat_stream(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        num_predict: int = 2048,
        timeout: Optional[int] = None,
        keep_alive: str = "30m",
    ) -> AsyncIterator[str]:
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        async for chunk in get_unified_llm_client().chat_stream(
            prompt,
            messages=messages,
            model=model,
            task_type=task_type,
            system=system,
            temperature=temperature,
            max_tokens=num_predict,
        ):
            yield chunk

    async def chat_safe(self, prompt: str, **kwargs) -> str:
        """Like chat() but returns empty string on failure instead of raising."""
        try:
            return await self.chat(prompt, **kwargs)
        except Exception as e:
            logger.error("llm_chat_safe_failed", error=str(e))
            return ""

    async def warmup(self, model: Optional[str] = None) -> bool:
        """Send a trivial prompt to keep the upstream model warm.

        Post-migration this just exercises the Bifrost path; there is no
        local Ollama keep_alive contract any more.
        """
        try:
            result = await self.chat(
                "Reply with OK.",
                model=model,
                num_predict=20,
                timeout=180,
                max_retries=1,
            )
            logger.info("llm_warmup_complete", model=model or self._default_model, response=result[:20])
            return bool(result)
        except Exception as e:
            logger.warning("llm_warmup_failed", model=model, error=str(e))
            return False

    # ------------------------------------------------------------------
    # Embeddings — direct OpenAI-compatible call to Bifrost
    # ------------------------------------------------------------------

    async def embed(
        self,
        text: str,
        *,
        model: Optional[str] = None,
        max_retries: int = 2,
    ) -> List[float]:
        """Generate embedding vector for text via Bifrost embed-local."""
        settings = get_settings()
        embed_model = model or settings.vllm_embed_model
        return await self._embed_openai(text, embed_model, max_retries)

    async def embed_batch(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        max_retries: int = 2,
    ) -> List[List[float]]:
        """Generate embeddings for multiple texts via Bifrost embed-local."""
        settings = get_settings()
        embed_model = model or settings.vllm_embed_model
        return await self._embed_batch_openai(texts, embed_model, max_retries)

    async def embed_safe(self, text: str, **kwargs) -> Optional[List[float]]:
        """Like embed() but returns None on failure instead of raising."""
        try:
            return await self.embed(text, **kwargs)
        except Exception as e:
            logger.error("llm_embed_safe_failed", error=str(e))
            return None

    async def _embed_openai(self, text: str, model: str, max_retries: int) -> List[float]:
        settings = get_settings()
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.post(
                    f"{self._embed_base_url}/embeddings",
                    json={"model": model, "input": text, "encoding_format": "float"},
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
                entries = data.get("data", [])
                if not entries:
                    raise ValueError("Empty embeddings returned from upstream")
                vec = entries[0]["embedding"]
                target_dim = settings.embedding_dimension
                if len(vec) > target_dim:
                    # Matryoshka truncation — Qwen3-Embedding supports this.
                    vec = vec[:target_dim]
                return vec
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = (2 ** attempt) * 2 + random.uniform(0, 1)
                    logger.warning(
                        "llm_embed_retry",
                        attempt=attempt + 1,
                        delay=f"{delay:.1f}s",
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
        logger.error("llm_embed_failed", attempts=max_retries + 1, error=str(last_error))
        raise Exception(f"embed failed after {max_retries + 1} attempts: {last_error}")

    async def _embed_batch_openai(
        self, texts: List[str], model: str, max_retries: int
    ) -> List[List[float]]:
        settings = get_settings()
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.post(
                    f"{self._embed_base_url}/embeddings",
                    json={"model": model, "input": texts, "encoding_format": "float"},
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
                entries = data.get("data", [])
                if len(entries) != len(texts):
                    raise ValueError(
                        f"Expected {len(texts)} embeddings, got {len(entries)}"
                    )
                entries_sorted = sorted(entries, key=lambda e: e.get("index", 0))
                target_dim = settings.embedding_dimension
                vecs = [e["embedding"] for e in entries_sorted]
                if vecs and len(vecs[0]) > target_dim:
                    vecs = [v[:target_dim] for v in vecs]
                return vecs
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = (2 ** attempt) * 2 + random.uniform(0, 1)
                    logger.warning(
                        "llm_embed_batch_retry",
                        attempt=attempt + 1,
                        delay=f"{delay:.1f}s",
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
        logger.error(
            "llm_embed_batch_failed",
            attempts=max_retries + 1,
            count=len(texts),
            error=str(last_error),
        )
        raise Exception(f"embed_batch failed after {max_retries + 1} attempts: {last_error}")

    async def is_healthy(self) -> bool:
        """Check if the upstream gateway is reachable."""
        try:
            client = await self._get_client()
            # Bifrost serves /v1/models on the OpenAI route.
            resp = await client.get(f"{self._base_url}/models", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class UnifiedLLMClientWrapper:
    """Backward-compatible wrapper around UnifiedLLMClient.

    Exposes the same interface as the historical OllamaClient but routes
    through the multi-provider system. Existing services calling
    get_llm_client() get this wrapper transparently.
    """

    def _get_unified(self):
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        return get_unified_llm_client()

    def _get_raw_ollama(self):
        """Get the raw OllamaClient shim for embed/warmup/health ops."""
        if not hasattr(self, "_raw"):
            self._raw = OllamaClient()
        return self._raw

    async def chat(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        num_predict: int = 2048,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        keep_alive: str = "30m",
    ) -> str:
        """Delegate to UnifiedLLMClient for multi-provider routing."""
        return await self._get_unified().chat(
            prompt,
            messages=messages,
            model=model,
            task_type=task_type,
            system=system,
            temperature=temperature,
            max_tokens=num_predict,
        )

    async def chat_stream(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        num_predict: int = 2048,
        timeout: Optional[int] = None,
        keep_alive: str = "30m",
    ) -> AsyncIterator[str]:
        """Delegate streaming to UnifiedLLMClient."""
        async for chunk in self._get_unified().chat_stream(
            prompt,
            messages=messages,
            model=model,
            task_type=task_type,
            system=system,
            temperature=temperature,
            max_tokens=num_predict,
        ):
            yield chunk

    async def chat_safe(self, prompt: str, **kwargs) -> str:
        """Returns empty string on failure."""
        try:
            return await self.chat(prompt, **kwargs)
        except Exception as e:
            logger.error("unified_chat_safe_failed", error=str(e))
            return ""

    # Embed methods delegate to raw client (Bifrost OpenAI embed route)
    async def warmup(self, model: Optional[str] = None) -> bool:
        return await self._get_raw_ollama().warmup(model)

    async def embed(self, text: str, **kwargs) -> List[float]:
        return await self._get_raw_ollama().embed(text, **kwargs)

    async def embed_batch(self, texts: List[str], **kwargs) -> List[List[float]]:
        return await self._get_raw_ollama().embed_batch(texts, **kwargs)

    async def embed_safe(self, text: str, **kwargs) -> Optional[List[float]]:
        return await self._get_raw_ollama().embed_safe(text, **kwargs)

    async def is_healthy(self) -> bool:
        return await self._get_raw_ollama().is_healthy()

    async def close(self):
        if hasattr(self, "_raw"):
            await self._raw.close()


@lru_cache()
def get_llm_client() -> UnifiedLLMClientWrapper:
    """Get the unified LLM client.

    Routes calls through the multi-provider UnifiedLLMClient → Bifrost
    at :4445 → vllm-local / embed-local / moonshot upstreams.
    """
    return UnifiedLLMClientWrapper()


# Backwards-compat alias — older callers used `get_ollama_client()`. The
# Ollama-specific contract no longer holds; this just keeps imports green.
get_ollama_client = get_llm_client
