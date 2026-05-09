"""
Wake-word + presence policy.

Two surfaces:

* **Wake**: pluggable wake-word backend selector (`openwakeword` vs.
  custom-trained "Hey Adam" / "Hey Reachy" model). The host_agent already
  ships an OpenWakeWord loop; this service just owns the *policy* (which
  model is active, allowed mute window) so the daemon and the dashboard
  agree.
* **Presence**: a camera-driven attention signal. When the user is
  actively looking at Reachy and speaking, suppress the wake-word check
  for a short window — the conversation is already engaged. Falls back
  to "always require wake-word" when the vision pipeline is offline.

This is intentionally a thin policy file. The host_agent reads
``snapshot_policy()`` once per second; the dashboard reads + writes via
the API router.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

POLICY_PATH = Path("workspace") / "reachy" / "wake_presence.json"


@dataclass
class WakePresencePolicy:
    wake_engine: str = "openwakeword"  # openwakeword | custom | off
    wake_model: str = "alexa"          # default OWW model id
    custom_model_path: Optional[str] = None
    presence_enabled: bool = False
    presence_grace_s: float = 8.0
    presence_camera_id: Optional[str] = None
    barge_in_grace_s: float = 1.5
    updated_at: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WakePresenceService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not POLICY_PATH.exists():
            self._write(WakePresencePolicy(updated_at=time.time()))
        # In-memory presence flag toggled by the vision pipeline.
        self._presence_seen_at: float = 0.0

    def _read(self) -> WakePresencePolicy:
        try:
            data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            return WakePresencePolicy(**data)
        except Exception:
            return WakePresencePolicy(updated_at=time.time())

    def _write(self, policy: WakePresencePolicy) -> None:
        POLICY_PATH.write_text(
            json.dumps(policy.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    async def get_policy(self) -> WakePresencePolicy:
        async with self._lock:
            return self._read()

    async def update_policy(self, patch: dict[str, Any]) -> WakePresencePolicy:
        async with self._lock:
            current = self._read()
            data = current.to_dict()
            for k, v in (patch or {}).items():
                if k in data:
                    data[k] = v
            data["updated_at"] = time.time()
            policy = WakePresencePolicy(**data)
            self._write(policy)
            logger.info("wake_presence_policy_updated", **policy.to_dict())
            return policy

    async def saw_presence(self) -> None:
        self._presence_seen_at = time.time()

    async def snapshot_policy(self) -> dict[str, Any]:
        policy = await self.get_policy()
        active_grace = (
            policy.presence_enabled
            and (time.time() - self._presence_seen_at) < policy.presence_grace_s
        )
        return {
            **policy.to_dict(),
            "presence_active": bool(active_grace),
            "wake_required": not active_grace,
        }


@lru_cache(maxsize=1)
def get_wake_presence_service() -> WakePresenceService:
    return WakePresenceService()
