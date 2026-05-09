"""
Reachy companion memory — three tiers atop the existing pgvector stack.

Tier 1: working context (full transcript inside ``LocalRealtimeHandler``).
Tier 2: semantic long-term memory (this module — wraps ``EpisodicMemoryService``
        with a per-(user, persona) namespace and short, conversational
        prompt-injection helpers).
Tier 3: episodic summaries (this module — every N turns we distill a small JSON
        of {user_likes, shared_moments, current_mood, relationship_level}
        into ``backend/app/data/memory/episodic/{user_id}/{persona_id}.json``
        and inject it into every system prompt).

Mem0-shaped surface (``add_memory`` / ``semantic_search``) so callers do not
need to know which storage backend is doing the work today.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog

from app.services.episodic_memory_service import get_episodic_memory_service

logger = structlog.get_logger(__name__)

_SUMMARY_DIR = Path(__file__).resolve().parents[1] / "data" / "memory" / "episodic"
SUMMARY_TURN_INTERVAL = 20  # tier-3 distill every N user+assistant turns


def _namespace(user_id: str, persona_id: str) -> str:
    return f"reachy:{persona_id}:{user_id}"


@dataclass
class CompanionSummary:
    """Tier-3 structured snapshot of the relationship state."""

    user_likes: list[str]
    shared_moments: list[str]
    current_mood: str
    relationship_level: int  # 1-10

    def to_json(self) -> dict[str, Any]:
        return {
            "user_likes": self.user_likes,
            "shared_moments": self.shared_moments,
            "current_mood": self.current_mood,
            "relationship_level": self.relationship_level,
        }

    @classmethod
    def empty(cls) -> "CompanionSummary":
        return cls([], [], "neutral", 1)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "CompanionSummary":
        return cls(
            user_likes=list(raw.get("user_likes") or [])[:20],
            shared_moments=list(raw.get("shared_moments") or [])[:20],
            current_mood=str(raw.get("current_mood") or "neutral")[:32],
            relationship_level=max(1, min(10, int(raw.get("relationship_level") or 1))),
        )

    def render_block(self) -> str:
        lines = [
            f"[Relationship: level {self.relationship_level}/10, current mood {self.current_mood}]"
        ]
        if self.user_likes:
            lines.append("[User likes: " + ", ".join(self.user_likes[:8]) + "]")
        if self.shared_moments:
            lines.append("[Recent shared moments: " + "; ".join(self.shared_moments[:5]) + "]")
        return "\n".join(lines)


class ReachyMemoryService:
    """Tier-2 semantic memory + tier-3 episodic summary, scoped per persona."""

    def __init__(self) -> None:
        self._episodic = get_episodic_memory_service()
        _SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Tier 2: semantic memory ----

    async def add_memory(
        self,
        user_id: str,
        persona_id: str,
        text: str,
        *,
        importance: float = 60.0,
        tags: Optional[list[str]] = None,
    ) -> None:
        """Store a single user-utterance memory. Fire-and-forget from the
        realtime loop."""
        if not text or len(text.strip()) < 4:
            return
        await self._episodic.store_direct(
            content=text.strip(),
            source_type="reachy_realtime",
            namespace=_namespace(user_id, persona_id),
            importance=importance,
            tags=tags or ["reachy", persona_id],
            context={"user_id": user_id, "persona_id": persona_id},
        )

    async def semantic_search(
        self,
        user_id: str,
        persona_id: str,
        query: str,
        *,
        k: int = 5,
    ) -> list[str]:
        """Top-k memories most relevant to the current user message, weighted
        by recency. Returns the raw memory text (no scores) so it can be
        inlined directly into the system prompt.

        Recency weighting multiplies cosine similarity by exp(-age_days/14),
        so a 2-week-old memory roughly halves in priority versus a brand-new
        one. Stops the model from quoting last-month conversations as if they
        were today's."""
        import math
        from datetime import datetime, timezone

        # Pull a wider pool than k so the recency multiplier has room to
        # rerank — otherwise we'd just be re-ordering the same fixed top-k.
        pool = max(k * 4, 16)
        results = await self._episodic.search(
            query=query,
            namespace=_namespace(user_id, persona_id),
            limit=pool,
        )
        if not results:
            return []
        now = datetime.now(timezone.utc)
        scored: list[tuple[float, str]] = []
        for r in results:
            content = (r.memory.content or "").strip()
            if not content:
                continue
            similarity = float(getattr(r, "similarity", 0.0) or 0.0)
            created_at = getattr(r.memory, "created_at", None)
            if created_at is None:
                age_days = 0.0
            else:
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
            recency = math.exp(-age_days / 14.0)
            scored.append((similarity * recency, content))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [content for _, content in scored[:k]]

    async def render_memory_block(
        self,
        user_id: str,
        persona_id: str,
        query: str,
        *,
        k: int = 5,
    ) -> str:
        memories = await self.semantic_search(user_id, persona_id, query, k=k)
        if not memories:
            return ""
        return "[Relevant memories: " + " | ".join(m for m in memories) + "]"

    # ---- Tier 3: episodic summary ----

    def _summary_path(self, user_id: str, persona_id: str) -> Path:
        # Sanitize so a stray slash in user_id can't escape the dir.
        safe_uid = user_id.replace("/", "_").replace("..", "_")
        safe_pid = persona_id.replace("/", "_").replace("..", "_")
        d = _SUMMARY_DIR / safe_uid
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{safe_pid}.json"

    def load_summary(self, user_id: str, persona_id: str) -> CompanionSummary:
        p = self._summary_path(user_id, persona_id)
        if not p.exists():
            return CompanionSummary.empty()
        try:
            return CompanionSummary.from_json(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("reachy_summary_load_failed", path=str(p), error=str(e))
            return CompanionSummary.empty()

    def save_summary(self, user_id: str, persona_id: str, summary: CompanionSummary) -> None:
        p = self._summary_path(user_id, persona_id)
        try:
            p.write_text(json.dumps(summary.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("reachy_summary_save_failed", path=str(p), error=str(e))

    async def maybe_summarize(
        self,
        user_id: str,
        persona_id: str,
        recent_turns: list[dict[str, str]],
    ) -> Optional[CompanionSummary]:
        """Distill the last N turns into a tier-3 summary via a cheap LLM call.

        ``recent_turns`` is a list of ``{"role": "...", "content": "..."}``.
        Triggered every ``SUMMARY_TURN_INTERVAL`` turns by the session
        orchestrator. Returns the new summary on success, None on failure
        (existing summary stays).
        """
        if len(recent_turns) < 4:
            return None
        prior = self.load_summary(user_id, persona_id)
        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            llm = get_unified_llm_client()
            prompt = (
                "You are maintaining a structured relationship summary between a "
                "user and an AI companion robot. Update the summary based on the "
                "new turns below. Output ONLY a JSON object with keys: "
                "user_likes (list of short strings), shared_moments (list of "
                "short phrases capturing things you did or talked about), "
                "current_mood (one short word/phrase), relationship_level "
                "(integer 1-10, where 10 = deep trust). Keep lists ≤ 20 items.\n\n"
                f"Existing summary:\n{json.dumps(prior.to_json(), ensure_ascii=False)}\n\n"
                "Recent turns:\n"
                + "\n".join(f"{t.get('role', '')}: {t.get('content', '')}" for t in recent_turns[-40:])
            )
            updated_raw = await llm.structured_chat(
                prompt=prompt,
                system="You distill relationship state into JSON.",
                task_type="analysis",
                temperature=0.2,
                max_tokens=600,
            )
            if not isinstance(updated_raw, dict):
                return None
            updated = CompanionSummary.from_json(updated_raw)
            self.save_summary(user_id, persona_id, updated)
            return updated
        except Exception as e:
            logger.warning("reachy_summary_update_failed", error=str(e))
            return None

    def clear(self, user_id: str, persona_id: str) -> None:
        """Wipe both tier-3 summary and tier-2 episodic memories for the
        scope. Used by ``DELETE /api/reachy/realtime/memory/...``"""
        p = self._summary_path(user_id, persona_id)
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
        # Tier-2 wipe runs through the episodic service (it handles its own
        # transaction). We delete by namespace.
        # NB: episodic_memory_service does not currently expose a namespace-
        # scoped delete; we do it directly via SQLAlchemy.
        try:
            import asyncio
            asyncio.create_task(self._wipe_namespace(user_id, persona_id))
        except RuntimeError:
            # No running loop — skip; the next task (e.g. cleanup_expired) will
            # eventually catch it via TTL.
            pass

    async def _wipe_namespace(self, user_id: str, persona_id: str) -> None:
        from sqlalchemy import delete
        from app.infrastructure.database import get_session
        from app.db.models import EpisodicMemoryModel
        try:
            async with get_session() as session:
                await session.execute(
                    delete(EpisodicMemoryModel).where(
                        EpisodicMemoryModel.namespace == _namespace(user_id, persona_id)
                    )
                )
                await session.commit()
        except Exception as e:
            logger.warning("reachy_memory_wipe_failed", error=str(e))


@lru_cache()
def get_reachy_memory_service() -> ReachyMemoryService:
    return ReachyMemoryService()
