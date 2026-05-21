"""F-85 — cross-meeting topic linking.

Walks the workspace topic stores written by F-76 / meeting_topic_segmenter
and indexes meetings by label tokens so:

  - the prep brief for an upcoming meeting can surface "last time this
    topic came up was in <other meeting>"
  - GET /api/meetings/topics/<label> returns every meeting that touched
    a label, ranked by token-Jaccard overlap with the query label
  - the system status page can spot orphaned long-running topics that
    never resolve

Pure file walker — no DB writes, no LLM. Cached in-process for 60 s so
multiple prep-brief calls per minute share one disk scan.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z']+")
_STOP = frozenset({
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for",
    "with", "is", "are", "was", "were", "this", "that", "it", "as", "at",
    "by", "from", "you", "i", "we", "they", "us", "our", "your",
})


def _tokenize(label: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(label or "") if t.lower() not in _STOP and len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


@dataclass
class TopicHit:
    meeting_id: str
    label: str
    start_time: float
    end_time: float
    score: float = 0.0
    title: str | None = None
    when: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "label": self.label,
            "start_time": round(self.start_time, 1),
            "end_time": round(self.end_time, 1),
            "score": round(self.score, 3),
            "title": self.title,
            "when": self.when,
        }


@dataclass
class _IndexEntry:
    meeting_id: str
    label: str
    tokens: set[str]
    start_time: float
    end_time: float


class MeetingTopicLinkService:
    def __init__(self) -> None:
        self._root = get_workspace_path("meetings").resolve()
        self._index: list[_IndexEntry] | None = None
        self._index_at: float = 0.0
        self._ttl_s: float = 60.0
        self._lock = threading.RLock()

    def _build_index(self) -> list[_IndexEntry]:
        entries: list[_IndexEntry] = []
        if not self._root.exists():
            return entries
        for child in self._root.iterdir():
            if not child.is_dir():
                continue
            topics_path = child / "topics.json"
            if not topics_path.exists():
                continue
            try:
                data = json.loads(topics_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("topic_link_read_failed", path=str(topics_path), error=str(exc))
                continue
            for t in data.get("topics", []) or []:
                label = str(t.get("label") or "").strip()
                if not label:
                    continue
                entries.append(_IndexEntry(
                    meeting_id=data.get("meeting_id") or child.name,
                    label=label,
                    tokens=_tokenize(label),
                    start_time=float(t.get("start_time") or 0.0),
                    end_time=float(t.get("end_time") or 0.0),
                ))
        return entries

    def _index_or_build(self) -> list[_IndexEntry]:
        now = time.monotonic()
        with self._lock:
            if self._index is not None and now - self._index_at < self._ttl_s:
                return self._index
            self._index = self._build_index()
            self._index_at = now
            return self._index

    def invalidate(self) -> None:
        with self._lock:
            self._index = None
            self._index_at = 0.0

    async def search(
        self,
        *,
        label: str,
        exclude_meeting_id: str | None = None,
        limit: int = 8,
        min_score: float = 0.3,
    ) -> list[TopicHit]:
        """Return prior topics whose label tokens overlap with the query."""
        query_tokens = _tokenize(label)
        if not query_tokens:
            return []
        hits: list[TopicHit] = []
        for entry in self._index_or_build():
            if exclude_meeting_id and entry.meeting_id == exclude_meeting_id:
                continue
            score = _jaccard(query_tokens, entry.tokens)
            if score < min_score:
                continue
            hits.append(TopicHit(
                meeting_id=entry.meeting_id,
                label=entry.label,
                start_time=entry.start_time,
                end_time=entry.end_time,
                score=score,
            ))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    async def hydrate(self, hits: list[TopicHit]) -> list[TopicHit]:
        """Attach meeting titles + start_time strings to a hit list."""
        if not hits:
            return hits
        try:
            from sqlalchemy import select
            from app.infrastructure.database import get_session
            from app.db.models import MeetingModel  # type: ignore

            ids = list({h.meeting_id for h in hits})
            async with get_session() as db:
                rows = (
                    await db.execute(
                        select(MeetingModel).where(MeetingModel.id.in_(ids))
                    )
                ).scalars().all()
            by_id: dict[str, Any] = {row.id: row for row in rows}
            for h in hits:
                row = by_id.get(h.meeting_id)
                if row is None:
                    continue
                h.title = getattr(row, "title", None)
                start = getattr(row, "start_time", None)
                if start:
                    h.when = start.isoformat()
        except Exception as exc:
            logger.debug("topic_link_hydrate_failed", error=str(exc))
        return hits


@lru_cache()
def get_meeting_topic_link_service() -> MeetingTopicLinkService:
    return MeetingTopicLinkService()
