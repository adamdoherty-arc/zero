"""Meeting search: full-text (PostgreSQL tsvector) + semantic (pgvector) hybrid."""

from typing import Optional
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.meeting_vector_service import get_meeting_vector_service

logger = structlog.get_logger(__name__)


class MeetingSearchService:
    async def search(
        self,
        query: str,
        db: AsyncSession,
        search_type: str = "hybrid",
        limit: int = 20,
    ) -> list[dict]:
        if not query.strip():
            return []

        if search_type == "semantic":
            return await self._semantic_search(query, db, limit)
        elif search_type == "fulltext":
            return await self._fulltext_search(query, db, limit)
        else:
            # Hybrid: combine both, deduplicate (graceful if semantic fails)
            ft_results = await self._fulltext_search(query, db, limit)
            try:
                sem_results = await self._semantic_search(query, db, limit)
            except Exception as e:
                logger.warning("semantic_search_fallback", error=str(e))
                sem_results = []
            return self._merge_results(ft_results, sem_results, limit)

    async def _fulltext_search(self, query: str, db: AsyncSession, limit: int) -> list[dict]:
        sql = text("""
            SELECT ts.id, ts.meeting_id, ts.speaker, ts.start_time, ts.text,
                   m.title as meeting_title,
                   ts_rank(to_tsvector('english', ts.text), plainto_tsquery('english', :q)) as score
            FROM meeting_transcript_segments ts
            JOIN meetings m ON m.id = ts.meeting_id
            WHERE to_tsvector('english', ts.text) @@ plainto_tsquery('english', :q)
            ORDER BY score DESC
            LIMIT :lim
        """)
        result = await db.execute(sql, {"q": query, "lim": limit})
        rows = result.fetchall()
        return [
            {"meeting_id": r.meeting_id, "meeting_title": r.meeting_title,
             "snippet": r.text[:300], "score": float(r.score),
             "timestamp": r.start_time, "speaker": r.speaker, "source": "fulltext"}
            for r in rows
        ]

    async def _semantic_search(self, query: str, db: AsyncSession, limit: int) -> list[dict]:
        vector_svc = get_meeting_vector_service()
        results = await vector_svc.search_similar(query, db, top_k=limit)
        return [
            {"meeting_id": r["meeting_id"], "meeting_title": r.get("meeting_title", ""),
             "snippet": r["text"][:300], "score": max(0, 1 - r.get("distance", 1)),
             "timestamp": r.get("start_time"), "speaker": r.get("speaker"), "source": "semantic"}
            for r in results
        ]

    def _merge_results(self, ft: list[dict], sem: list[dict], limit: int) -> list[dict]:
        seen = set()
        merged = []
        for r in ft + sem:
            key = (r["meeting_id"], r.get("timestamp"))
            if key not in seen:
                seen.add(key)
                merged.append(r)
        merged.sort(key=lambda x: x["score"], reverse=True)
        return merged[:limit]


_instance: MeetingSearchService | None = None

def get_meeting_search_service() -> MeetingSearchService:
    global _instance
    if _instance is None:
        _instance = MeetingSearchService()
    return _instance
