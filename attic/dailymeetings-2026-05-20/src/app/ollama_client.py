"""Simplified Ollama client for DailyMeetings (no LLM router, no circuit breaker)."""

import asyncio
import json
import random
import time
from typing import Optional, List, Dict

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


class OllamaClient:
    def __init__(self):
        settings = get_settings()
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._default_model = settings.ollama_model
        self._default_timeout = settings.ollama_timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._default_timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=4),
            )
        return self._client

    async def chat(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        num_predict: int = 2048,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        keep_alive: str = "30m",
    ) -> str:
        model = model or self._default_model
        effective_timeout = timeout or self._default_timeout

        if messages is None:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

        last_error = None
        for attempt in range(max_retries + 1):
            try:
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
                        },
                    },
                    timeout=effective_timeout,
                )
                response.raise_for_status()
                msg = response.json().get("message", {})
                content = msg.get("content", "")
                if not content.strip() and msg.get("thinking"):
                    content = msg["thinking"]
                return content
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = (2 ** attempt) * 2 + random.uniform(0, 1)
                    logger.warning("ollama_retry", attempt=attempt + 1, delay=f"{delay:.1f}s", error=str(e))
                    await asyncio.sleep(delay)

        raise Exception(f"Ollama call failed after {max_retries + 1} attempts: {last_error}")

    async def embed(self, text_input: str, model: Optional[str] = None) -> list[float]:
        settings = get_settings()
        model = model or settings.embedding_model
        client = await self._get_client()
        resp = await client.post(
            f"{self._base_url}/api/embed",
            json={"model": model, "input": text_input},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


_instance: OllamaClient | None = None


def get_ollama_client() -> OllamaClient:
    global _instance
    if _instance is None:
        _instance = OllamaClient()
    return _instance
