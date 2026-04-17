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
from app.infrastructure.ollama_client import get_ollama_client
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
            ollama = get_ollama_client()

            for item in extracted[:10]:  # cap at 10 per extraction
                content = item.get("content", "")
                if not content or len(content) < 10:
                    continue

                importance = float(item.get("importance", 50))
                tags = item.get("tags", [])
                ttl_days = HIGH_IMPORTANCE_TTL_DAYS if importance >= IMPORTANCE_THRESHOLD else DEFAULT_TTL_DAYS

                embedding = await ollama.embed_safe(content)

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
            ollama = get_ollama_client()
            embedding = await ollama.embed_safe(content)

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

    async def search(
        self,
        query: str,
        namespace: Optional[str] = None,
        limit: int = 5,
    ) -> List[MemorySearchResult]:
        """Semantic search over episodic memories using pgvector cosine distance."""
        try:
            ollama = get_ollama_client()
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
    ) -> List[EpisodicMemory]:
        """Get most recent memories, optionally filtered by namespace."""
        try:
            async with get_session() as session:
                query = select(EpisodicMemoryModel).order_by(
                    EpisodicMemoryModel.created_at.desc()
                )
                if namespace:
                    query = query.where(EpisodicMemoryModel.namespace == namespace)
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
        except Exception:
            return 0


@lru_cache()
def get_episodic_memory_service() -> EpisodicMemoryService:
    return EpisodicMemoryService()
