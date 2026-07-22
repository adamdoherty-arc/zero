"""
Episodic Memory Service for Zero Brain.

Extracts facts, decisions, and outcomes from LLM interactions.
Stores with pgvector embeddings for semantic retrieval.
Provides few-shot enrichment for any LLM call.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from functools import lru_cache

import structlog
from sqlalchemy import select, delete, func as sql_func, text

from app.infrastructure.database import get_session
from app.infrastructure.ollama_client import get_llm_client
from app.infrastructure.unified_llm_client import get_unified_llm_client
from app.db.models import EpisodicMemoryModel
from app.models.brain import EpisodicMemory, MemorySearchResult

logger = structlog.get_logger(__name__)

DEFAULT_TTL_DAYS = 90
HIGH_IMPORTANCE_TTL_DAYS = 180
IMPORTANCE_THRESHOLD = 75.0

EXTRACTION_SYSTEM_PROMPT = """You extract structured knowledge from text. For each distinct fact, decision, or outcome, output a JSON array of objects:
[{"content": "concise fact/decision/outcome", "importance": 0-100, "tags": ["tag1", "tag2"]}]

Rules:
- importance: 90-100 for critical decisions/failures, 70-89 for useful patterns, 50-69 for general facts, <50 for trivia
- tags: 1-3 short tags describing the topic (e.g. "content", "tiktok", "error", "strategy")
- Each item should be a standalone, self-contained statement
- Focus on actionable knowledge, not procedural details
- Return ONLY valid JSON array"""


class EpisodicMemoryService:
    """Extracts and stores facts/decisions/outcomes with semantic retrieval."""

    def _gen_id(self) -> str:
        return f"em-{uuid.uuid4().hex[:12]}"

    async def extract_and_store(
        self,
        text: str,
        source_type: str,
        source_id: Optional[str] = None,
        namespace: str = "general",
        context: Optional[Dict[str, Any]] = None,
    ) -> List[EpisodicMemory]:
        """Extract facts/decisions/outcomes from text via LLM, store with embeddings."""
        if not text or len(text.strip()) < 20:
            return []

        try:
            llm = get_unified_llm_client()
            extracted = await llm.structured_chat(
                prompt=f"Extract knowledge from this text:\n\n{text[:3000]}",
                system=EXTRACTION_SYSTEM_PROMPT,
                task_type="analysis",
                temperature=0.1,
                max_tokens=2048,
            )

            if not isinstance(extracted, list):
                extracted = [extracted] if isinstance(extracted, dict) else []

            memories = []
            ollama = get_llm_client()

            for item in extracted[:10]:  # cap at 10 per extraction
                # Fix-126 (LRN-A/CAP-1): one malformed LLM item must not abort the
                # whole captured batch. Guard per-item: a non-dict element,
                # null/"high" importance, or an empty embedding skips that item
                # only — mirrors the Fix-123 reflection-store hardening.
                try:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content", "")
                    if not content or len(content) < 10:
                        continue

                    try:
                        # RET-3 (supervise ee392aa1): `or 50` promoted a
                        # legitimate importance of 0 (trivia the LLM scored at the
                        # bottom) to mid-scale 50, silently inflating TTL/ranking.
                        # Default only on a truly absent/None value.
                        _raw_importance = item.get("importance")
                        importance = float(_raw_importance) if _raw_importance is not None else 50.0
                    except (TypeError, ValueError):
                        importance = 50.0
                    # RET-1 (supervise ee392aa1): an LLM emitting `"tags": null`
                    # (a common JSON-mode habit for an empty array) left tags=None.
                    # The ORM row committed (nullable column), but the EpisodicMemory
                    # Pydantic build below — tags: List[str] non-Optional — then
                    # raised ValidationError, caught per-item AFTER the commit: the
                    # fact was persisted yet dropped from the return list, and the
                    # NULL-tags row later fails to deserialize on retrieval too.
                    # `or []` coerces both absent and null to an empty list.
                    tags = item.get("tags") or []
                    ttl_days = HIGH_IMPORTANCE_TTL_DAYS if importance >= IMPORTANCE_THRESHOLD else DEFAULT_TTL_DAYS

                    embedding = await ollama.embed_safe(content)
                    if not embedding:
                        # Fix-126 (LRN-B): search filters embedding IS NOT NULL, so a
                        # null-vector row is unretrievable dead data — skip it rather
                        # than persist + over-count it as a stored memory.
                        logger.warning("episodic_embed_empty_skip",
                                       namespace=namespace, source_type=source_type)
                        continue

                    mem_id = self._gen_id()
                    now = datetime.now(timezone.utc)

                    async with get_session() as session:
                        model = EpisodicMemoryModel(
                            id=mem_id,
                            namespace=namespace,
                            content=content,
                            source_type=source_type,
                            source_id=source_id,
                            importance=importance,
                            tags=tags,
                            context=context or {},
                            embedding=embedding,
                            expires_at=now + timedelta(days=ttl_days),
                            created_at=now,
                        )
                        session.add(model)
                        await session.commit()

                    memories.append(EpisodicMemory(
                        id=mem_id,
                        namespace=namespace,
                        content=content,
                        source_type=source_type,
                        source_id=source_id,
                        importance=importance,
                        tags=tags,
                        context=context or {},
                        expires_at=now + timedelta(days=ttl_days),
                        created_at=now,
                    ))
                except Exception as item_err:
                    logger.warning("episodic_item_store_failed",
                                   error=str(item_err), namespace=namespace)
                    continue

            logger.info("episodic_memories_extracted",
                        count=len(memories), namespace=namespace, source_type=source_type)
            return memories

        except Exception as e:
            logger.error("episodic_extraction_failed", error=str(e))
            return []

    async def store_direct(
        self,
        content: str,
        source_type: str,
        namespace: str = "general",
        importance: float = 50.0,
        tags: Optional[List[str]] = None,
        source_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[EpisodicMemory]:
        """Store a single memory directly without LLM extraction."""
        try:
            ollama = get_llm_client()
            embedding = await ollama.embed_safe(content)
            if not embedding:
                # Fix-126 (LRN-B): a null embedding produces a row that semantic
                # search can never return (it filters embedding IS NOT NULL).
                # Refuse to store dead data rather than report a false success.
                logger.warning("episodic_store_direct_embed_empty", source_type=source_type)
                return None

            ttl_days = HIGH_IMPORTANCE_TTL_DAYS if importance >= IMPORTANCE_THRESHOLD else DEFAULT_TTL_DAYS
            now = datetime.now(timezone.utc)
            mem_id = self._gen_id()

            async with get_session() as session:
                model = EpisodicMemoryModel(
                    id=mem_id,
                    namespace=namespace,
                    content=content,
                    source_type=source_type,
                    source_id=source_id,
                    importance=importance,
                    tags=tags or [],
                    context=context or {},
                    embedding=embedding,
                    expires_at=now + timedelta(days=ttl_days),
                    created_at=now,
                )
                session.add(model)
                await session.commit()

            return EpisodicMemory(
                id=mem_id,
                namespace=namespace,
                content=content,
                source_type=source_type,
                source_id=source_id,
                importance=importance,
                tags=tags or [],
                context=context or {},
                expires_at=now + timedelta(days=ttl_days),
                created_at=now,
            )
        except Exception as e:
            logger.error("episodic_store_direct_failed", error=str(e))
            return None

    async def exists_recent(
        self,
        content: str,
        source_type: str,
        namespace: str = "general",
        within_days: int = 7,
    ) -> bool:
        """True if an identical-content memory of this source_type already exists
        in the recent window.

        Fix-126 (RFL-3): lets re-runnable loops (weekly reflection, etc.) be
        idempotent — a double-fire over the same decision window re-synthesizes
        the same learnings, and storing them again pollutes retrieval with
        duplicate meta-learnings. Callers skip the store when this returns True.
        Fails OPEN (returns False on error) so a check blip never blocks a store.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
            async with get_session() as session:
                stmt = (
                    select(EpisodicMemoryModel.id)
                    .where(EpisodicMemoryModel.content == content)
                    .where(EpisodicMemoryModel.source_type == source_type)
                    .where(EpisodicMemoryModel.namespace == namespace)
                    .where(EpisodicMemoryModel.created_at >= cutoff)
                    .limit(1)
                )
                result = await session.execute(stmt)
                return result.first() is not None
        except Exception as e:
            logger.warning("episodic_exists_check_failed", error=str(e))
            return False

    async def search(
        self,
        query: str,
        namespace: Optional[str] = None,
        limit: int = 5,
    ) -> List[MemorySearchResult]:
        """Semantic search over episodic memories using pgvector cosine distance."""
        try:
            ollama = get_llm_client()
            query_embedding = await ollama.embed_safe(query)
            if not query_embedding:
                return []

            now = datetime.now(timezone.utc)
            async with get_session() as session:
                # Build query with cosine distance
                distance = EpisodicMemoryModel.embedding.cosine_distance(query_embedding)
                query_stmt = (
                    select(EpisodicMemoryModel, distance.label("distance"))
                    .where(EpisodicMemoryModel.embedding.isnot(None))
                    .where(
                        (EpisodicMemoryModel.expires_at.is_(None)) |
                        (EpisodicMemoryModel.expires_at > now)
                    )
                )

                if namespace:
                    query_stmt = query_stmt.where(EpisodicMemoryModel.namespace == namespace)

                query_stmt = query_stmt.order_by(distance).limit(limit)
                result = await session.execute(query_stmt)
                rows = result.all()

                return [
                    MemorySearchResult(
                        memory=EpisodicMemory(
                            id=row[0].id,
                            namespace=row[0].namespace,
                            content=row[0].content,
                            source_type=row[0].source_type,
                            source_id=row[0].source_id,
                            importance=row[0].importance,
                            tags=row[0].tags or [],
                            context=row[0].context or {},
                            expires_at=row[0].expires_at,
                            created_at=row[0].created_at,
                        ),
                        similarity=max(0.0, 1.0 - float(row[1])),
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error("episodic_search_failed", error=str(e))
            return []

    async def get_recent(
        self,
        namespace: Optional[str] = None,
        limit: int = 20,
        source_type: Optional[str] = None,
    ) -> List[EpisodicMemory]:
        """Get most recent memories, optionally filtered by namespace/source_type.

        Pushing ``source_type`` into SQL (rather than over-fetching and filtering in
        Python) keeps a low-frequency source (e.g. weekly reflections) findable even
        when high-frequency sources dominate the recency ordering.
        """
        try:
            async with get_session() as session:
                query = select(EpisodicMemoryModel).order_by(
                    EpisodicMemoryModel.created_at.desc()
                )
                if namespace:
                    query = query.where(EpisodicMemoryModel.namespace == namespace)
                if source_type:
                    query = query.where(EpisodicMemoryModel.source_type == source_type)
                query = query.limit(limit)

                result = await session.execute(query)
                rows = result.scalars().all()

                return [
                    EpisodicMemory(
                        id=r.id,
                        namespace=r.namespace,
                        content=r.content,
                        source_type=r.source_type,
                        source_id=r.source_id,
                        importance=r.importance,
                        tags=r.tags or [],
                        context=r.context or {},
                        expires_at=r.expires_at,
                        created_at=r.created_at,
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.error("episodic_get_recent_failed", error=str(e))
            return []

    async def enrich_prompt(
        self,
        task_description: str,
        namespace: Optional[str] = None,
        limit: int = 3,
    ) -> str:
        """Search for relevant memories and format as few-shot context block."""
        results = await self.search(task_description, namespace=namespace, limit=limit)
        if not results:
            return ""

        lines = ["## Relevant Past Experience"]
        for r in results:
            lines.append(f"- [{r.memory.namespace}] {r.memory.content} (relevance: {r.similarity:.0%})")
        return "\n".join(lines)

    async def cleanup_expired(self) -> int:
        """Delete memories past their TTL."""
        try:
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                result = await session.execute(
                    delete(EpisodicMemoryModel).where(
                        EpisodicMemoryModel.expires_at.isnot(None),
                        EpisodicMemoryModel.expires_at < now,
                    )
                )
                await session.commit()
                count = result.rowcount
                if count > 0:
                    logger.info("episodic_cleanup_complete", deleted=count)
                return count
        except Exception as e:
            logger.error("episodic_cleanup_failed", error=str(e))
            return 0

    async def count(self, namespace: Optional[str] = None) -> int:
        """Count total memories."""
        try:
            async with get_session() as session:
                query = select(sql_func.count(EpisodicMemoryModel.id))
                if namespace:
                    query = query.where(EpisodicMemoryModel.namespace == namespace)
                result = await session.execute(query)
                return result.scalar() or 0
        except Exception as e:
            # RET-4 (supervise ee392aa1): every other method in this file logs on
            # this catch; count() alone swallowed silently, so a DB outage would
            # be indistinguishable from "zero memories" to any future metric caller.
            logger.warning("episodic_count_failed", error=str(e), namespace=namespace)
            return 0


@lru_cache()
def get_episodic_memory_service() -> EpisodicMemoryService:
    return EpisodicMemoryService()
