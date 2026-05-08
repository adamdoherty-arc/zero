"""
SightRegistry — holds all registered providers and tracks which one is
the active source of truth for ambient vision. The active provider is
what the voice loop, VLM, and scheduler tick read from.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import structlog

from .base import SightProvider, SightStatus
from .meta_rayban_provider import MetaRayBanProvider
from .reachy_provider import ReachySightProvider

logger = structlog.get_logger()


class SightRegistry:
    _instance: Optional["SightRegistry"] = None

    def __init__(self) -> None:
        self._providers: dict[str, SightProvider] = {}
        self._active_id: str = os.getenv("ZERO_SIGHT_DEFAULT_PROVIDER", "reachy")
        self._lock = asyncio.Lock()
        # Global kill switch — when True, every provider acts as if it has
        # no frames and no audio. Toggled via POST /api/sight/eyes-off.
        self._eyes_off: bool = False

        self.register(ReachySightProvider())
        self.register(MetaRayBanProvider())

    # --- Eyes-off kill switch ------------------------------------------

    @property
    def eyes_off(self) -> bool:
        return self._eyes_off

    async def set_eyes_off(self, eyes_off: bool) -> dict:
        """
        Toggle the global privacy switch. On transition to True we also
        purge any in-memory ring buffers so frames captured before the
        switch-off can't leak out.
        """
        async with self._lock:
            self._eyes_off = bool(eyes_off)
            purged = 0
            if self._eyes_off:
                for prov in self._providers.values():
                    frames = getattr(prov, "_frames", None)
                    audio = getattr(prov, "_audio", None)
                    try:
                        if frames is not None and hasattr(frames, "clear"):
                            purged += len(frames)
                            frames.clear()
                        if audio is not None and hasattr(audio, "clear"):
                            audio.clear()
                    except Exception:
                        pass
            logger.info(
                "sight_eyes_off_changed",
                eyes_off=self._eyes_off,
                purged_frames=purged,
            )
            return {"eyes_off": self._eyes_off, "purged_frames": purged}

    @classmethod
    def get_instance(cls) -> "SightRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, provider: SightProvider) -> None:
        self._providers[provider.name] = provider
        logger.info("sight_provider_registered", name=provider.name)

    def get(self, name: str) -> Optional[SightProvider]:
        return self._providers.get(name)

    def get_active(self) -> Optional[SightProvider]:
        return self._providers.get(self._active_id)

    def get_active_id(self) -> str:
        return self._active_id

    async def set_active(self, name: str) -> bool:
        async with self._lock:
            if name not in self._providers:
                return False
            self._active_id = name
            logger.info("sight_active_provider_changed", name=name)
            return True

    async def list_statuses(self) -> list[SightStatus]:
        out: list[SightStatus] = []
        for prov in self._providers.values():
            try:
                s = await prov.status()
            except Exception as e:
                s = SightStatus(provider=prov.name, active=False, last_error=str(e)[:200])
            out.append(s)
        return out


def get_sight_registry() -> SightRegistry:
    return SightRegistry.get_instance()
