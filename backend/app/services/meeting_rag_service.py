"""RAG pipeline for meeting Q&A."""

import structlog

from app.infrastructure.ollama_client import get_llm_client
from app.services.meeting_vector_service import get_meeting_vector_service

logger = structlog.get_logger(__name__)

_RAG_SYSTEM = (
    "You are a helpful meeting assistant. Answer using ONLY the meeting transcript "
    "excerpts provided. If the answer is not in the excerpts, say so honestly. "
    "Cite the source meeting and speaker when possible."
)

_RAG_PROMPT = """\
Meeting transcript excerpts (most relevant first):

{context}

---

User question: {question}

Answer based on the excerpts above. Mention which meeting or speaker when referencing specific information.
"""


class MeetingRAGService:
    async def query(
        self,
        question: str,
        db,
        meeting_id: str | None = None,
        top_k: int = 8,
        topic_label: str | None = None,
    ) -> dict:
        if not question.strip():
            return {"answer": "", "sources": []}

        logger.info(
            "meeting_rag_query",
            question=question[:80],
            meeting_id=meeting_id,
            topic_label=topic_label,
        )
        vector_svc = get_meeting_vector_service()
        # F-91: when a topic_label is provided, over-fetch then boost the
        # in-topic segments to the top. Falls back gracefully when the
        # topics workspace file isn't available (older meetings).
        fetch_k = top_k * 3 if topic_label else top_k
        results = await vector_svc.search_similar(
            question, db, meeting_id=meeting_id, top_k=fetch_k
        )

        if results and topic_label:
            results = await self._boost_in_topic(results, topic_label, top_k=top_k)

        if not results:
            return {"answer": "I couldn't find any relevant meeting content to answer your question.", "sources": []}

        # Build context
        sections = []
        for i, r in enumerate(results, 1):
            parts = [f"[Excerpt {i}]"]
            if r.get("speaker"):
                parts.append(f"Speaker: {r['speaker']}")
            if r.get("start_time"):
                parts.append(f"Time: {r['start_time']:.1f}s")
            parts.append(f"Meeting: {r.get('meeting_title', r['meeting_id'])}")
            sections.append(" | ".join(parts) + "\n" + r["text"])

        context = "\n\n".join(sections)
        prompt = _RAG_PROMPT.format(context=context, question=question)

        client = get_llm_client()
        answer = await client.chat(prompt, system=_RAG_SYSTEM, temperature=0.2)

        sources = []
        for r in results:
            sources.append({
                "meeting_id": r["meeting_id"],
                "meeting_title": r.get("meeting_title", ""),
                "text": r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"],
                "speaker": r.get("speaker"),
                "timestamp": r.get("start_time"),
            })

        return {"answer": answer, "sources": sources}

    async def _boost_in_topic(
        self,
        results: list[dict],
        topic_label: str,
        top_k: int,
    ) -> list[dict]:
        """F-91 — rerank vector hits so segments inside any topic whose
        label token-overlaps with ``topic_label`` float to the top.
        Score blend: 0.7 * vector_score + 0.3 * (1.0 if in-topic else 0).
        """
        try:
            from app.services.meeting_topic_link_service import (
                get_meeting_topic_link_service,
                _tokenize,
                _jaccard,
            )
            from app.services.meeting_topic_segmenter import (
                get_meeting_topic_store,
            )
        except Exception as exc:
            logger.debug("rag_topic_boost_imports_failed", error=str(exc))
            return results[:top_k]

        query_tokens = _tokenize(topic_label)
        if not query_tokens:
            return results[:top_k]

        topic_store = get_meeting_topic_store()
        # Cache per-meeting topic lookups so a 24-hit batch only hits the
        # disk once per distinct meeting_id.
        topic_cache: dict[str, list[dict]] = {}

        def _topics_for(meeting_id: str) -> list[dict]:
            if meeting_id in topic_cache:
                return topic_cache[meeting_id]
            data = topic_store.read(meeting_id) or {}
            topic_cache[meeting_id] = list(data.get("topics") or [])
            return topic_cache[meeting_id]

        def _in_topic(meeting_id: str, ts: float | None) -> bool:
            if ts is None:
                return False
            for topic in _topics_for(meeting_id):
                t_tokens = _tokenize(topic.get("label") or "")
                if _jaccard(query_tokens, t_tokens) < 0.3:
                    continue
                if float(topic.get("start_time") or 0) <= ts <= float(topic.get("end_time") or 0):
                    return True
            return False

        scored: list[tuple[float, dict]] = []
        for r in results:
            # Fix-118 (RTV-2): meeting_vector_service.search_similar returns a
            # "distance" key (lower = closer), NOT "score". The old `r.get("score")`
            # was always None -> base==0.5 for EVERY hit, so the vector ranking was
            # erased and topic-boost partitioned results into two flat buckets.
            # Derive a 0-1 relevance from distance (same convention as
            # meeting_search_service) and fall back to an explicit score if present.
            if r.get("score") is not None:
                base = float(r["score"])
            else:
                base = max(0.0, 1.0 - float(r.get("distance", 1.0)))
            bonus = 0.3 if _in_topic(r.get("meeting_id") or "", r.get("start_time")) else 0.0
            scored.append((0.7 * base + bonus, r))
        scored.sort(key=lambda kv: kv[0], reverse=True)
        return [r for _, r in scored[:top_k]]


_instance: MeetingRAGService | None = None

def get_meeting_rag_service() -> MeetingRAGService:
    global _instance
    if _instance is None:
        _instance = MeetingRAGService()
    return _instance
