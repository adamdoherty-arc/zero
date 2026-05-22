"""host_agent persisted state — Enhancement-09.

Writes a small JSON snapshot of host_agent runtime state so a restart
doesn't lose visibility into what was happening when it died. The MVP
records:

- ``active_recording``: meeting_id + device + started_at when /record/start
  succeeds, cleared on /record/stop.
- ``wake_mode``: last requested wake mode + threshold.
- ``last_heartbeat``: when this file was last written (any state change).

On startup the file is read and a warning is logged if an
``active_recording`` was left in it -- that meeting either crashed or
was left mid-flight. Operator can decide whether to re-process the WAV
or mark the meeting failed. Re-attaching to an in-flight stream is out
of scope for this MVP: a Windows audio device can't be re-acquired
mid-stream after a process death.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "workspace" / "host_agent_state.json"


class StateStore:
    """File-backed key/value snapshot. Thread-safe via a single RLock.

    Atomic writes via ``.tmp -> rename`` so partial files never confuse
    a subsequent load.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path or os.getenv("ZERO_HOST_AGENT_STATE_PATH") or _DEFAULT_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._loaded = False

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self._path.exists():
                self._data = {}
                self._loaded = True
                return {}
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("host_agent_state_load_failed", error=str(e))
                self._data = {}
            self._loaded = True
            return dict(self._data)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not self._loaded:
                self.load()
            self._data.update(patch)
            self._data["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            self._save_locked()
            return dict(self._data)

    def clear(self, *keys: str) -> dict[str, Any]:
        with self._lock:
            if not self._loaded:
                self.load()
            for k in keys:
                self._data.pop(k, None)
            self._data["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            self._save_locked()
            return dict(self._data)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if not self._loaded:
                self.load()
            return dict(self._data)

    def _save_locked(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._data, indent=2, default=str), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as e:
            logger.warning("host_agent_state_save_failed", error=str(e), path=str(self._path))


_store: Optional[StateStore] = None


def get_state_store() -> StateStore:
    global _store
    if _store is None:
        _store = StateStore()
    return _store


def log_startup_recovery() -> None:
    """At process boot, surface any state left behind by a previous run.

    Doesn't attempt to re-attach to active recordings -- Windows audio
    handles can't survive a process death. The goal is visibility: log
    a warning so the operator (and future Steward health card) knows a
    recording was orphaned.
    """
    store = get_state_store()
    snap = store.load()
    active = snap.get("active_recording")
    if active and not snap.get("recording_recovered"):
        logger.warning(
            "host_agent_active_recording_orphaned",
            meeting_id=active.get("meeting_id"),
            device_index=active.get("mic_device_index"),
            started_at=active.get("started_at"),
            note="Previous host_agent died mid-recording. WAV file (if any) may be truncated; recording row should be marked crashed or re-processed by hand.",
        )
        # Mark as recovered so we don't log it again on the next restart.
        store.update({"recording_recovered": True})
