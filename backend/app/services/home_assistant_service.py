"""
Minimal Home Assistant REST client.

Harvest target: community/reachy_mini_home_assistant. This module exposes
the subset of the HA REST API Zero needs to wire Reachy gestures to HA
events (doorbell rings, alarm triggers, timers, presence). It is a thin
shell — no websocket subscription, no entity caching — so it is cheap to
stand up and safe to turn off.

Configuration: set ``ZERO_HA_BASE_URL`` and ``ZERO_HA_TOKEN`` in the
backend's environment. Both are optional; without them this service is
inert and returns ``configured=False`` from get_status.

Docs: https://developers.home-assistant.io/docs/api/rest
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()


class HomeAssistantService:
    _instance: Optional["HomeAssistantService"] = None

    def __init__(self) -> None:
        self._base = (os.getenv("ZERO_HA_BASE_URL") or "").rstrip("/")
        self._token = os.getenv("ZERO_HA_TOKEN") or ""
        self._client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_instance(cls) -> "HomeAssistantService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def configured(self) -> bool:
        return bool(self._base and self._token)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        if not self.configured:
            return {"error": "home_assistant_not_configured", "configured": False}
        try:
            url = f"{self._base}{path}"
            resp = await self._get_client().request(method, url, **kwargs)
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("application/json"):
                data = resp.json()
                return data if isinstance(data, dict) else {"items": data}
            return {"ok": True}
        except httpx.HTTPStatusError as e:
            logger.warning("ha_request_failed", status=e.response.status_code, path=path)
            return {"error": "ha_request_failed", "status": e.response.status_code}
        except httpx.ConnectError:
            return {"error": "ha_unreachable", "configured": True}
        except Exception as e:
            logger.debug("ha_request_error", error=str(e))
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Public API — small deliberately
    # ------------------------------------------------------------------

    async def get_status(self) -> dict:
        if not self.configured:
            return {"configured": False}
        info = await self._request("GET", "/api/")
        return {"configured": True, "base": self._base, **info}

    async def list_states(self) -> dict:
        return await self._request("GET", "/api/states")

    async def get_state(self, entity_id: str) -> dict:
        return await self._request("GET", f"/api/states/{entity_id}")

    async def call_service(self, domain: str, service: str, data: Optional[dict] = None) -> dict:
        return await self._request(
            "POST", f"/api/services/{domain}/{service}", json=data or {}
        )


def get_home_assistant_service() -> HomeAssistantService:
    return HomeAssistantService.get_instance()
