"""F-82 — per-meeting cost telemetry.

Tracks the resources each meeting consumes so the user can decide which
ones are worth summarising vs. just keeping a transcript:

  - ``transcription_seconds``: wall-clock seconds Whisper spent
  - ``transcription_model``: e.g. ``distil-large-v3`` / ``small``
  - ``audio_seconds``: total audio length transcribed
  - ``summary_tokens``: tokens the summariser used (in + out approx)
  - ``summary_model``: the LLM used (e.g. ``qwen3-coder-next``)
  - ``summary_ms``: wall-clock for summarization
  - ``estimated_cost_usd``: rough $ estimate using cost-per-token defaults

JSONB-on-summary-row would be cleaner but doesn't need an Alembic
migration; persist to ``workspace/meetings/cost_log.json`` keyed by
meeting_id.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


# Defaults — only used when env doesn't override. Tuned conservatively
# so the dashboard tile never overstates spend.
_TOKEN_COST_USD_PER_M = {
    "default": 0.10,           # most local Ollama models = ~free; show small floor
    "kimi-k2.5": 0.60,
    "moonshot-v1-32k": 0.024,
    "gpt-5": 5.0,
    "claude-opus-4-7": 15.0,
}
_TRANSCRIPTION_SEC_PER_AUDIO_SEC = 0.05  # distil-large-v3 ~20x realtime on 5090
_TRANSCRIPTION_COST_USD_PER_SEC = 0.0    # local Whisper = $0
# Per-second cost for cloud transcription (Deepgram nova-3 = $0.0043/min)
_CLOUD_TRANSCRIPTION_COST_USD_PER_SEC = float(
    os.getenv("ZERO_CLOUD_TRANSCRIPTION_USD_PER_SEC", "0.0")
)


class MeetingCostService:
    def __init__(self, storage_dir: Path | None = None) -> None:
        base = storage_dir or get_workspace_path("meetings")
        self._dir = Path(base).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "cost_log.json"
        self._lock = threading.RLock()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("cost_log_load_failed", error=str(exc))
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def record(
        self,
        *,
        meeting_id: str,
        transcription_seconds: float | None = None,
        transcription_model: str | None = None,
        audio_seconds: float | None = None,
        summary_tokens: int | None = None,
        summary_model: str | None = None,
        summary_ms: int | None = None,
        is_cloud_transcription: bool = False,
        extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Idempotent: re-record on retranscribe/re-summarize merges into
        the existing entry. Returns the merged + cost-calculated row."""
        with self._lock:
            data = self._load()
            entry = data.get(meeting_id) or {"meeting_id": meeting_id, "recorded_at": datetime.now(timezone.utc).isoformat()}
            if transcription_seconds is not None:
                entry["transcription_seconds"] = round(float(transcription_seconds), 2)
            if transcription_model:
                entry["transcription_model"] = transcription_model
            if audio_seconds is not None:
                entry["audio_seconds"] = round(float(audio_seconds), 1)
            if summary_tokens is not None:
                entry["summary_tokens"] = int(summary_tokens)
            if summary_model:
                entry["summary_model"] = summary_model
            if summary_ms is not None:
                entry["summary_ms"] = int(summary_ms)
            entry["is_cloud_transcription"] = bool(is_cloud_transcription)
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            if extras:
                entry.setdefault("extras", {}).update(extras)
            entry["estimated_cost_usd"] = round(self._estimate(entry), 4)
            data[meeting_id] = entry
            self._save(data)
            return entry

    def get(self, meeting_id: str) -> dict[str, Any] | None:
        return self._load().get(meeting_id)

    def weekly_summary(self) -> dict[str, Any]:
        """Rollup of cost log entries from the last 7 days."""
        from datetime import timedelta

        data = self._load()
        week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        recent = [
            row for row in data.values()
            if (row.get("updated_at") or "") >= week_start
        ]
        if not recent:
            return {
                "meetings": 0,
                "total_audio_seconds": 0,
                "total_transcription_seconds": 0,
                "total_summary_tokens": 0,
                "estimated_cost_usd": 0.0,
                "by_model": {},
            }
        by_model: dict[str, int] = {}
        for row in recent:
            mdl = row.get("summary_model") or "unknown"
            by_model[mdl] = by_model.get(mdl, 0) + 1
        return {
            "meetings": len(recent),
            "total_audio_seconds": sum(int(r.get("audio_seconds") or 0) for r in recent),
            "total_transcription_seconds": sum(
                int(r.get("transcription_seconds") or 0) for r in recent
            ),
            "total_summary_tokens": sum(int(r.get("summary_tokens") or 0) for r in recent),
            "estimated_cost_usd": round(
                sum(float(r.get("estimated_cost_usd") or 0) for r in recent), 4
            ),
            "by_model": by_model,
        }

    def _estimate(self, entry: dict[str, Any]) -> float:
        cost = 0.0
        tx_sec = float(entry.get("transcription_seconds") or 0)
        if entry.get("is_cloud_transcription") and tx_sec:
            cost += tx_sec * _CLOUD_TRANSCRIPTION_COST_USD_PER_SEC
        else:
            cost += tx_sec * _TRANSCRIPTION_COST_USD_PER_SEC
        toks = int(entry.get("summary_tokens") or 0)
        if toks:
            mdl = (entry.get("summary_model") or "default").lower()
            # Pick the closest known model key (substring match).
            rate_per_m = _TOKEN_COST_USD_PER_M.get("default", 0.10)
            for key, rate in _TOKEN_COST_USD_PER_M.items():
                if key in mdl:
                    rate_per_m = rate
                    break
            cost += (toks / 1_000_000.0) * rate_per_m
        return cost


@lru_cache()
def get_meeting_cost_service() -> MeetingCostService:
    return MeetingCostService()
