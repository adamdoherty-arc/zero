"""Meeting vector search using pgvector + Ollama nomic-embed-text."""

from typing import Optional

import structlog
from sqlalchemy import select, text, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MeetingTranscriptSegmentModel, MeetingModel
from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


class MeetingVectorService:
    """Embedding and vector search for meeting transcripts using pgvector."""

    async def embed_text(self, text_input: str) -> list[float]:
        """Generate embedding for a single text using Ollama nomic-embed-text."""
        settings = get_settings()
        import httpx
        base_url = settings.ollama_base_url.rstrip("/").replace("/v1", "")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/api/embed",
                json={"model": settings.embedding_model, "input": text_input},
            )
            resp.raise_for_status()
            data = resp.json()
            # Ollama returns {"embeddings": [[...]]}
            return data["embeddings"][0]

    async def embed_segments(self, meeting_id: str, segments: list[dict], db: AsyncSession) -> int:
        """Generate embeddings for transcript segments and store in DB."""
        # Chunk segments into groups for embedding
        chunks = self._chunk_segments(segments, max_tokens=500)
        embedded_count = 0

        for chunk in chunks:
            try:
                embedding = await self.embed_text(chunk["text"])
                # Update the transcript segments that belong to this chunk
                for seg_id in chunk.get("segment_ids", []):
                    await db.execute(
                        text("UPDATE meeting_transcript_segments SET embedding = :emb WHERE id = :id"),
                        {"emb": str(embedding), "id": seg_id},
                    )
                embedded_count += 1
            except Exception as e:
                logger.warning("embedding_failed", chunk=chunk.get("text", "")[:50], error=str(e))

        await db.commit()
        logger.info("segments_embedded", meeting_id=meeting_id, chunks=embedded_count)
        return embedded_count

    async def search_similar(
        self,
        query: str,
        db: AsyncSession,
        meeting_id: Optional[str] = None,
        top_k: int = 8,
    ) -> list[dict]:
        """Search for similar transcript segments using cosine distance."""
        query_embedding = await self.embed_text(query)

        # Build query with pgvector cosine distance
        emb_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        if meeting_id:
            sql = text("""
                SELECT ts.id, ts.meeting_id, ts.speaker, ts.start_time, ts.end_time, ts.text,
                       ts.embedding <=> CAST(:emb AS vector) AS distance,
                       m.title as meeting_title
                FROM meeting_transcript_segments ts
                JOIN meetings m ON m.id = ts.meeting_id
                WHERE ts.embedding IS NOT NULL AND ts.meeting_id = :mid
                ORDER BY ts.embedding <=> CAST(:emb AS vector)
                LIMIT :k
            """)
            result = await db.execute(sql, {"emb": emb_str, "mid": meeting_id, "k": top_k})
        else:
            sql = text("""
                SELECT ts.id, ts.meeting_id, ts.speaker, ts.start_time, ts.end_time, ts.text,
                       ts.embedding <=> CAST(:emb AS vector) AS distance,
                       m.title as meeting_title
                FROM meeting_transcript_segments ts
                JOIN meetings m ON m.id = ts.meeting_id
                WHERE ts.embedding IS NOT NULL
                ORDER BY ts.embedding <=> CAST(:emb AS vector)
                LIMIT :k
            """)
            result = await db.execute(sql, {"emb": emb_str, "k": top_k})

        rows = result.fetchall()
        results = []
        for row in rows:
            results.append({
                "id": row.id,
                "meeting_id": row.meeting_id,
                "meeting_title": row.meeting_title,
                "speaker": row.speaker,
                "start_time": row.start_time,
                "end_time": row.end_time,
                "text": row.text,
                "distance": row.distance,
            })
        return results

    async def delete_meeting_vectors(self, meeting_id: str, db: AsyncSession) -> None:
        """Clear embeddings for a meeting (segments still exist, just embedding=NULL)."""
        await db.execute(
            text("UPDATE meeting_transcript_segments SET embedding = NULL WHERE meeting_id = :mid"),
            {"mid": meeting_id},
        )
        await db.commit()

    def _chunk_segments(self, segments: list[dict], max_tokens: int = 500) -> list[dict]:
        """Group segments into chunks for embedding."""
        chunks = []
        current_text = ""
        current_ids = []
        current_start = None

        for seg in segments:
            seg_text = seg.get("text", "").strip()
            estimated_tokens = len(current_text + " " + seg_text) // 4
            if estimated_tokens > max_tokens and current_text:
                chunks.append({"text": current_text.strip(), "segment_ids": current_ids, "start": current_start})
                current_text = ""
                current_ids = []
                current_start = None
            if current_start is None:
                current_start = seg.get("start_time", seg.get("start", 0))
            current_text += " " + seg_text
            if "id" in seg:
                current_ids.append(seg["id"])

        if current_text.strip():
            chunks.append({"text": current_text.strip(), "segment_ids": current_ids, "start": current_start})
        return chunks


_instance: MeetingVectorService | None = None

def get_meeting_vector_service() -> MeetingVectorService:
    global _instance
    if _instance is None:
        _instance = MeetingVectorService()
    return _instance
