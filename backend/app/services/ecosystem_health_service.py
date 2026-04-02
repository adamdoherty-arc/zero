"""
Ecosystem Health Aggregation Service.

Monitors the health of all services in the AI ecosystem by pinging
their health endpoints and reporting status with response times.
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

ECOSYSTEM_SERVICES: Dict[str, Dict[str, str]] = {
    "zero": {"url": "http://localhost:18792", "health": "/health"},
    "ada": {"url": "http://localhost:8003", "health": "/health"},
    "legion": {"url": "http://localhost:8005", "health": "/health"},
    "ollama": {"url": "http://localhost:11434", "health": "/api/tags"},
    "reachy": {"url": "http://localhost:8000", "health": "/api/v1/status"},
}

TIMEOUT_SECONDS = 3.0


class EcosystemHealthService:
    """Checks liveness of all ecosystem services."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        return self._client

    async def check_service(self, name: str) -> Dict[str, Any]:
        """Ping a single service and return its status."""
        if name not in ECOSYSTEM_SERVICES:
            return {"status": "unknown", "error": f"Service '{name}' not registered"}

        svc = ECOSYSTEM_SERVICES[name]
        url = f"{svc['url']}{svc['health']}"
        client = await self._get_client()

        try:
            start = time.monotonic()
            resp = await client.get(url)
            elapsed_ms = round((time.monotonic() - start) * 1000)

            result: Dict[str, Any] = {
                "status": "healthy" if resp.status_code < 400 else "unhealthy",
                "response_ms": elapsed_ms,
                "status_code": resp.status_code,
            }

            # For Ollama, include model count from /api/tags response
            if name == "ollama" and resp.status_code == 200:
                try:
                    data = resp.json()
                    models = data.get("models", [])
                    result["models"] = len(models)
                except Exception:
                    pass

            return result

        except httpx.ConnectError:
            return {"status": "offline", "error": "Connection refused"}
        except httpx.TimeoutException:
            return {"status": "timeout", "error": f"No response within {TIMEOUT_SECONDS}s"}
        except Exception as exc:
            logger.warning("health_check_error", service=name, error=str(exc))
            return {"status": "error", "error": str(exc)}

    async def check_all(self) -> Dict[str, Any]:
        """Ping all services and return a status map with response times."""
        import asyncio

        names = list(ECOSYSTEM_SERVICES.keys())
        results = await asyncio.gather(
            *(self.check_service(name) for name in names)
        )
        services = dict(zip(names, results))

        return {
            "services": services,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_summary(self) -> Dict[str, Any]:
        """Overall ecosystem health summary."""
        data = await self.check_all()
        services = data["services"]

        healthy_count = sum(
            1 for s in services.values() if s.get("status") == "healthy"
        )
        total = len(services)

        if healthy_count == total:
            overall = "healthy"
        elif healthy_count == 0:
            overall = "offline"
        else:
            overall = "degraded"

        return {
            "overall": overall,
            "healthy": healthy_count,
            "total": total,
            "services": services,
            "timestamp": data["timestamp"],
        }


# --------------- singleton accessor ---------------

_instance: Optional[EcosystemHealthService] = None


def get_ecosystem_health_service() -> EcosystemHealthService:
    global _instance
    if _instance is None:
        _instance = EcosystemHealthService()
    return _instance
