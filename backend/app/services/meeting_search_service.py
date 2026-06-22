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
            # RTV-5: the semantic-only path must degrade as gracefully as the
            # hybrid branch below. _semantic_search -> embed_text raises when the
            # embedder is down; without this guard a `search_type=semantic`
            # request 500s. Fall back to full-text rather than erroring.
            try:
                return await self._semantic_search(query, db, limit)
            except Exception as e:
                logger.warning("semantic_search_fallback", error=str(e))
                return await self._fulltext_search(query, db, limit)
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

    @staticmethod
    def _normalize_scores(rows: list[dict]) -> list[dict]:
        """Min-max normalize one ranker's scores into [0,1].

        Fulltext ``ts_rank`` (~0.0-0.1) and semantic ``1 - cosine_distance``
        (~0.6-0.95) live on incompatible scales; normalizing each list
        independently makes them comparable before the hybrid sort (RTV-3).
        Degenerate lists (0/1 row, or all-equal scores) map to 1.0. Returns
        copies so callers never mutate the source rows.
        """
        if not rows:
            return []
        scores = [r["score"] for r in rows]
        lo, hi = min(scores), max(scores)
        span = hi - lo
        out = []
        for r in rows:
            rr = dict(r)
            rr["score"] = 1.0 if span == 0 else (r["score"] - lo) / span
            out.append(rr)
        return out

    def _merge_results(self, ft: list[dict], sem: list[dict], limit: int) -> list[dict]:
        """Fuse fulltext + semantic hits into one ranking.

        Each ranker's scores are min-max normalized to [0,1] first so the two
        incompatible scales are comparable (fixes RTV-3, where raw ts_rank scores
        were dwarfed by cosine similarities and fulltext relevance was ignored).
        Dedup by (meeting_id, timestamp) keeps the HIGHER normalized score and
        tags the segment ``hybrid`` when both rankers surfaced it, instead of
        blindly keeping the first (fulltext) copy and burying a strong semantic
        match (fixes RTV-4). ``score`` stays in [0,1] for the frontend's
        "% match" display.
        """
        best: dict = {}
        for r in self._normalize_scores(ft) + self._normalize_scores(sem):
            key = (r["meeting_id"], r.get("timestamp"))
            cur = best.get(key)
            if cur is None:
                best[key] = r
            else:
                winner = dict(r if r["score"] >= cur["score"] else cur)
                winner["score"] = max(r["score"], cur["score"])
                winner["source"] = "hybrid"
                best[key] = winner
        merged = sorted(best.values(), key=lambda x: x["score"], reverse=True)
        return merged[:limit]


_instance: MeetingSearchService | None = None

def get_meeting_search_service() -> MeetingSearchService:
    global _instance
    if _instance is None:
        _instance = MeetingSearchService()
    return _instance
