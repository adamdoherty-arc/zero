"""
Shared LLM client for ZERO API.

NOTE 2026-04-27: Ollama was retired ecosystem-wide. This file is misnamed
for historical reasons — `get_llm_client()` (canonical name) and the
backwards-compat alias `get_ollama_client()` both return a
UnifiedLLMClientWrapper that routes via the multi-provider UnifiedLLMClient,
which in turn routes through shared-litellm at :4444 to vLLM at :18800.
Direct Ollama HTTP calls are deprecated; the raw OllamaClient class below
remains as a transitional shim and will be removed in a follow-up sweep.

Provides a single async HTTP client with connection pooling, retry logic
with exponential backoff, circuit breaker integration, and keep_alive
management to prevent model unloading (legacy semantics — kept for the
transitional shim only).
"""

import asyncio
import json
import random
import time
from functools import lru_cache
from typing import AsyncIterator, Optional, List, Dict

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.infrastructure.circuit_breaker import get_circuit_breaker

logger = structlog.get_logger(__name__)


class OllamaClient:
    """Async Ollama client with connection pooling, retry, and circuit breaker.

    This is the raw Ollama HTTP client. Used internally by OllamaProvider.
    External services should use get_ollama_client() instead.
    """

    def __init__(self):
        settings = get_settings()
        self._base_url = settings.ollama_base_url.rstrip("/").replace("/v1", "")
        self._default_model = settings.ollama_model
        self._default_timeout = settings.ollama_timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._breaker = get_circuit_breaker(
            "ollama",
            failure_threshold=5,
            recovery_timeout=120.0,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared httpx client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._default_timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=4),
            )
        return self._client

    def _resolve_model(self, model: Optional[str], task_type: Optional[str]) -> str:
        """Resolve model via LLM router, explicit model, or fallback default."""
        if model:
            return model
        try:
            from app.infrastructure.llm_router import get_llm_router
            from app.models.llm import parse_provider_model
            raw = get_llm_router().resolve(task_type)
            # Strip provider prefix for direct Ollama calls
            _, model_name = parse_provider_model(raw)
            return model_name
        except Exception:
            return self._default_model

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
        """Call Ollama /api/chat with retry and circuit breaker.

        Uses /api/chat (not /api/generate) because qwen3 thinking models
        return empty responses via /api/generate.
        """
        model = self._resolve_model(model, task_type)
        effective_timeout = timeout or self._default_timeout
        self._record_gpu_usage(model)

        if messages is None:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                t0 = time.monotonic()

                async def _do_call() -> str:
                    client = await self._get_client()
                    response = await client.post(
                        f"{self._base_url}/api/chat",
                        json={
                            "model": model,
                            "messages": messages,
                            "stream": False,
                            "keep_alive": keep_alive,
                            "options": {
                                "temperature": temperature,
                                "num_predict": num_predict,
                                "num_ctx": 8192,
                            },
                        },
                        timeout=effective_timeout,
                    )
                    response.raise_for_status()
                    msg = response.json().get("message", {})
                    content = msg.get("content", "")
                    # For thinking models (qwen3), content may be empty
                    # while reasoning is in the 'thinking' field
                    if not content.strip() and msg.get("thinking"):
                        content = msg["thinking"]
                    return content

                result = await self._breaker.call(_do_call)
                # Record response time metric
                try:
                    from app.services.metrics_service import get_metrics_service
                    elapsed = time.monotonic() - t0
                    get_metrics_service().record("ollama_response_time", elapsed, {"model": model})
                    get_metrics_service().increment("ollama_requests")
                except Exception:
                    pass
                return result
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = (2 ** attempt) * 2 + random.uniform(0, 1)
                    logger.warning(
                        "ollama_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=f"{delay:.1f}s",
                        error=f"{type(e).__name__}: {e}",
                        model=model,
                    )
                    await asyncio.sleep(delay)

        logger.error(
            "ollama_call_failed",
            attempts=max_retries + 1,
            error=str(last_error),
            model=model,
        )
        raise Exception(
            f"Ollama call failed after {max_retries + 1} attempts: {last_error}"
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
        """Streaming version of chat(). Yields content chunks as they arrive."""
        model = self._resolve_model(model, task_type)
        effective_timeout = timeout or self._default_timeout
        self._record_gpu_usage(model)

        if messages is None:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

        client = await self._get_client()
        async with client.stream(
            "POST",
            f"{self._base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "keep_alive": keep_alive,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                    "num_ctx": 8192,
                },
            },
            timeout=effective_timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = data.get("message", {})
                content = msg.get("content", "")
                if content:
                    yield content
                if data.get("done", False):
                    return

    async def chat_safe(self, prompt: str, **kwargs) -> str:
        """Like chat() but returns empty string on failure instead of raising."""
        try:
            return await self.chat(prompt, **kwargs)
        except Exception as e:
            logger.error("ollama_chat_safe_failed", error=str(e))
            return ""

    async def warmup(self, model: Optional[str] = None) -> bool:
        """Load model into VRAM with a trivial prompt. Returns True on success."""
        model = self._resolve_model(model, None)
        try:
            logger.info("ollama_warmup_start", model=model)
            result = await self.chat(
                "Reply with OK. /no_think",
                model=model,
                num_predict=20,
                timeout=180,
                max_retries=1,
                keep_alive="30m",
            )
            logger.info("ollama_warmup_complete", model=model, response=result[:20])
            return bool(result)
        except Exception as e:
            logger.warning("ollama_warmup_failed", model=model, error=str(e))
            return False

    async def embed(
        self,
        text: str,
        *,
        model: Optional[str] = None,
        max_retries: int = 2,
    ) -> List[float]:
        """Generate embedding vector for text. Routes to vLLM or Ollama per settings."""
        settings = get_settings()

        if settings.embed_provider == "vllm":
            # Always use the vLLM-served model name; caller-supplied names
            # reference Ollama-side models (e.g. "nomic-embed-text-v2-moe").
            return await self._embed_vllm(text, settings.vllm_embed_model, max_retries)

        model = model or settings.embedding_model

        last_error = None
        for attempt in range(max_retries + 1):
            try:

                async def _do_embed() -> List[float]:
                    client = await self._get_client()
                    response = await client.post(
                        f"{self._base_url}/api/embed",
                        json={"model": model, "input": text},
                        timeout=60,
                    )
                    response.raise_for_status()
                    data = response.json()
                    embeddings = data.get("embeddings", [])
                    if not embeddings:
                        raise ValueError("Empty embeddings returned from Ollama")
                    return embeddings[0]

                return await self._breaker.call(_do_embed)
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = (2 ** attempt) * 2 + random.uniform(0, 1)
                    logger.warning(
                        "ollama_embed_retry",
                        attempt=attempt + 1,
                        delay=f"{delay:.1f}s",
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

        logger.error("ollama_embed_failed", attempts=max_retries + 1, error=str(last_error))
        raise Exception(f"Ollama embed failed after {max_retries + 1} attempts: {last_error}")

    async def embed_batch(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        max_retries: int = 2,
    ) -> List[List[float]]:
        """Generate embeddings for multiple texts. Routes to vLLM or Ollama per settings."""
        settings = get_settings()

        if settings.embed_provider == "vllm":
            return await self._embed_batch_vllm(texts, settings.vllm_embed_model, max_retries)

        model = model or settings.embedding_model

        last_error = None
        for attempt in range(max_retries + 1):
            try:

                async def _do_embed_batch() -> List[List[float]]:
                    client = await self._get_client()
                    response = await client.post(
                        f"{self._base_url}/api/embed",
                        json={"model": model, "input": texts},
                        timeout=120,
                    )
                    response.raise_for_status()
                    data = response.json()
                    embeddings = data.get("embeddings", [])
                    if len(embeddings) != len(texts):
                        raise ValueError(
                            f"Expected {len(texts)} embeddings, got {len(embeddings)}"
                        )
                    return embeddings

                return await self._breaker.call(_do_embed_batch)
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = (2 ** attempt) * 2 + random.uniform(0, 1)
                    logger.warning(
                        "ollama_embed_batch_retry",
                        attempt=attempt + 1,
                        delay=f"{delay:.1f}s",
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

        logger.error(
            "ollama_embed_batch_failed",
            attempts=max_retries + 1,
            count=len(texts),
            error=str(last_error),
        )
        raise Exception(
            f"Ollama embed_batch failed after {max_retries + 1} attempts: {last_error}"
        )

    async def embed_safe(self, text: str, **kwargs) -> Optional[List[float]]:
        """Like embed() but returns None on failure instead of raising."""
        try:
            return await self.embed(text, **kwargs)
        except Exception as e:
            logger.error("ollama_embed_safe_failed", error=str(e))
            return None

    # --- vLLM embed path (OpenAI-compatible) ---

    async def _embed_vllm(self, text: str, model: str, max_retries: int) -> List[float]:
        settings = get_settings()
        base = settings.vllm_embed_url.rstrip("/")
        api_key = settings.vllm_api_key or "EMPTY"
        auth_headers = {"Authorization": f"Bearer {api_key}"} if api_key and api_key != "EMPTY" else None
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.post(
                    f"{base}/embeddings",
                    json={"model": model, "input": text, "encoding_format": "float"},
                    headers=auth_headers,
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
                entries = data.get("data", [])
                if not entries:
                    raise ValueError("Empty embeddings returned from vLLM")
                vec = entries[0]["embedding"]
                target_dim = settings.embedding_dimension
                if len(vec) > target_dim:
                    # Matryoshka truncation: Qwen3-Embedding supports this natively.
                    vec = vec[:target_dim]
                return vec
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = (2 ** attempt) * 2 + random.uniform(0, 1)
                    logger.warning(
                        "vllm_embed_retry",
                        attempt=attempt + 1,
                        delay=f"{delay:.1f}s",
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
        logger.error("vllm_embed_failed", attempts=max_retries + 1, error=str(last_error))
        raise Exception(f"vLLM embed failed after {max_retries + 1} attempts: {last_error}")

    async def _embed_batch_vllm(
        self, texts: List[str], model: str, max_retries: int
    ) -> List[List[float]]:
        settings = get_settings()
        base = settings.vllm_embed_url.rstrip("/")
        api_key = settings.vllm_api_key or "EMPTY"
        auth_headers = {"Authorization": f"Bearer {api_key}"} if api_key and api_key != "EMPTY" else None
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.post(
                    f"{base}/embeddings",
                    json={"model": model, "input": texts, "encoding_format": "float"},
                    headers=auth_headers,
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
                entries = data.get("data", [])
                if len(entries) != len(texts):
                    raise ValueError(
                        f"Expected {len(texts)} embeddings, got {len(entries)}"
                    )
                # vLLM returns entries ordered by index
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
                        "vllm_embed_batch_retry",
                        attempt=attempt + 1,
                        delay=f"{delay:.1f}s",
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
        logger.error(
            "vllm_embed_batch_failed",
            attempts=max_retries + 1,
            count=len(texts),
            error=str(last_error),
        )
        raise Exception(
            f"vLLM embed_batch failed after {max_retries + 1} attempts: {last_error}"
        )

    async def is_healthy(self) -> bool:
        """Check if Ollama API is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _record_gpu_usage(self, model: str):
        """Record usage in GPU manager (fire-and-forget, non-blocking)."""
        try:
            from app.services.gpu_manager_service import get_gpu_manager_service
            svc = get_gpu_manager_service()
            svc._record_usage("zero", model)
        except Exception:
            pass  # GPU manager may not be initialized yet

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class UnifiedLLMClientWrapper:
    """Backward-compatible wrapper around UnifiedLLMClient.

    Exposes the same interface as OllamaClient but routes through the
    multi-provider system. Existing services calling get_ollama_client()
    get this wrapper transparently.
    """

    def _get_unified(self):
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        return get_unified_llm_client()

    def _get_raw_ollama(self):
        """Get raw OllamaClient for Ollama-specific ops (embed, warmup)."""
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

    # Ollama-specific methods delegate to raw client
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

    Routes calls through the multi-provider UnifiedLLMClient → shared-litellm
    at :4444 → vLLM at :18800 (Ollama retired ecosystem-wide 2026-04-27).
    """
    return UnifiedLLMClientWrapper()


# Backwards-compat alias — older callers used `get_ollama_client()`. Cleaned
# up via the 2026-04-27 retirement sweep but kept here as a one-line shim
# until every import site is migrated.
get_ollama_client = get_llm_client
