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
    async def query(self, question: str, db, meeting_id: str | None = None, top_k: int = 8) -> dict:
        if not question.strip():
            return {"answer": "", "sources": []}

        logger.info("meeting_rag_query", question=question[:80], meeting_id=meeting_id)
        vector_svc = get_meeting_vector_service()
        results = await vector_svc.search_similar(question, db, meeting_id=meeting_id, top_k=top_k)

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


_instance: MeetingRAGService | None = None

def get_meeting_rag_service() -> MeetingRAGService:
    global _instance
    if _instance is None:
        _instance = MeetingRAGService()
    return _instance
