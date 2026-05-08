"""
MetaRayBanProvider — push-based buffer fed by the future Android
companion app (Meta DAT SDK). Accepts JPEG frames + audio chunks over
HTTP and makes them readable through the SightProvider interface.

Until the Android bridge ships, this provider just sits idle. The
endpoints work today, so a hobbyist can POST frames from any client
(curl, phone, even another glasses brand via MentraOS) and everything
downstream — VLM, Reachy voice context, weekly digest — will consume
them unchanged.
"""

from __future__ import annotations

import asyncio
import base64
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


@dataclass
class _AudioEntry:
    ts: float
    pcm16: bytes
    sample_rate: int


class MetaRayBanProvider(SightProvider):
    name = "meta_rayban"

    #: Ring-buffer capacity. 30 frames at 1 fps = last 30 s of vision.
    FRAME_RING_SIZE = 30
    #: ~60 s of audio at 16 kHz pcm16 stereo = ~3.8 MB cap.
    AUDIO_RING_SIZE = 120

    def __init__(self) -> None:
        self._frames: deque[_FrameEntry] = deque(maxlen=self.FRAME_RING_SIZE)
        self._audio: deque[_AudioEntry] = deque(maxlen=self.AUDIO_RING_SIZE)
        self._lock = asyncio.Lock()
        self._new_frame_event = asyncio.Event()
        self._last_notify: Optional[str] = None
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
                "audio_ring_filled": len(self._audio),
                "last_notification": self._last_notify,
                "mode": "push",
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
            # Silently drop — the client shouldn't have to know the user
            # flipped the switch mid-stream, but we don't store anything.
            return
        if not jpeg:
            self._last_error = "empty frame ingested"
            return
        # Quick sanity check: JPEG SOI marker.
        if not jpeg.startswith(b"\xff\xd8"):
            self._last_error = "ingest rejected: not a JPEG"
            logger.warning("meta_rayban_ingest_non_jpeg", size=len(jpeg))
            return
        async with self._lock:
            self._frames.append(_FrameEntry(ts=time.time(), jpeg=jpeg))
        self._last_error = None
        self._new_frame_event.set()
        self._new_frame_event.clear()

    async def ingest_audio_chunk(self, pcm16_b64: str, sample_rate: int = 16000) -> None:
        from .base import _eyes_off
        if _eyes_off():
            return
        try:
            raw = base64.b64decode(pcm16_b64)
        except Exception as e:
            self._last_error = f"audio decode failed: {e}"
            return
        async with self._lock:
            self._audio.append(_AudioEntry(ts=time.time(), pcm16=raw, sample_rate=sample_rate))

    async def push_notification(self, text: str) -> bool:
        """
        For now, just buffer the last notification. The Android bridge
        (Phase 3) will pull it over the /sight/meta_rayban/notify
        WebSocket and speak it through the glasses open-ear speaker.
        """
        self._last_notify = text
        logger.info("meta_rayban_notification_buffered", preview=text[:80])
        return True

    async def await_next_notification(self) -> Optional[str]:
        """Used by a future WebSocket pump in the /sight router."""
        # Simple polling implementation — swap for an asyncio.Queue when
        # the real bridge lands. Returns current buffered notification.
        return self._last_notify
