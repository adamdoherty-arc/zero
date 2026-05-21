"""F-76 — meeting transcript topic segmentation.

Splits a single meeting transcript into N topical segments by combining:

  - **silence gap** between consecutive segments (>= ``SILENCE_GAP_S``)
    → hard boundary; usually a speaker switch + new topic
  - **lexical-shift score** between adjacent windows of K segments —
    Jaccard distance on lowercased token sets after stopword removal.
    Crosses ``LEXICAL_THRESHOLD`` → boundary.
  - **minimum topic length** — segments separated by < ``MIN_TOPIC_S``
    seconds are merged forward so the timeline doesn't fragment into
    1-second slivers.

The service is intentionally embedding-free. Embeddings are great when
available but they're owned by ``meeting_vector_service`` and live in a
separate index; running them here would duplicate work. Lexical shift
on the existing transcript text gives "good enough" boundaries for the
UX without a second model in the pipeline.

Persistence: workspace JSON at ``workspace/meetings/<id>/topics.json``
keyed by segment offset. No DB migration. The frontend can render the
timeline directly from this file (proxied via /api/meetings/{id}/topics).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


SILENCE_GAP_S: float = 6.0
MIN_TOPIC_S: float = 30.0
LEXICAL_WINDOW: int = 4
LEXICAL_THRESHOLD: float = 0.75
MAX_TITLE_TOKENS: int = 6

_STOP_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for",
    "with", "is", "are", "was", "were", "be", "been", "being", "this",
    "that", "these", "those", "it", "its", "as", "at", "by", "from",
    "you", "i", "we", "they", "he", "she", "them", "us", "our", "your",
    "my", "do", "does", "did", "have", "has", "had", "will", "would",
    "could", "should", "can", "may", "might", "just", "really", "very",
    "so", "if", "then", "than", "what", "when", "where", "why", "how",
    "um", "uh", "ah", "okay", "ok", "yeah", "right", "well", "like",
    "know", "think", "going", "want", "got", "get", "say", "said",
})
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z']+")


@dataclass
class Topic:
    topic_id: int
    start_idx: int  # transcript-segment index, inclusive
    end_idx: int  # transcript-segment index, exclusive
    start_time: float
    end_time: float
    label: str  # short auto-label from top lexical-shift terms
    segment_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "start_time": round(self.start_time, 2),
            "end_time": round(self.end_time, 2),
            "label": self.label,
            "segment_count": self.segment_count,
        }


def _tokenize(text: str) -> set[str]:
    tokens = {t.lower() for t in _TOKEN_RE.findall(text or "")}
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 2}


def _jaccard_distance(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return 1.0 - (inter / union)


def _label_from_tokens(tokens: Iterable[str]) -> str:
    """Pick the top distinct content tokens by simple frequency. Falls
    back to 'topic' when no content words land in the bucket."""
    counts: dict[str, int] = {}
    for t in tokens:
        if t in _STOP_WORDS or len(t) < 3:
            continue
        counts[t] = counts.get(t, 0) + 1
    if not counts:
        return "topic"
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:MAX_TITLE_TOKENS]
    return " ".join(t for t, _ in top)


def segment_transcript(segments: list[dict[str, Any]]) -> list[Topic]:
    """Return topic boundaries for a list of transcript segments.

    ``segments`` items must have ``text``, ``start`` (seconds), and
    ``end`` (seconds). Order matters — caller pre-sorts by start time.
    """
    if not segments:
        return []
    sigs: list[set[str]] = [_tokenize(s.get("text") or "") for s in segments]
    boundaries: list[int] = [0]
    last_end = float(segments[0].get("start") or 0.0)
    for i in range(1, len(segments)):
        gap = float(segments[i].get("start") or 0.0) - float(segments[i - 1].get("end") or 0.0)
        hard = gap >= SILENCE_GAP_S
        soft = False
        if i >= LEXICAL_WINDOW and i + LEXICAL_WINDOW <= len(segments):
            window_before = set().union(*sigs[i - LEXICAL_WINDOW : i])
            window_after = set().union(*sigs[i : i + LEXICAL_WINDOW])
            soft = _jaccard_distance(window_before, window_after) >= LEXICAL_THRESHOLD
        if hard or soft:
            seg_start = float(segments[i].get("start") or 0.0)
            if seg_start - last_end >= MIN_TOPIC_S:
                boundaries.append(i)
                last_end = seg_start
    boundaries.append(len(segments))

    topics: list[Topic] = []
    for tid, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        chunk = segments[start:end]
        if not chunk:
            continue
        all_tokens: list[str] = []
        for s in chunk:
            all_tokens.extend(_TOKEN_RE.findall((s.get("text") or "").lower()))
        topics.append(
            Topic(
                topic_id=tid,
                start_idx=start,
                end_idx=end,
                start_time=float(chunk[0].get("start") or 0.0),
                end_time=float(chunk[-1].get("end") or 0.0),
                label=_label_from_tokens(all_tokens),
                segment_count=len(chunk),
            )
        )
    return topics


class MeetingTopicStore:
    """Workspace-JSON persistence so the topic timeline survives across
    process restarts without an Alembic migration. One file per meeting
    at ``workspace/meetings/<id>/topics.json``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def _path(self, meeting_id: str) -> Path:
        return get_workspace_path("meetings") / meeting_id / "topics.json"

    def write(self, meeting_id: str, topics: list[Topic]) -> dict[str, Any]:
        path = self._path(meeting_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "meeting_id": meeting_id,
            "topic_count": len(topics),
            "topics": [t.to_dict() for t in topics],
        }
        with self._lock:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(path)
        return payload

    def read(self, meeting_id: str) -> dict[str, Any] | None:
        path = self._path(meeting_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("topic_store_read_failed", error=str(exc))
            return None


@lru_cache()
def get_meeting_topic_store() -> MeetingTopicStore:
    return MeetingTopicStore()
