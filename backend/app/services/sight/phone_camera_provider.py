"""
PhoneCameraProvider — push-based sight feed from the user's phone.

The mobile PWA companion page (/m/camera) captures frames via getUserMedia
and POSTs them to /api/sight/phone_camera/ingest at ~1 fps.  Everything
downstream (VLM, ambient ticks) consumes them through the standard
SightProvider interface.

Default sight provider (ZERO_SIGHT_DEFAULT_PROVIDER) as of the Reachy
hardware removal (robot/Reachy control moved to a separate app, Zero
Studio). meta_rayban is the other option, switched via POST /api/sight/select.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import structlog

from .base import SightProvider, SightStatus

logger = structlog.get_logger()


@dataclass
class _FrameEntry:
    ts: float
    jpeg: bytes


class PhoneCameraProvider(SightProvider):
    name = "phone_camera"

    FRAME_RING_SIZE = 30  # ~30 s at 1 fps

    def __init__(self) -> None:
        self._frames: deque[_FrameEntry] = deque(maxlen=self.FRAME_RING_SIZE)
        self._lock = asyncio.Lock()
        self._new_frame_event = asyncio.Event()
        self._last_error: Optional[str] = None

    async def status(self) -> SightStatus:
        last_ts = self._frames[-1].ts if self._frames else None
        active = bool(last_ts and (time.time() - last_ts) < 10.0)
        return SightStatus(
            provider=self.name,
            active=active,
            last_frame_ts=last_ts,
            consumers=0,
            last_error=self._last_error,
            extra={
                "frame_ring_filled": len(self._frames),
                "mode": "push",
                "companion_url": "/m/camera",
            },
        )

    async def get_latest_frame(self) -> Optional[bytes]:
        from .base import _eyes_off
        if _eyes_off():
            return None
        async with self._lock:
            if not self._frames:
                return None
            return self._frames[-1].jpeg

    async def ingest_frame(self, jpeg: bytes) -> None:
        from .base import _eyes_off
        if _eyes_off():
            return
        if not jpeg:
            self._last_error = "empty frame"
            return
        if not jpeg.startswith(b"\xff\xd8"):
            self._last_error = "rejected: not a JPEG"
            logger.warning("phone_camera_ingest_non_jpeg", size=len(jpeg))
            return
        async with self._lock:
            self._frames.append(_FrameEntry(ts=time.time(), jpeg=jpeg))
        self._last_error = None
        self._new_frame_event.set()
        self._new_frame_event.clear()

    async def ingest_audio_chunk(self, pcm16_b64: str, sample_rate: int = 16000) -> None:
        pass  # phone camera is video-only for now

    async def push_notification(self, text: str) -> bool:
        return False  # no speaker on the phone companion
