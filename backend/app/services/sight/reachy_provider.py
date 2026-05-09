"""
ReachySightProvider — exposes the Reachy Mini's camera through the
SightProvider interface by proxying host_agent's `/camera/*` endpoints.

Zero-api runs in Docker and doesn't own the USB device; the host_agent
(on the Windows host) does. We read through it, which has
the nice side effect that the same camera feed is shared with the
ReachyCameraViewer UI and the vision pipeline without duplicate hardware
contention.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

import httpx
import structlog

from app.infrastructure.config import get_settings

from .base import SightProvider, SightStatus

logger = structlog.get_logger()


class ReachySightProvider(SightProvider):
    name = "reachy"

    def __init__(self) -> None:
        self._consumers = 0

    def _base(self) -> Optional[str]:
        url = getattr(get_settings(), "host_agent_url", None)
        return url.rstrip("/") if url else None

    async def status(self) -> SightStatus:
        base = self._base()
        if not base:
            return SightStatus(
                provider=self.name,
                active=False,
                last_error="ZERO_HOST_AGENT_URL not configured",
            )
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base}/camera/status")
            if resp.status_code >= 400:
                return SightStatus(
                    provider=self.name,
                    active=False,
                    last_error=f"host_agent status {resp.status_code}",
                )
            data = resp.json()
        except Exception as e:
            return SightStatus(
                provider=self.name,
                active=False,
                last_error=f"host_agent unreachable: {e}",
            )

        last_frame_ts = None
        age = data.get("age_seconds")
        if age is not None:
            import time
            last_frame_ts = time.time() - float(age)

        return SightStatus(
            provider=self.name,
            active=bool(data.get("active")),
            width=data.get("width") or None,
            height=data.get("height") or None,
            fps=data.get("fps"),
            consumers=int(data.get("consumers", 0)),
            last_frame_ts=last_frame_ts,
            last_error=data.get("last_error"),
            extra={"backend": data.get("backend")},
        )

    async def get_latest_frame(self) -> Optional[bytes]:
        from .base import _eyes_off
        if _eyes_off():
            return None
        base = self._base()
        if not base:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base}/camera/frame.jpg")
            if resp.status_code == 200 and resp.content:
                return resp.content
            logger.debug("reachy_sight_frame_non200", status=resp.status_code)
        except Exception as e:
            logger.debug("reachy_sight_frame_fetch_failed", error=str(e))
        return None

    async def mjpeg_stream(self) -> AsyncIterator[bytes]:
        """
        Prefer the host_agent's native MJPEG (real 15 fps push) over
        the polling fallback in the base class.
        """
        base = self._base()
        if not base:
            return
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", f"{base}/camera/mjpeg") as resp:
                    if resp.status_code >= 400:
                        logger.warning(
                            "reachy_sight_mjpeg_upstream_error",
                            status=resp.status_code,
                        )
                        return
                    async for chunk in resp.aiter_raw():
                        yield chunk
        except Exception as e:
            logger.warning("reachy_sight_mjpeg_proxy_error", error=str(e))
            return
