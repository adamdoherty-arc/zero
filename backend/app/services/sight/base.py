"""Base class + shared types for SightProvider implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class SightStatus:
    """Snapshot of a provider's current state, serialized to the /sight/ API."""

    provider: str
    active: bool = False
    last_frame_ts: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    consumers: int = 0
    last_error: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "active": self.active,
            "last_frame_ts": self.last_frame_ts,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "consumers": self.consumers,
            "last_error": self.last_error,
            **self.extra,
        }


def _eyes_off() -> bool:
    """Cheap access to the global kill switch without circular imports."""
    try:
        from app.services.sight.registry import SightRegistry
        inst = SightRegistry._instance
        return bool(inst and inst.eyes_off)
    except Exception:
        return False


class SightProvider(ABC):
    """
    A source of images + (optionally) audio + a channel to push notifications
    back to the wearer. Providers are async-friendly. All methods must be
    safe to call concurrently — implementations guard their own state.

    Privacy: when the global eyes-off kill switch is on, `get_latest_frame`,
    `mjpeg_stream`, `subscribe_audio`, and `ingest_*` act as if the provider
    has no data. Status calls are still allowed so the UI can render the
    'paused' state.
    """

    #: Stable identifier used as the URL segment, e.g. "reachy", "meta_rayban".
    name: str = "base"

    @abstractmethod
    async def status(self) -> SightStatus:
        """Return a lightweight snapshot. Must not open hardware."""

    @abstractmethod
    async def get_latest_frame(self) -> Optional[bytes]:
        """
        Return the most recently captured JPEG frame, or None if no frame
        is available yet. Providers that lazily start capture should do so
        on the first call and reuse the worker afterwards.
        """

    async def mjpeg_stream(self) -> AsyncIterator[bytes]:
        """
        Yield `multipart/x-mixed-replace; boundary=sight-frame` chunks.
        Default implementation polls `get_latest_frame()` at ~15 fps.
        Providers that can expose a richer native stream should override.
        """
        import asyncio

        last_emitted_at = 0.0
        boundary = b"--sight-frame\r\n"
        while True:
            jpeg = await self.get_latest_frame()
            if jpeg:
                chunk = (
                    boundary
                    + b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
                    + jpeg
                    + b"\r\n"
                )
                yield chunk
                last_emitted_at = 0.0
            else:
                # Emit a tiny keep-alive so the client doesn't time out.
                last_emitted_at += 0.1
                if last_emitted_at > 5.0:
                    return
            await asyncio.sleep(1 / 15.0)

    async def ingest_frame(self, jpeg: bytes) -> None:
        """For push providers (mobile companion). Pull providers raise."""
        raise NotImplementedError(f"{self.name} is a pull provider; ingest not supported")

    async def ingest_audio_chunk(self, pcm16_b64: str, sample_rate: int) -> None:
        """For push providers that also forward mic audio."""
        raise NotImplementedError(f"{self.name} does not accept audio ingest")

    async def push_notification(self, text: str) -> bool:
        """Return True if the wearable acknowledged the TTS / text hint."""
        return False
