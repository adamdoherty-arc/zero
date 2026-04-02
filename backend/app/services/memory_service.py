"""
Persistent Conversation Memory Service

Replaces in-memory session store with PostgreSQL-backed persistence.
Sessions survive restarts, support search, and enable long-term context.
"""

import uuid
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, update, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)


class MemoryService:
    """Persistent conversation memory backed by PostgreSQL."""

    async def create_session(
        self,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        channel: str = "web",
    ) -> Dict[str, Any]:
        from app.db.models import ConversationSessionModel
        sid = session_id or str(uuid.uuid4())
        async with AsyncSessionLocal() as db:
            existing = await db.get(ConversationSessionModel, sid)
            if existing:
                existing.last_active = datetime.now(UTC).replace(tzinfo=None)
                if project_id:
                    existing.project_id = project_id
                await db.commit()
                return {"session_id": sid, "resumed": True, "message_count": existing.message_count}

            session = ConversationSessionModel(
                id=sid,
                project_id=project_id,
                channel=channel,
            )
            db.add(session)
            await db.commit()
            return {"session_id": sid, "resumed": False, "message_count": 0}

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> int:
        from app.db.models import ConversationMessageModel, ConversationSessionModel
        async with AsyncSessionLocal() as db:
            msg = ConversationMessageModel(
                session_id=session_id,
                role=role,
                content=content,
                metadata_=metadata or {},
            )
            db.add(msg)
            # Update session
            await db.execute(
                update(ConversationSessionModel)
                .where(ConversationSessionModel.id == session_id)
                .values(
                    last_active=datetime.now(UTC).replace(tzinfo=None),
                    message_count=ConversationSessionModel.message_count + 1,
                )
            )
            await db.commit()
            await db.refresh(msg)
            return msg.id

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        from app.db.models import ConversationMessageModel
        async with AsyncSessionLocal() as db:
            query = (
                select(ConversationMessageModel)
                .where(ConversationMessageModel.session_id == session_id)
                .order_by(desc(ConversationMessageModel.id))
                .limit(limit)
            )
            if before_id:
                query = query.where(ConversationMessageModel.id < before_id)
            result = await db.execute(query)
            messages = result.scalars().all()
            return [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "metadata": m.metadata_,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in reversed(messages)  # Chronological order
            ]

    async def get_recent_context(
        self,
        session_id: str,
        max_messages: int = 20,
        max_chars: int = 8000,
    ) -> str:
        """Get recent conversation as formatted context string for LLM injection."""
        messages = await self.get_messages(session_id, limit=max_messages)
        lines = []
        total = 0
        for m in messages:
            role = "User" if m["role"] == "human" else "Zero"
            line = f"{role}: {m['content']}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)

    async def list_sessions(
        self,
        limit: int = 20,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        from app.db.models import ConversationSessionModel
        async with AsyncSessionLocal() as db:
            query = (
                select(ConversationSessionModel)
                .order_by(desc(ConversationSessionModel.last_active))
                .limit(limit)
            )
            if not include_archived:
                query = query.where(ConversationSessionModel.is_archived == False)
            result = await db.execute(query)
            sessions = result.scalars().all()
            return [
                {
                    "session_id": s.id,
                    "title": s.title,
                    "project_id": s.project_id,
                    "channel": s.channel,
                    "message_count": s.message_count,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "last_active": s.last_active.isoformat() if s.last_active else None,
                }
                for s in sessions
            ]

    async def search_conversations(
        self,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Full-text search across all conversation messages."""
        from app.db.models import ConversationMessageModel, ConversationSessionModel
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ConversationMessageModel, ConversationSessionModel.title)
                .join(ConversationSessionModel, ConversationMessageModel.session_id == ConversationSessionModel.id)
                .where(ConversationMessageModel.content.ilike(f"%{query}%"))
                .order_by(desc(ConversationMessageModel.created_at))
                .limit(limit)
            )
            rows = result.all()
            return [
                {
                    "session_id": msg.session_id,
                    "session_title": title,
                    "role": msg.role,
                    "content": msg.content[:200],
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
                for msg, title in rows
            ]

    async def update_session_title(self, session_id: str, title: str):
        from app.db.models import ConversationSessionModel
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ConversationSessionModel)
                .where(ConversationSessionModel.id == session_id)
                .values(title=title)
            )
            await db.commit()

    async def generate_title(self, session_id: str) -> str:
        """Auto-generate a title from the first user message."""
        messages = await self.get_messages(session_id, limit=3)
        first_human = next((m for m in messages if m["role"] == "human"), None)
        if first_human:
            title = first_human["content"][:80]
            if len(first_human["content"]) > 80:
                title += "..."
            await self.update_session_title(session_id, title)
            return title
        return "Untitled conversation"


_memory_service: Optional[MemoryService] = None

def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
