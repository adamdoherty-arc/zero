"""
Bifrost gateway client.

Bifrost (maximhq/bifrost) is a Go-written, OpenAI-compatible LLM gateway
Zero treats as **shared infrastructure** — it lives in a separate docker
service, not inside this repo. This module is the tiny client surface Zero
services use to route through it.

Behavior:

  • If ``BIFROST_GATEWAY_URL`` is set in the env, requests go to that URL.
  • If unset, ``is_available()`` returns False and every call short-circuits
    so callers can transparently fall back to their in-process provider.

The client speaks OpenAI Chat-Completions v1. Bifrost resolves provider/model
strings against its own shared-infra config (outside this Zero repo, currently
``C:\\code\\shared-infra\\bifrost\\config.json`` on the host).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# Common defaults Zero hits when running inside the docker-compose network.
_DEFAULT_TIMEOUT_S = float(os.getenv("BIFROST_TIMEOUT_S", "60"))


class BifrostClient:
    """Thin OpenAI-compatible client targeting the shared Bifrost gateway."""

    def __init__(self) -> None:
        # Read env at call time too so a runtime export works for tests.
        self._url = (os.getenv("BIFROST_GATEWAY_URL") or "").rstrip("/") or None
        self._token = os.getenv("BIFROST_TOKEN") or None
        if self._url:
            logger.info("bifrost_client_ready", url=self._url)
        else:
            logger.debug("bifrost_client_unavailable")

    def is_available(self) -> bool:
        # Re-read each call: presence is a property of env state, not init.
        return bool(os.getenv("BIFROST_GATEWAY_URL"))

    @property
    def url(self) -> Optional[str]:
        return (os.getenv("BIFROST_GATEWAY_URL") or "").rstrip("/") or None

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        token = os.getenv("BIFROST_TOKEN") or self._token
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> str:
        """One-shot chat completion. Returns the assistant content string.

        ``model`` accepts a provider/model spec or gateway alias. If the shared
        gateway defines ``hint:*`` virtual models, callers may pass those too.
        """
        url = self.url
        if not url:
            raise RuntimeError(
                "BIFROST_GATEWAY_URL is not set; Bifrost not available."
            )

        import httpx

        payload: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        endpoint = f"{url}/v1/chat/completions"
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(endpoint, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Bifrost response shape: {data}") from e

    async def health(self) -> dict[str, Any]:
        """Probe the gateway's /health (or /v1/models as a fallback)."""
        url = self.url
        if not url:
            return {"available": False, "reason": "BIFROST_GATEWAY_URL unset"}

        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            for path in ("/health", "/healthz", "/v1/models"):
                try:
                    resp = await client.get(f"{url}{path}", headers=self._headers())
                    if resp.status_code < 500:
                        return {
                            "available": True,
                            "url": url,
                            "probed": path,
                            "status_code": resp.status_code,
                        }
                except Exception as e:  # noqa: BLE001
                    last_err = str(e)
                    continue
        return {"available": False, "url": url, "reason": "no healthy endpoint", "last_error": last_err}


@lru_cache(maxsize=1)
def get_bifrost_client() -> BifrostClient:
    return BifrostClient()
