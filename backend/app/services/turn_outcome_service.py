"""
Per-turn outcome writer for the realtime voice loop.

Every conversational turn that flows through the local/openai/gemini
realtime handlers should call ``record_turn`` after the assistant reply
finalises. The outcome is structured (latency buckets, intent label,
tool calls, error flag) so the existing outcome_learning + reflection
services can grade them in aggregate.

The writer never raises — failures are logged and swallowed so the voice
loop is never killed by analytics.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

OUTCOME_DIR = Path("workspace") / "outcomes"
OUTCOME_PATH = OUTCOME_DIR / "reachy_turns.jsonl"
MAX_LINES = 20_000


@dataclass
class TurnOutcome:
    id: str
    ts: float
    persona_id: str
    intent: str
    user_text: str
    assistant_text: str
    ttfb_ms: Optional[int]
    total_ms: Optional[int]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    feedback: Optional[str] = None  # "thumbs_up" | "thumbs_down" | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TurnOutcomeService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        OUTCOME_DIR.mkdir(parents=True, exist_ok=True)
        OUTCOME_PATH.touch(exist_ok=True)

    async def record_turn(
        self,
        *,
        persona_id: str,
        intent: str,
        user_text: str,
        assistant_text: str,
        ttfb_ms: Optional[int] = None,
        total_ms: Optional[int] = None,
        tool_calls: Optional[list[dict[str, Any]]] = None,
        error: Optional[str] = None,
    ) -> TurnOutcome:
        outcome = TurnOutcome(
            id=f"turn-{uuid.uuid4().hex[:10]}",
            ts=time.time(),
            persona_id=persona_id or "default",
            intent=intent or "direct",
            user_text=(user_text or "")[:2000],
            assistant_text=(assistant_text or "")[:4000],
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            tool_calls=list(tool_calls or []),
            error=error,
        )
        try:
            async with self._lock:
                line = json.dumps(outcome.to_dict(), separators=(",", ":")) + "\n"
                with open(OUTCOME_PATH, "a", encoding="utf-8") as f:
                    f.write(line)
                # Light-touch rotation — drop oldest lines past MAX_LINES.
                try:
                    if OUTCOME_PATH.stat().st_size > 8 * 1024 * 1024:
                        all_lines = OUTCOME_PATH.read_text(encoding="utf-8").splitlines()
                        keep = all_lines[-MAX_LINES:]
                        OUTCOME_PATH.write_text("\n".join(keep) + "\n", encoding="utf-8")
                except Exception:
                    pass
        except Exception as e:
            logger.debug("turn_outcome_write_failed", error=str(e))
        # Best-effort: also write to the structured outcome learning store so
        # the brain pipeline can grade it. Never blocks voice on failure.
        try:
            from app.services.outcome_learning_service import (
                get_outcome_learning_service,
            )
            svc = get_outcome_learning_service()
            recorder = (
                getattr(svc, "record_turn", None)
                or getattr(svc, "record", None)
            )
            if recorder is not None:
                res = recorder(outcome.to_dict())
                if asyncio.iscoroutine(res):
                    await res
        except Exception as e:
            logger.debug("outcome_learning_bridge_failed", error=str(e))
        return outcome

    async def feedback(self, turn_id: str, signal: str) -> bool:
        if signal not in ("thumbs_up", "thumbs_down"):
            return False
        async with self._lock:
            if not OUTCOME_PATH.exists():
                return False
            lines = OUTCOME_PATH.read_text(encoding="utf-8").splitlines()
            updated = False
            new_lines: list[str] = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    new_lines.append(line)
                    continue
                if rec.get("id") == turn_id:
                    rec["feedback"] = signal
                    updated = True
                new_lines.append(json.dumps(rec, separators=(",", ":")))
            if updated:
                OUTCOME_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            return updated

    async def recent(self, *, limit: int = 50) -> list[TurnOutcome]:
        async with self._lock:
            if not OUTCOME_PATH.exists():
                return []
            tail = OUTCOME_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
        out: list[TurnOutcome] = []
        for line in tail:
            try:
                rec = json.loads(line)
                out.append(TurnOutcome(**{
                    **rec,
                    "tool_calls": rec.get("tool_calls") or [],
                }))
            except Exception:
                continue
        return out

    async def trend(self, *, hours: int = 24) -> dict[str, Any]:
        cutoff = time.time() - hours * 3600
        recent = await self.recent(limit=2000)
        in_window = [r for r in recent if r.ts >= cutoff]
        n = len(in_window)
        if n == 0:
            return {"window_hours": hours, "n": 0}
        ttfb = [r.ttfb_ms for r in in_window if r.ttfb_ms is not None]
        total = [r.total_ms for r in in_window if r.total_ms is not None]
        thumbs_up = sum(1 for r in in_window if r.feedback == "thumbs_up")
        thumbs_down = sum(1 for r in in_window if r.feedback == "thumbs_down")
        errors = sum(1 for r in in_window if r.error)
        intents: dict[str, int] = {}
        for r in in_window:
            intents[r.intent] = intents.get(r.intent, 0) + 1
        return {
            "window_hours": hours,
            "n": n,
            "ttfb_ms_avg": int(sum(ttfb) / len(ttfb)) if ttfb else None,
            "total_ms_avg": int(sum(total) / len(total)) if total else None,
            "errors": errors,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "by_intent": intents,
        }


@lru_cache(maxsize=1)
def get_turn_outcome_service() -> TurnOutcomeService:
    return TurnOutcomeService()
