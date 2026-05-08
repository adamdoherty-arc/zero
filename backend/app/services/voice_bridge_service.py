"""Voice Bridge — LiveKit Agents + Reachy pipeline (Phase 6 skeleton).

This is the scaffold for SecondBrain Phase 6. The actual voice loop runs on
the Windows host (not in Docker) because WASAPI audio is unavailable in Linux
containers. This service coordinates three moving parts:

  1. LiveKit Agents process on the host bridges mic -> STT -> Zero orchestrator
     -> TTS -> Reachy speaker. Native MCP support makes it a thin bridge.
  2. The Reachy daemon (already running on :8000 per `reachy_service`) handles
     motion + speaker playback. We call `/api/media/play_sound` for TTS output
     and `/api/move/goto` for head turns.
  3. Ask Zero's orchestration graph processes each user turn with
     `source="reachy"` in context so the pkm_node can append the turn to the
     daily note under `## Mic`.

Wake word / STT / TTS stack (not yet wired — installed on the host-side):
  - Silero VAD
  - openWakeWord ("Hey Zero")
  - faster-whisper distil-large-v3 (or NVIDIA Parakeet TDT 1.1B)
  - Kokoro 82M via Kokoro-FastAPI (:8880)
  - Barge-in: Silero-interrupt

This module exposes a thin control surface: enable / disable, push-mic-audio,
health check, log each turn. It does NOT run the ASR/TTS stack itself — that
runs on the host.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


class VoiceBridgeService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._reachy_url = self._settings.reachy_api_url.rstrip("/")
        self._enabled = False

    def enabled(self) -> bool:
        return self._enabled

    async def enable(self) -> dict[str, Any]:
        self._enabled = True
        logger.info("voice_bridge_enabled", reachy_url=self._reachy_url)
        return {"enabled": True, "reachy_url": self._reachy_url}

    async def disable(self) -> dict[str, Any]:
        self._enabled = False
        logger.info("voice_bridge_disabled")
        return {"enabled": False}

    async def health(self) -> dict[str, Any]:
        """Check Reachy daemon reachability + whether host voice stack is listening."""
        reachy_ok = False
        err = None
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self._reachy_url}/api/daemon/status")
                reachy_ok = r.status_code == 200
        except Exception as e:  # noqa: BLE001
            err = str(e)
        return {
            "enabled": self._enabled,
            "reachy_reachable": reachy_ok,
            "reachy_error": err,
            "host_stack": "not-wired",  # Phase 6: populate when LiveKit Agents host process registers
        }

    async def log_turn(
        self,
        *,
        user_utterance: str,
        zero_reply: str,
        tool_calls: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Append a voice-turn entry under the daily note's ## Mic section.

        Writes via the shared vault_writer which respects the ## Mic append-only
        marker per CLAUDE.md. Called by the host-side LiveKit process for every
        completed turn.
        """
        from app.services.vault_writer_service import get_vault_writer
        writer = get_vault_writer()
        if not writer.available():
            return {"status": "skipped", "reason": "vault_unavailable"}

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry_path = Path(self._settings.vault_daily_subdir) / f"{today}.md"
        try:
            abs_path = writer.vault_root / entry_path
            # Append to ## Mic. If file doesn't exist, skip — morning_digest_service
            # will create it on its first tick.
            if not abs_path.exists():
                return {"status": "skipped", "reason": "daily_not_created_yet"}
            existing = abs_path.read_text(encoding="utf-8")
            marker = "## Mic"
            ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
            new_entry_lines = [
                "",
                f"**[{ts}]** user: {user_utterance}",
                f"    zero: {zero_reply}",
            ]
            if tool_calls:
                new_entry_lines.append(f"    tools: {', '.join(tool_calls)}")
            entry_block = "\n".join(new_entry_lines) + "\n"

            if marker in existing:
                # insert immediately under the marker
                idx = existing.index(marker) + len(marker)
                existing = existing[:idx] + entry_block + existing[idx:]
            else:
                existing = existing.rstrip() + f"\n\n{marker}\n{entry_block}"

            abs_path.write_text(existing, encoding="utf-8")
            return {"status": "ok", "path": str(entry_path)}
        except Exception as e:  # noqa: BLE001
            logger.warning("voice_bridge_log_turn_failed", error=str(e))
            return {"status": "error", "error": str(e)}


_singleton: Optional[VoiceBridgeService] = None


def get_voice_bridge() -> VoiceBridgeService:
    global _singleton
    if _singleton is None:
        _singleton = VoiceBridgeService()
    return _singleton
