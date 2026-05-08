"""Lore ingestion + retrieval (W5 of orchestration hardening).

Walks existing CharacterModel.research_data, chunks it into retrievable units,
embeds them, and upserts into character_lore_chunks for hybrid retrieval by
the carousel synthesis stage.

No new scraping: operates strictly on research already persisted on
CharacterModel.research_data and .fact_bank.

Retrieval helper is intentionally simple: a single pgvector similarity scan
gated by character_id, returning the top-k chunks. Hybrid text+vector fusion
can be layered on later without changing the call signature.
"""

from __future__ import annotations

import hashlib
import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, delete

from app.db.models import CharacterLoreChunkModel, CharacterModel
from app.infrastructure.database import get_session
from app.infrastructure.ollama_client import get_llm_client

logger = structlog.get_logger(__name__)


_CHUNK_CHAR_TARGET = 800
_CHUNK_OVERLAP = 120
_INGEST_BATCH = 8


class LoreIngestionService:
    """Chunk + embed + upsert character research into character_lore_chunks."""

    def __init__(self) -> None:
        self._embed = get_llm_client()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    async def ingest_all(self, *, limit: Optional[int] = None) -> Dict[str, int]:
        """Scheduler entrypoint. Returns {"characters": N, "chunks": M}."""
        async with get_session() as session:
            stmt = (
                select(CharacterModel)
                .where(CharacterModel.research_data.isnot(None))
                .order_by(CharacterModel.research_depth_score.desc().nullslast())
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            res = await session.execute(stmt)
            characters = list(res.scalars().all())

        totals = {"characters": 0, "chunks": 0}
        for character in characters:
            try:
                added = await self.ingest_character(character_id=character.id)
                totals["characters"] += 1
                totals["chunks"] += added
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "lore_ingest_character_failed",
                    character_id=character.id,
                    error=str(e)[:200],
                )
        logger.info("lore_ingest_all_complete", **totals)
        return totals

    async def ingest_character(self, *, character_id: str) -> int:
        """Rebuild chunks for a single character. Returns chunk count written."""
        async with get_session() as session:
            character = await session.get(CharacterModel, character_id)
            if character is None or not character.research_data:
                return 0
            texts = list(_extract_texts_from_research(character.research_data))

        chunks: List[Dict[str, Any]] = []
        for source, text in texts:
            for idx, chunk_text in enumerate(_chunk_text(text)):
                chunks.append(
                    {
                        "source": source,
                        "text": chunk_text,
                        "chunk_index": idx,
                    }
                )

        if not chunks:
            return 0

        # Embed in batches to cap memory.
        embeddings: List[Optional[List[float]]] = []
        for i in range(0, len(chunks), _INGEST_BATCH):
            batch_texts = [c["text"] for c in chunks[i : i + _INGEST_BATCH]]
            try:
                batch_embeds = await self._embed.embed_batch(batch_texts)
            except Exception as e:  # noqa: BLE001
                logger.warning("lore_embed_batch_failed", character_id=character_id, error=str(e)[:200])
                batch_embeds = [None] * len(batch_texts)
            embeddings.extend(batch_embeds)

        # Replace existing rows for this character (idempotent ingestion).
        async with get_session() as session:
            await session.execute(
                delete(CharacterLoreChunkModel).where(
                    CharacterLoreChunkModel.character_id == character_id
                )
            )
            for chunk, embedding in zip(chunks, embeddings):
                row = CharacterLoreChunkModel(
                    id=f"lore-{uuid.uuid4().hex[:12]}",
                    character_id=character_id,
                    source=chunk["source"],
                    source_license=None,
                    text=chunk["text"],
                    chunk_index=chunk["chunk_index"],
                    chunk_metadata={
                        "hash": hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()[:16],
                    },
                    embedding=embedding,
                )
                session.add(row)
            await session.commit()
        return len(chunks)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        *,
        character_id: str,
        query: str,
        k: int = 6,
    ) -> List[Dict[str, Any]]:
        """Top-k lore chunks for a character by vector similarity.

        Returns [{text, source, chunk_index, similarity}]. Silently returns an
        empty list when embedding fails — the caller can fall back to
        CharacterModel.research_data directly.
        """
        vec = await self._embed.embed_safe(query)
        if vec is None:
            return []
        async with get_session() as session:
            stmt = (
                select(
                    CharacterLoreChunkModel.text,
                    CharacterLoreChunkModel.source,
                    CharacterLoreChunkModel.chunk_index,
                    CharacterLoreChunkModel.embedding.cosine_distance(vec).label("dist"),
                )
                .where(CharacterLoreChunkModel.character_id == character_id)
                .where(CharacterLoreChunkModel.embedding.isnot(None))
                .order_by("dist")
                .limit(k)
            )
            res = await session.execute(stmt)
            rows = res.all()
        return [
            {
                "text": r.text,
                "source": r.source,
                "chunk_index": r.chunk_index,
                "similarity": round(1.0 - float(r.dist), 4),
            }
            for r in rows
        ]


def _extract_texts_from_research(research_data: Dict[str, Any]) -> List[tuple[str, str]]:
    """Flatten nested research_data into (source, text) pairs.

    research_data shapes observed: {wiki_text, wiki_source_url, synthesis_text,
    search_results[...], deep_research[...]}. We take string leaves that look
    like prose (length > 200 chars) and tag them with their JSON path as source.
    """
    out: List[tuple[str, str]] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, str):
            if len(node) >= 200:
                out.append((path or "research_data", node))
            return
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{path}.{k}" if path else k)
            return
        if isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, f"{path}[{i}]")
            return

    _walk(research_data, "")
    return out


def _chunk_text(text: str) -> List[str]:
    """Simple character-based chunking with overlap. Good enough for v1."""
    text = text.strip()
    if len(text) <= _CHUNK_CHAR_TARGET:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_CHAR_TARGET, len(text))
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - _CHUNK_OVERLAP
    return chunks


@lru_cache()
def get_lore_ingestion_service() -> LoreIngestionService:
    return LoreIngestionService()
