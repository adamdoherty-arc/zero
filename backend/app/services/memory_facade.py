"""
Unified memory facade.

Zero already has five overlapping memory services. The realtime voice loop
shouldn't have to know which one to call — it should just say "remember this"
and "what does Adam know that's relevant to this turn?"

This module wraps them behind a single contract:

    facade = get_memory_facade()
    notes = await facade.recall("what did I tell you about my CPA?", k=8)
    await facade.remember(user_text, assistant_text, persona_id="default")

Backends, in fall-through order:

1. **mem0** (optional, env: ``ZERO_MEMORY_USE_MEM0=1``). When the
   ``mem0ai`` package is importable and a valid local config is present,
   recall/remember go through mem0 first. mem0 stores facts in vector +
   graph and returns scoped recall.
2. **Episodic memory** (`episodic_memory_service`) — pgvector-backed
   extraction store. Always queried.
3. **Reachy user memory** (`reachy_user_memory_service`) — JSON-backed
   per-user notes with cosine dedupe.
4. **Reachy memory blocks** (`reachy_memory_blocks`) — Letta-style
   structured blocks (human / relationship / persona).

`recall()` merges the three into one ranked list. `remember()` writes to
all three so existing surfaces continue to work and we don't lose history
during the migration.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

USE_MEM0 = os.getenv("ZERO_MEMORY_USE_MEM0", "").strip().lower() in ("1", "true", "yes")
DEFAULT_RECALL_K = int(os.getenv("ZERO_MEMORY_RECALL_K", "8"))


@dataclass
class MemoryNote:
    """A single recalled note with provenance.

    ``score`` is in [0, 1]; higher is more relevant. ``source`` identifies
    which underlying store produced the note so callers can attribute it
    in spoken replies (e.g. "I noted last week that ...").
    """

    text: str
    source: str
    score: float = 0.5
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "score": round(self.score, 4),
            "tags": list(self.tags),
            **({"extra": self.extra} if self.extra else {}),
        }


class MemoryFacade:
    """Single recall/remember contract over all of Zero's memory stores."""

    def __init__(self) -> None:
        self._mem0_client: Any = None
        self._mem0_available: Optional[bool] = None

    # ------------------------------------------------------------------
    # mem0 lazy init — gracefully no-op when the package isn't installed
    # so the facade still works on a clean checkout.
    # ------------------------------------------------------------------
    def _ensure_mem0(self) -> Any:
        if self._mem0_available is False:
            return None
        if self._mem0_client is not None:
            return self._mem0_client
        if not USE_MEM0:
            self._mem0_available = False
            return None
        try:
            from mem0 import Memory  # type: ignore
            # Default config is fine for first boot; the user can override
            # via mem0's own config file under workspace/mem0/.
            self._mem0_client = Memory()
            self._mem0_available = True
            logger.info("memory_facade_mem0_initialized")
            return self._mem0_client
        except Exception as e:
            logger.info("memory_facade_mem0_unavailable", error=str(e))
            self._mem0_available = False
            return None

    # ------------------------------------------------------------------
    # Recall — merge results from every backend, rank by score, dedupe.
    # ------------------------------------------------------------------
    async def recall(
        self,
        query: str,
        *,
        k: int = DEFAULT_RECALL_K,
        user_id: str = "adam",
        namespace: str = "reachy",
    ) -> list[MemoryNote]:
        if not query or len(query.strip()) < 2:
            return []
        notes: list[MemoryNote] = []

        # mem0 (preferred when available)
        mem0 = self._ensure_mem0()
        if mem0 is not None:
            try:
                results = await asyncio.to_thread(
                    mem0.search, query=query, user_id=user_id, limit=k
                )
                for r in (results or {}).get("results", results or []):
                    text = (r or {}).get("memory") or (r or {}).get("text") or ""
                    if not text:
                        continue
                    score = float((r or {}).get("score") or 0.5)
                    notes.append(MemoryNote(text=text, source="mem0", score=score))
            except Exception as e:
                logger.debug("memory_facade_mem0_recall_failed", error=str(e))

        # Episodic memory (pgvector)
        try:
            from app.services.episodic_memory_service import (
                get_episodic_memory_service,
            )
            ep = get_episodic_memory_service()
            try:
                hits = await ep.search(query, namespace=namespace, limit=k)
            except AttributeError:
                hits = await ep.semantic_search(query, namespace=namespace, limit=k)  # type: ignore[attr-defined]
            for h in hits or []:
                content = getattr(h, "content", None) or (
                    h.get("content") if isinstance(h, dict) else None
                )
                if not content:
                    continue
                score = float(getattr(h, "score", None) or (
                    h.get("score") if isinstance(h, dict) else 0.5
                ) or 0.5)
                tags = list(getattr(h, "tags", None) or (
                    h.get("tags") if isinstance(h, dict) else []
                ) or [])
                notes.append(MemoryNote(
                    text=content, source="episodic", score=score, tags=tags
                ))
        except Exception as e:
            logger.debug("memory_facade_episodic_recall_failed", error=str(e))

        # Reachy user memory (JSON, fast keyword)
        try:
            from app.services.reachy_user_memory_service import (
                get_reachy_user_memory_service,
            )
            ru = get_reachy_user_memory_service()
            for n in ru.relevant_notes(query, k=k) or []:
                if isinstance(n, dict):
                    text = n.get("text") or n.get("content") or ""
                    score = float(n.get("score") or 0.4)
                else:
                    text = str(n)
                    score = 0.4
                if text:
                    notes.append(MemoryNote(
                        text=text, source="reachy_user", score=score
                    ))
        except Exception as e:
            logger.debug("memory_facade_user_recall_failed", error=str(e))

        # Reachy memory blocks (always-on context)
        try:
            from app.services.reachy_memory_blocks import get_reachy_memory_blocks
            blocks = get_reachy_memory_blocks()
            try:
                summary = await blocks.summary_for_prompt()  # type: ignore[attr-defined]
            except AttributeError:
                summary = blocks.summary_for_prompt() if hasattr(blocks, "summary_for_prompt") else None
            if summary:
                notes.append(MemoryNote(
                    text=str(summary), source="blocks", score=0.7,
                    tags=["context", "always-on"],
                ))
        except Exception as e:
            logger.debug("memory_facade_blocks_recall_failed", error=str(e))

        # Dedupe + rank
        seen: set[str] = set()
        deduped: list[MemoryNote] = []
        for n in sorted(notes, key=lambda x: x.score, reverse=True):
            key = n.text.strip().lower()[:200]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(n)
            if len(deduped) >= k:
                break
        return deduped

    # ------------------------------------------------------------------
    # Remember — fan out to every backend so we don't lose data while we
    # converge on mem0.
    # ------------------------------------------------------------------
    async def remember(
        self,
        user_text: str,
        assistant_text: str,
        *,
        persona_id: str = "default",
        user_id: str = "adam",
        namespace: str = "reachy",
        gestures: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"written_to": []}

        # mem0
        mem0 = self._ensure_mem0()
        if mem0 is not None:
            try:
                await asyncio.to_thread(
                    mem0.add,
                    [
                        {"role": "user", "content": user_text or ""},
                        {"role": "assistant", "content": assistant_text or ""},
                    ],
                    user_id=user_id,
                )
                result["written_to"].append("mem0")
            except Exception as e:
                logger.debug("memory_facade_mem0_write_failed", error=str(e))

        # Episodic memory — extract from the pair
        try:
            from app.services.episodic_memory_service import (
                get_episodic_memory_service,
            )
            ep = get_episodic_memory_service()
            blob = (
                f"User: {user_text}\nAssistant: {assistant_text}"
            )
            await ep.extract_and_store(
                blob, source_type="reachy_turn", namespace=namespace,
            )
            result["written_to"].append("episodic")
        except Exception as e:
            logger.debug("memory_facade_episodic_write_failed", error=str(e))

        # Reachy user memory — full turn log + extraction every N
        try:
            from app.services.reachy_user_memory_service import (
                get_reachy_user_memory_service,
            )
            ru = get_reachy_user_memory_service()
            await ru.log_turn(
                persona_id=persona_id,
                user_text=user_text or "",
                reachy_text=assistant_text or "",
                gestures=gestures or [],
            )
            result["written_to"].append("reachy_user")
        except Exception as e:
            logger.debug("memory_facade_user_write_failed", error=str(e))

        return result

    # ------------------------------------------------------------------
    # Helpers — small utility used by the realtime handlers to inject a
    # compact, prompt-friendly memory block into the system message.
    # ------------------------------------------------------------------
    def format_for_system_prompt(self, notes: list[MemoryNote], *, max_chars: int = 1200) -> str:
        if not notes:
            return ""
        lines: list[str] = ["Relevant memory:"]
        for n in notes:
            tag = f" [{n.source}]" if n.source else ""
            lines.append(f"- {n.text}{tag}")
        joined = "\n".join(lines)
        if len(joined) > max_chars:
            joined = joined[: max_chars - 1] + "…"
        return joined


@lru_cache(maxsize=1)
def get_memory_facade() -> MemoryFacade:
    return MemoryFacade()
