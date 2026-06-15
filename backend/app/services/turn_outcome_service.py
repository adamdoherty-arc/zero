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
            # Fix-90: OutcomeLearningService exposes record_outcome (not
            # record_turn/record), so the old getattr-or-None dance always
            # resolved to None and every voice turn silently skipped the
            # structured store. Map the turn onto record_outcome directly.
            # Fix-96: the TurnOutcome field is `id`, not `turn_id` — the old
            # getattr(outcome, "turn_id") wrote action_id=NULL on every row,
            # severing the link back to the JSONL turn. Use outcome.id.
            await svc.record_outcome(
                domain="voice",
                action_type="turn",
                action_id=outcome.id,
                metrics=outcome.to_dict(),
            )
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
                # Bridge the thumbs signal into the structured outcome store so
                # the calibration / reflection loop actually sees it. The voice
                # bridge wrote a BrainOutcomeRecordModel row with
                # action_id == this turn id and actual_score=None; thumbs become
                # that row's actual_score (1.0 up / 0.0 down). Best-effort: a
                # failure here must never sink the JSONL feedback write.
                try:
                    await self._bridge_feedback_score(turn_id, signal)
                except Exception as e:
                    logger.debug("turn_feedback_bridge_failed", turn_id=turn_id, error=str(e))
            return updated

    @staticmethod
    async def _bridge_feedback_score(turn_id: str, signal: str) -> None:
        """Propagate a thumbs signal onto the matching structured outcome row
        (action_id == turn_id) as its actual_score, so it reaches the
        outcome-learning / reflection store instead of dying in the JSONL."""
        # Fix-116 (LRN2): score on the 0-100 scale the aggregates use. The
        # outcome store counts a "win" as actual_score >= 60 and buckets
        # calibration in 0-100 ranges, so the old 1.0/0.0 made every thumbs_up
        # read as a near-total failure. (LRN3): also stamp a retrievable
        # `learnings` string — voice turns are recorded with no predicted/actual
        # score, so record_outcome never auto-extracts a learning for them and
        # the single human feedback signal would otherwise never reach
        # extract_learnings()/enrich_task_prompt().
        score = 100.0 if signal == "thumbs_up" else 0.0
        learning = f"User rated this turn {signal} (score {score:.0f}/100)."
        from app.infrastructure.database import get_session
        from app.db.models import BrainOutcomeRecordModel
        from sqlalchemy import update as _sql_update
        async with get_session() as session:
            await session.execute(
                _sql_update(BrainOutcomeRecordModel)
                .where(BrainOutcomeRecordModel.action_id == turn_id)
                .values(actual_score=score, learnings=learning)
            )
            await session.commit()

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
        # Scale the read window with the requested span. The router allows
        # hours up to 24*30; a hardcoded 2000-line cap silently truncated any
        # window with >2000 turns, biasing every aggregate to the most recent
        # 2000. Assume <=200 turns/hour and keep a hard ceiling.
        limit = min(50000, max(2000, hours * 200))
        recent = await self.recent(limit=limit)
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
