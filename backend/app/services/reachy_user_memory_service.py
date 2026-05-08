"""
Reachy user memory — cross-session durable notes about the human.

Reachy's persona_state already counts turns. This service steps further: it
logs what was actually said, then asks a light LLM to extract durable notes
about the user (preferences, facts, corrections, topics). Those notes are
injected back into the persona system prompt on future turns so Reachy
remembers across sessions.

Storage is a single JSON file under workspace/reachy/user_memory.json. Simple,
async-safe, no DB migration needed. Notes are capped at MAX_NOTES with an
aging policy that removes low-confidence unused notes first.

API:
  await mem.log_turn(persona_id, user_text, reachy_text, gestures)
  mem.relevant_notes(user_text, k=5)          # sync, fast keyword overlap
  mem.list_notes() / .add_note() / .delete_note()
  mem.stats()
  await mem.maybe_extract()                   # called every N turns
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

MEMORY_PATH = Path("workspace") / "reachy" / "user_memory.json"
MAX_TURNS = 500
MAX_NOTES = 50
EXTRACT_EVERY_N_TURNS = 5
LOW_CONF_AGE_DAYS = 7
# Cosine-similarity threshold above which two notes are treated as the same
# idea. 0.82 catches paraphrases ("prefers concise answers" vs "likes brief
# replies") with our embedding model while still rejecting unrelated notes.
DEDUP_COSINE_THRESHOLD = 0.82


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


async def _safe_embed(text: str) -> Optional[list[float]]:
    """Embed text via the shared Ollama client. Returns None on failure —
    the memory service still works in degraded mode using keyword overlap."""
    try:
        from app.infrastructure.ollama_client import get_llm_client
        client = get_llm_client()
        return await client.embed_safe(text)
    except Exception as e:
        logger.debug("memory_embed_failed", error=str(e))
        return None


# Valid categories. The LLM is allowed to pick any of these; anything else
# is normalized to "topic" on ingest.
VALID_CATEGORIES = {"preference", "fact", "correction", "topic"}


_STOP_WORDS = {
    "the", "a", "an", "i", "me", "my", "you", "your", "it", "is", "are",
    "was", "were", "do", "does", "did", "to", "of", "and", "or", "but",
    "in", "on", "at", "for", "with", "about", "that", "this", "these",
    "those", "have", "has", "had", "be", "been", "being", "if", "then",
    "so", "as", "what", "when", "where", "why", "how",
}


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}


@dataclass
class Turn:
    ts: float
    persona_id: str
    user_text: str
    reachy_text: str
    gestures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Note:
    id: str
    category: str
    text: str
    confidence: float
    learned_at: float
    last_used_at: Optional[float] = None
    uses: int = 0
    # Embedding vector for semantic similarity. Optional — notes added
    # before the embedding service existed, or when embedding fails, fall
    # back to keyword overlap.
    embedding: Optional[list[float]] = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "Note":
        # Tolerate older payloads without `embedding`.
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


class ReachyUserMemoryService:
    _instance: Optional["ReachyUserMemoryService"] = None

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._turns: list[Turn] = []
        self._notes: list[Note] = []
        self._turn_counter: int = 0
        self._load()

    @classmethod
    def get_instance(cls) -> "ReachyUserMemoryService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if not MEMORY_PATH.exists():
                return
            raw = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            self._turns = [Turn(**t) for t in (raw.get("turns") or [])][-MAX_TURNS:]
            self._notes = [Note.from_dict(n) for n in (raw.get("notes") or [])]
            self._turn_counter = int(raw.get("turn_counter", 0))
        except Exception as e:
            logger.warning("user_memory_load_failed", error=str(e))

    def _save_sync(self) -> None:
        try:
            MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "turns": [t.to_dict() for t in self._turns[-MAX_TURNS:]],
                "notes": [n.to_dict() for n in self._notes],
                "turn_counter": self._turn_counter,
            }
            MEMORY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("user_memory_save_failed", error=str(e))

    # ------------------------------------------------------------------
    # Public API — turns
    # ------------------------------------------------------------------

    async def log_turn(
        self,
        persona_id: str,
        user_text: str,
        reachy_text: str,
        gestures: Optional[list[str]] = None,
    ) -> None:
        async with self._lock:
            self._turns.append(
                Turn(
                    ts=time.time(),
                    persona_id=persona_id,
                    user_text=user_text or "",
                    reachy_text=reachy_text or "",
                    gestures=list(gestures or []),
                )
            )
            self._turns = self._turns[-MAX_TURNS:]
            self._turn_counter += 1
            self._save_sync()

    # ------------------------------------------------------------------
    # Public API — notes
    # ------------------------------------------------------------------

    def relevant_notes(
        self, user_text: str, k: int = 5, query_embedding: Optional[list[float]] = None,
    ) -> list[Note]:
        """
        Top-k notes relevant to the current turn.

        When ``query_embedding`` is supplied AND enough notes have embeddings,
        cosine similarity is the primary signal (blended with category
        weight + recency + usage). Otherwise falls back to keyword overlap
        so the system still works when the embedding service is down.
        """
        if not self._notes:
            return []
        q_tokens = _tokens(user_text)
        now = time.time()
        notes_with_embed = [n for n in self._notes if n.embedding]
        use_vectors = bool(query_embedding) and len(notes_with_embed) >= max(1, len(self._notes) // 2)

        def score(note: Note) -> float:
            cat_weight = {"preference": 0.4, "correction": 0.3, "fact": 0.2, "topic": 0.1}.get(
                note.category, 0.05
            )
            recency = max(0.0, 1.0 - (now - note.learned_at) / (86400 * 30))
            usage = min(1.0, note.uses / 5.0)

            if use_vectors and note.embedding:
                sim = _cosine(query_embedding, note.embedding)  # type: ignore[arg-type]
                base = sim * 2.0  # scale so sim=0.5 ≈ overlap=1
            else:
                n_tokens = _tokens(note.text)
                overlap = len(q_tokens & n_tokens) if n_tokens else 0
                base = overlap * 1.0 if overlap > 0 else (0.5 if note.category == "preference" else 0.0)

            return base + cat_weight + 0.3 * recency + 0.2 * usage * note.confidence

        ranked = sorted(self._notes, key=score, reverse=True)
        # Tighter threshold when using vectors since similarity is bounded.
        threshold = 0.7 if use_vectors else 0.5
        top = [n for n in ranked if score(n) > threshold][:k]

        for n in top:
            n.uses += 1
            n.last_used_at = now
        if top:
            self._save_sync()
        return top

    async def relevant_notes_async(self, user_text: str, k: int = 5) -> list[Note]:
        """Same as relevant_notes but computes a query embedding first so
        cosine similarity can be used when notes have embeddings."""
        emb = await _safe_embed(user_text) if user_text else None
        return self.relevant_notes(user_text, k=k, query_embedding=emb)

    def list_notes(self) -> list[Note]:
        return list(self._notes)

    async def add_note(
        self,
        category: str,
        text: str,
        confidence: float = 1.0,
    ) -> Note:
        """
        Add or merge a durable note. Uses embedding cosine similarity to
        dedupe against semantically-equivalent existing notes (e.g.
        "likes short replies" merges with "prefers brief answers") before
        falling back to lowercase exact match.
        """
        cat = category if category in VALID_CATEGORIES else "topic"
        text = (text or "").strip()
        if not text:
            raise ValueError("note text is empty")

        # Exact-match fast path (no embedding needed for identical text).
        existing = next(
            (n for n in self._notes if n.text.lower() == text.lower() and n.category == cat),
            None,
        )
        if existing:
            existing.confidence = max(existing.confidence, confidence)
            existing.last_used_at = time.time()
            self._save_sync()
            return existing

        # Semantic dedupe via embedding.
        emb = await _safe_embed(text)
        if emb:
            for n in self._notes:
                if n.category != cat or not n.embedding:
                    continue
                if _cosine(emb, n.embedding) >= DEDUP_COSINE_THRESHOLD:
                    n.confidence = max(n.confidence, confidence)
                    n.last_used_at = time.time()
                    # Keep the newer, often richer wording when confidence was bumped.
                    if confidence > n.confidence:
                        n.text = text
                        n.embedding = emb
                    self._save_sync()
                    logger.debug(
                        "memory_dedup_merged",
                        merged_into=n.id,
                        new_text=text[:50],
                    )
                    return n

        note = Note(
            id=uuid.uuid4().hex[:8],
            category=cat,
            text=text,
            confidence=float(confidence),
            learned_at=time.time(),
            embedding=emb,
        )
        self._notes.append(note)
        self._enforce_cap()
        self._save_sync()
        return note

    def delete_note(self, note_id: str) -> bool:
        before = len(self._notes)
        self._notes = [n for n in self._notes if n.id != note_id]
        if len(self._notes) != before:
            self._save_sync()
            return True
        return False

    def _enforce_cap(self) -> None:
        """Age out oldest unused low-confidence notes first."""
        if len(self._notes) <= MAX_NOTES:
            return
        now = time.time()

        def priority(n: Note) -> float:
            # Higher = keep. Confidence + usage + recency.
            recency = max(0.0, 1.0 - (now - n.learned_at) / (86400 * 30))
            return n.confidence + min(n.uses, 5) * 0.2 + recency * 0.3

        self._notes.sort(key=priority, reverse=True)
        self._notes = self._notes[:MAX_NOTES]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        per_persona: dict[str, int] = {}
        for t in self._turns:
            per_persona[t.persona_id] = per_persona.get(t.persona_id, 0) + 1
        return {
            "total_turns": self._turn_counter,
            "turns_retained": len(self._turns),
            "notes_count": len(self._notes),
            "per_persona": per_persona,
            "notes_by_category": {
                cat: sum(1 for n in self._notes if n.category == cat)
                for cat in VALID_CATEGORIES
            },
        }

    # ------------------------------------------------------------------
    # Extraction — LLM-driven durable-note distillation
    # ------------------------------------------------------------------

    def should_extract(self) -> bool:
        return self._turn_counter > 0 and self._turn_counter % EXTRACT_EVERY_N_TURNS == 0

    async def maybe_extract(self) -> None:
        """
        If we've crossed an extraction boundary, fire the LLM in the
        background. Safe to call after every turn.
        """
        if not self.should_extract():
            return
        recent = self._turns[-EXTRACT_EVERY_N_TURNS:]
        if not recent:
            return
        asyncio.create_task(self._extract_and_save(recent))

    async def compact(self) -> dict:
        """
        Every-6h housekeeping job. Two passes:
          1. Age out low-confidence unused notes (uses < 2, older than
             LOW_CONF_AGE_DAYS, confidence < 0.5).
          2. Re-run extraction on the last 20 turns to catch durable
             facts that slipped through the per-5-turn loop.

        Returns a summary dict so the scheduler log shows what changed.
        """
        removed = 0
        async with self._lock:
            now = time.time()
            cutoff = now - LOW_CONF_AGE_DAYS * 86400
            before = len(self._notes)
            self._notes = [
                n
                for n in self._notes
                if not (
                    n.confidence < 0.5
                    and n.uses < 2
                    and n.learned_at < cutoff
                )
            ]
            removed = before - len(self._notes)
            if removed:
                self._save_sync()

        added = 0
        recent = self._turns[-20:]
        if recent:
            try:
                notes = await self._extract_notes_llm(recent)
                for raw in notes:
                    try:
                        cat = raw.get("category", "topic")
                        text = (raw.get("text") or "").strip()
                        if not text:
                            continue
                        conf = float(raw.get("confidence", 0.6))
                        before_notes = len(self._notes)
                        await self.add_note(cat, text, confidence=conf)
                        if len(self._notes) > before_notes:
                            added += 1
                    except Exception:
                        continue
            except Exception as e:
                logger.debug("memory_compact_extract_failed", error=str(e))

        logger.info("reachy_memory_compact", removed=removed, added=added)
        return {"aged_out": removed, "newly_extracted": added}

    async def _extract_and_save(self, recent: list[Turn]) -> None:
        try:
            notes = await self._extract_notes_llm(recent)
        except Exception as e:
            logger.debug("memory_extract_failed", error=str(e))
            return
        if not notes:
            return
        added = 0
        for raw in notes:
            try:
                cat = raw.get("category", "topic")
                text = (raw.get("text") or "").strip()
                if not text:
                    continue
                conf = float(raw.get("confidence", 0.6))
                await self.add_note(cat, text, confidence=conf)
                added += 1
            except Exception:
                continue
        if added:
            logger.info("memory_extracted", added=added)

    async def _extract_notes_llm(self, recent: list[Turn]) -> list[dict]:
        """
        Call the light LLM to extract 0-3 durable notes from recent turns.
        Uses the unified client so it inherits project-wide routing +
        fallbacks. Short prompt, tight token budget — this runs every 5 turns.
        """
        transcript = "\n".join(
            f"USER: {t.user_text}\nREACHY: {t.reachy_text}" for t in recent if t.user_text
        )
        if not transcript:
            return []

        system = (
            "You extract durable notes about a user from their conversation with a robot. "
            "Return ONLY a JSON array (no prose, no code fences). Each element is "
            '{"category": "preference" | "fact" | "correction" | "topic", '
            '"text": "short note in third person about the user", '
            '"confidence": 0.0-1.0}. '
            "Extract 0-3 notes. Prefer durable facts (preferences, names, habits, "
            "recurring topics). Skip ephemeral chit-chat. If nothing durable, return []."
        )

        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            client = get_unified_llm_client()
            response = await asyncio.wait_for(
                client.chat(
                    prompt=transcript,
                    system=system,
                    task_type="classification",
                    temperature=0.3,
                    max_tokens=400,
                ),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.debug("memory_extract_timeout")
            return []
        except Exception as e:
            logger.debug("memory_extract_llm_error", error=str(e))
            return []

        text = response if isinstance(response, str) else (
            response.get("content") or response.get("response") or ""
        )
        return _parse_notes_json(text)


def _parse_notes_json(text: str) -> list[dict]:
    """Tolerant JSON array extractor: handles fences, leading prose, etc."""
    if not text:
        return []
    # Strip markdown fences
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)
    # Find the first JSON array in the text
    match = re.search(r"\[.*\]", stripped, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if not item.get("text"):
            continue
        out.append(item)
    return out


def get_reachy_user_memory_service() -> ReachyUserMemoryService:
    return ReachyUserMemoryService.get_instance()
