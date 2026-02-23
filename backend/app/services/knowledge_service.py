"""
Knowledge management service for ZERO's Second Brain functionality.
Handles notes, user profile, and memory recall.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache
import structlog

from sqlalchemy import select, func as sa_func, or_, text

from app.models.knowledge import (
    Note, NoteCreate, NoteUpdate, NoteType, NoteSource,
    UserProfile, UserProfileUpdate, UserFact, UserContact,
    RecallRequest, RecallResult,
    KnowledgeCategory, KnowledgeCategoryCreate, KnowledgeCategoryUpdate,
)
from app.infrastructure.database import get_session
from app.db.models import NoteModel, UserProfileModel, UserFactModel, UserContactModel, KnowledgeCategoryModel

logger = structlog.get_logger()


class KnowledgeService:
    """Service for knowledge management and second brain functionality."""

    # ==========================================================================
    # Embedding & Semantic Search
    # ==========================================================================

    async def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate an embedding vector for text via Ollama. Returns None on failure."""
        try:
            from app.infrastructure.ollama_client import get_ollama_client
            return await get_ollama_client().embed_safe(text)
        except Exception as e:
            logger.warning("embedding_generation_failed", error=str(e))
            return None

    async def semantic_search(
        self, query: str, *, limit: int = 10, table: str = "notes"
    ) -> List[Note]:
        """Search notes or facts using vector similarity (pgvector cosine distance).

        Falls back to text search if embedding fails or no vectors exist.
        """
        # Generate query embedding
        query_embedding = await self._generate_embedding(query)
        if query_embedding is None:
            logger.info("semantic_search_fallback_to_text", reason="embedding_failed")
            return await self.search_notes(query, limit=limit)

        async with get_session() as session:
            if table == "facts":
                result = await session.execute(
                    text(
                        "SELECT id, fact, category, confidence, source, learned_at "
                        "FROM user_facts WHERE embedding IS NOT NULL "
                        "ORDER BY embedding <=> :vec LIMIT :lim"
                    ),
                    {"vec": str(query_embedding), "lim": limit},
                )
                rows = result.fetchall()
                return [
                    {"id": r[0], "fact": r[1], "category": r[2],
                     "confidence": r[3], "source": r[4]}
                    for r in rows
                ]
            else:
                result = await session.execute(
                    text(
                        "SELECT id FROM notes WHERE embedding IS NOT NULL "
                        "ORDER BY embedding <=> :vec LIMIT :lim"
                    ),
                    {"vec": str(query_embedding), "lim": limit},
                )
                note_ids = [r[0] for r in result.fetchall()]

                if not note_ids:
                    # No embeddings yet — fall back to text search
                    return await self.search_notes(query, limit=limit)

                notes_result = await session.execute(
                    select(NoteModel).where(NoteModel.id.in_(note_ids))
                )
                rows = notes_result.scalars().all()
                # Preserve ordering from vector search
                row_map = {r.id: r for r in rows}
                return [self._orm_to_note(row_map[nid]) for nid in note_ids if nid in row_map]

    async def backfill_embeddings(self, batch_size: int = 20) -> Dict[str, int]:
        """Backfill embeddings for notes and facts that don't have them yet.

        Intended to be called as a background task after enabling pgvector.
        Returns counts of items embedded.
        """
        from app.infrastructure.ollama_client import get_ollama_client
        client = get_ollama_client()
        counts = {"notes": 0, "facts": 0}

        # Backfill notes
        async with get_session() as session:
            result = await session.execute(
                text(
                    "SELECT id, coalesce(title, '') || ' ' || content as text "
                    "FROM notes WHERE embedding IS NULL LIMIT :lim"
                ),
                {"lim": batch_size},
            )
            rows = result.fetchall()

        if rows:
            texts = [r[1] for r in rows]
            try:
                embeddings = await client.embed_batch(texts)
                for (row_id, _), emb in zip(rows, embeddings):
                    async with get_session() as session:
                        await session.execute(
                            text("UPDATE notes SET embedding = :emb WHERE id = :id"),
                            {"emb": str(emb), "id": row_id},
                        )
                    counts["notes"] += 1
            except Exception as e:
                logger.error("backfill_notes_failed", error=str(e))

        # Backfill facts
        async with get_session() as session:
            result = await session.execute(
                text(
                    "SELECT id, fact FROM user_facts WHERE embedding IS NULL LIMIT :lim"
                ),
                {"lim": batch_size},
            )
            rows = result.fetchall()

        if rows:
            texts = [r[1] for r in rows]
            try:
                embeddings = await client.embed_batch(texts)
                for (row_id, _), emb in zip(rows, embeddings):
                    async with get_session() as session:
                        await session.execute(
                            text("UPDATE user_facts SET embedding = :emb WHERE id = :id"),
                            {"emb": str(emb), "id": row_id},
                        )
                    counts["facts"] += 1
            except Exception as e:
                logger.error("backfill_facts_failed", error=str(e))

        logger.info("backfill_embeddings_complete", **counts)
        return counts

    # ==========================================================================
    # Note Operations
    # ==========================================================================

    async def create_note(self, note_data: NoteCreate) -> Note:
        """Create a new note."""
        async with get_session() as session:
            # Generate new note ID by counting existing notes + 1
            count_result = await session.execute(
                select(sa_func.count()).select_from(NoteModel)
            )
            next_id = count_result.scalar_one() + 1
            note_id = f"note-{next_id}"

            now = datetime.utcnow()

            # Generate embedding for semantic search (non-blocking)
            embed_text = f"{note_data.title or ''} {note_data.content}"
            embedding = await self._generate_embedding(embed_text)

            orm_obj = NoteModel(
                id=note_id,
                type=note_data.type.value if hasattr(note_data.type, 'value') else note_data.type,
                title=note_data.title,
                content=note_data.content,
                source=note_data.source.value if hasattr(note_data.source, 'value') else note_data.source,
                source_reference=note_data.source_reference,
                tags=note_data.tags or [],
                project_id=note_data.project_id,
                task_id=note_data.task_id,
                category_id=note_data.category_id,
                embedding=embedding,
                created_at=now,
            )

            session.add(orm_obj)
            await session.flush()

            note = self._orm_to_note(orm_obj)

        logger.info("Note created", note_id=note_id, type=note.type.value)
        return note

    async def list_notes(
        self,
        type_filter: Optional[NoteType] = None,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        search: Optional[str] = None,
        category_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Note]:
        """Get notes with optional filters."""
        async with get_session() as session:
            query = select(NoteModel)

            if type_filter:
                query = query.where(NoteModel.type == type_filter.value)
            if tags:
                # Match notes that have ANY of the requested tags (overlap)
                query = query.where(NoteModel.tags.overlap(tags))
            if project_id:
                query = query.where(NoteModel.project_id == project_id)
            if category_id:
                query = query.where(NoteModel.category_id == category_id)
            if search:
                search_pattern = f"%{search.lower()}%"
                query = query.where(
                    or_(
                        sa_func.lower(NoteModel.title).like(search_pattern),
                        sa_func.lower(NoteModel.content).like(search_pattern),
                    )
                )

            query = query.order_by(NoteModel.created_at.desc()).limit(limit)

            result = await session.execute(query)
            rows = result.scalars().all()

            return [self._orm_to_note(row) for row in rows]

    async def get_note(self, note_id: str) -> Optional[Note]:
        """Get note by ID."""
        async with get_session() as session:
            row = await session.get(NoteModel, note_id)
            if row is None:
                return None
            return self._orm_to_note(row)

    async def update_note(self, note_id: str, updates: NoteUpdate) -> Optional[Note]:
        """Update a note."""
        async with get_session() as session:
            row = await session.get(NoteModel, note_id)
            if row is None:
                return None

            update_dict = updates.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                if value is not None:
                    if hasattr(value, 'value'):
                        value = value.value
                    setattr(row, key, value)

            row.updated_at = datetime.utcnow()
            await session.flush()

            note = self._orm_to_note(row)

        logger.info("Note updated", note_id=note_id)
        return note

    async def delete_note(self, note_id: str) -> bool:
        """Delete a note."""
        async with get_session() as session:
            row = await session.get(NoteModel, note_id)
            if row is None:
                return False

            await session.delete(row)

        logger.info("Note deleted", note_id=note_id)
        return True

    async def search_notes(self, query: str, limit: int = 10) -> List[Note]:
        """Search notes by text (simple text search for now)."""
        return await self.list_notes(search=query, limit=limit)

    # ==========================================================================
    # User Profile Operations
    # ==========================================================================

    async def get_user_profile(self) -> UserProfile:
        """Get user profile (USER.md equivalent)."""
        async with get_session() as session:
            row = await session.get(UserProfileModel, 1)

            if row is None:
                # Return default profile
                return UserProfile()

            # Load facts
            facts_result = await session.execute(
                select(UserFactModel).order_by(UserFactModel.learned_at.desc())
            )
            fact_rows = facts_result.scalars().all()

            facts = [
                UserFact(
                    id=f.id,
                    fact=f.fact,
                    category=f.category,
                    confidence=f.confidence,
                    source=f.source,
                    learned_at=f.learned_at,
                )
                for f in fact_rows
            ]

            # Load contacts
            contacts_result = await session.execute(
                select(UserContactModel).order_by(UserContactModel.created_at.desc())
            )
            contact_rows = contacts_result.scalars().all()

            contacts = [
                UserContact(
                    name=c.name,
                    relation=c.relation,
                    email=c.email,
                    phone=c.phone,
                    notes=c.notes,
                )
                for c in contact_rows
            ]

            return UserProfile(
                name=row.name,
                timezone=row.timezone,
                facts=facts,
                preferences=row.preferences or {},
                communication_style=row.communication_style,
                work_hours=row.work_hours,
                interests=row.interests or [],
                skills=row.skills or [],
                contacts=contacts,
                goals=row.goals or [],
                updated_at=row.updated_at,
            )

    async def update_user_profile(self, updates: UserProfileUpdate) -> UserProfile:
        """Update user profile."""
        async with get_session() as session:
            row = await session.get(UserProfileModel, 1)

            if row is None:
                # Create default profile row
                row = UserProfileModel(id=1)
                session.add(row)
                await session.flush()

            update_dict = updates.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                if value is not None:
                    setattr(row, key, value)

            row.updated_at = datetime.utcnow()
            await session.flush()

        logger.info("User profile updated")
        return await self.get_user_profile()

    async def learn_fact(self, fact: str, category: str = "general", source: str = "manual") -> UserFact:
        """Learn a new fact about the user."""
        fact_id = f"fact-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow()

        async with get_session() as session:
            # Ensure profile row exists
            profile = await session.get(UserProfileModel, 1)
            if profile is None:
                session.add(UserProfileModel(id=1))

            # Generate embedding for semantic search
            embedding = await self._generate_embedding(fact)

            orm_obj = UserFactModel(
                id=fact_id,
                fact=fact,
                category=category,
                confidence=1.0,
                source=source,
                embedding=embedding,
                learned_at=now,
            )
            session.add(orm_obj)
            await session.flush()

        logger.info("Fact learned", fact_id=fact_id, category=category)

        return UserFact(
            id=fact_id,
            fact=fact,
            category=category,
            confidence=1.0,
            source=source,
            learned_at=now,
        )

    async def add_contact(self, contact: UserContact) -> UserProfile:
        """Add a contact to the user's network."""
        async with get_session() as session:
            # Ensure profile row exists
            profile = await session.get(UserProfileModel, 1)
            if profile is None:
                session.add(UserProfileModel(id=1))

            orm_obj = UserContactModel(
                name=contact.name,
                relation=contact.relation,
                email=contact.email,
                phone=contact.phone,
                notes=contact.notes,
            )
            session.add(orm_obj)
            await session.flush()

        logger.info("Contact added", name=contact.name)
        return await self.get_user_profile()

    # ==========================================================================
    # Memory Recall
    # ==========================================================================

    async def recall(self, request: RecallRequest) -> RecallResult:
        """Recall relevant memories based on context.

        Uses pgvector semantic search for notes and facts, with text-based fallback.
        """
        result = RecallResult()

        if request.include_notes:
            # Semantic search for notes (falls back to text if embeddings unavailable)
            result.notes = await self.semantic_search(
                request.context, limit=request.limit, table="notes"
            )

        if request.include_facts:
            # Semantic search for facts
            try:
                fact_results = await self.semantic_search(
                    request.context, limit=request.limit, table="facts"
                )
                # Convert dict results to UserFact objects
                result.facts = [
                    UserFact(
                        id=f.get("id", ""),
                        fact=f.get("fact", ""),
                        category=f.get("category", "general"),
                        confidence=f.get("confidence", 1.0),
                        source=f.get("source", "manual"),
                    )
                    if isinstance(f, dict) else f
                    for f in fact_results
                ]
            except Exception as e:
                logger.warning("semantic_fact_recall_failed", error=str(e))
                # Fallback to keyword matching
                profile = await self.get_user_profile()
                context_lower = request.context.lower()
                relevant_facts = []
                for fact in profile.facts:
                    if any(word in fact.fact.lower() for word in context_lower.split()):
                        relevant_facts.append(fact)
                result.facts = relevant_facts[:request.limit]

        if request.include_tasks:
            try:
                from app.services.task_service import get_task_service
                task_service = get_task_service()
                tasks = await task_service.list_tasks()
                context_lower = request.context.lower()
                related = []
                for task in tasks[:50]:
                    if context_lower in task.title.lower() or (task.description and context_lower in task.description.lower()):
                        related.append({
                            "id": task.id,
                            "title": task.title,
                            "status": task.status.value if hasattr(task.status, 'value') else task.status
                        })
                result.related_tasks = related[:request.limit]
            except Exception as e:
                logger.error("Failed to get related tasks", error=str(e))

        return result

    # ==========================================================================
    # Knowledge Categories
    # ==========================================================================

    async def list_categories(self, parent_id: Optional[str] = None, tree: bool = False) -> List[KnowledgeCategory]:
        """List categories, optionally as a tree structure."""
        async with get_session() as session:
            if tree:
                # Fetch all and build tree in Python
                result = await session.execute(
                    select(KnowledgeCategoryModel).order_by(KnowledgeCategoryModel.sort_order)
                )
                all_rows = result.scalars().all()
                return self._build_category_tree(all_rows)
            else:
                query = select(KnowledgeCategoryModel).order_by(KnowledgeCategoryModel.sort_order)
                if parent_id is not None:
                    query = query.where(KnowledgeCategoryModel.parent_id == parent_id)
                result = await session.execute(query)
                rows = result.scalars().all()
                return [self._orm_to_category(row) for row in rows]

    async def get_category(self, category_id: str) -> Optional[KnowledgeCategory]:
        """Get a single category by ID."""
        async with get_session() as session:
            row = await session.get(KnowledgeCategoryModel, category_id)
            if row is None:
                return None
            return self._orm_to_category(row)

    async def create_category(self, data: KnowledgeCategoryCreate) -> KnowledgeCategory:
        """Create a new knowledge category."""
        import re
        slug = data.slug or re.sub(r'[^a-z0-9]+', '-', data.name.lower()).strip('-')

        # If parent, prefix slug with parent slug
        if data.parent_id:
            async with get_session() as session:
                parent = await session.get(KnowledgeCategoryModel, data.parent_id)
                if parent:
                    slug = f"{parent.slug}/{slug}"

        cat_id = slug  # Use slug as ID for easy referencing

        async with get_session() as session:
            row = KnowledgeCategoryModel(
                id=cat_id,
                name=data.name,
                slug=slug,
                parent_id=data.parent_id,
                description=data.description,
                icon=data.icon,
                color=data.color,
                sort_order=data.sort_order,
                is_system=False,
            )
            session.add(row)
            await session.flush()

        logger.info("Category created", category_id=cat_id, name=data.name)
        return await self.get_category(cat_id)

    async def update_category(self, category_id: str, data: KnowledgeCategoryUpdate) -> Optional[KnowledgeCategory]:
        """Update a knowledge category."""
        async with get_session() as session:
            row = await session.get(KnowledgeCategoryModel, category_id)
            if row is None:
                return None

            update_dict = data.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                if value is not None:
                    setattr(row, key, value)
            await session.flush()

        logger.info("Category updated", category_id=category_id)
        return await self.get_category(category_id)

    async def delete_category(self, category_id: str) -> bool:
        """Delete a non-system category."""
        async with get_session() as session:
            row = await session.get(KnowledgeCategoryModel, category_id)
            if row is None:
                return False
            if row.is_system:
                return False  # Cannot delete system categories
            await session.delete(row)

        logger.info("Category deleted", category_id=category_id)
        return True

    async def get_category_stats(self) -> Dict[str, Any]:
        """Get note/fact counts per category."""
        async with get_session() as session:
            # Notes per category
            notes_result = await session.execute(
                select(NoteModel.category_id, sa_func.count())
                .where(NoteModel.category_id.isnot(None))
                .group_by(NoteModel.category_id)
            )
            notes_by_cat = {r[0]: r[1] for r in notes_result.all()}

            # Facts per category
            facts_result = await session.execute(
                select(UserFactModel.category_id, sa_func.count())
                .where(UserFactModel.category_id.isnot(None))
                .group_by(UserFactModel.category_id)
            )
            facts_by_cat = {r[0]: r[1] for r in facts_result.all()}

            return {
                "notes_by_category": notes_by_cat,
                "facts_by_category": facts_by_cat,
            }

    # ==========================================================================
    # Seeding
    # ==========================================================================

    DEFAULT_CATEGORIES = [
        # Root categories
        {"id": "ai-research", "name": "AI Research", "slug": "ai-research", "icon": "Brain", "color": "#6366f1", "sort_order": 0, "is_system": True},
        {"id": "trading", "name": "Trading", "slug": "trading", "icon": "TrendingUp", "color": "#10b981", "sort_order": 1, "is_system": True},
        {"id": "projects", "name": "Projects", "slug": "projects", "icon": "Folder", "color": "#f59e0b", "sort_order": 2, "is_system": True},
        {"id": "personal", "name": "Personal", "slug": "personal", "icon": "User", "color": "#ec4899", "sort_order": 3, "is_system": True},
        {"id": "general", "name": "General", "slug": "general", "icon": "BookOpen", "color": "#6b7280", "sort_order": 4, "is_system": True},
        # AI Research children
        {"id": "ai-research/frameworks", "name": "Frameworks", "slug": "ai-research/frameworks", "parent_id": "ai-research", "description": "LangGraph, LangChain, FastAPI, etc.", "sort_order": 0, "is_system": True},
        {"id": "ai-research/models-llms", "name": "Models & LLMs", "slug": "ai-research/models-llms", "parent_id": "ai-research", "description": "Ollama, model architectures, quantization", "sort_order": 1, "is_system": True},
        {"id": "ai-research/agents", "name": "Agents", "slug": "ai-research/agents", "parent_id": "ai-research", "description": "Multi-agent, orchestration, autonomous", "sort_order": 2, "is_system": True},
        {"id": "ai-research/tools-mcp", "name": "Tools & MCP", "slug": "ai-research/tools-mcp", "parent_id": "ai-research", "description": "MCP servers, plugins, skills, tool use", "sort_order": 3, "is_system": True},
        {"id": "ai-research/chat-ui", "name": "Chat UI", "slug": "ai-research/chat-ui", "parent_id": "ai-research", "description": "Chat frontends, UX patterns, AI interfaces", "sort_order": 4, "is_system": True},
        # Trading children
        {"id": "trading/options", "name": "Options", "slug": "trading/options", "parent_id": "trading", "description": "CSP, covered calls, wheel strategy", "sort_order": 0, "is_system": True},
        {"id": "trading/signals", "name": "Signals", "slug": "trading/signals", "parent_id": "trading", "description": "XTrades, alerts, signal analysis", "sort_order": 1, "is_system": True},
        {"id": "trading/market-analysis", "name": "Market Analysis", "slug": "trading/market-analysis", "parent_id": "trading", "description": "Technicals, macro, sector analysis", "sort_order": 2, "is_system": True},
        # Projects children
        {"id": "projects/zero", "name": "Zero", "slug": "projects/zero", "parent_id": "projects", "description": "This project (Zero AI assistant)", "sort_order": 0, "is_system": True},
        {"id": "projects/ada", "name": "Ada", "slug": "projects/ada", "parent_id": "projects", "sort_order": 1, "is_system": True},
        {"id": "projects/other", "name": "Other", "slug": "projects/other", "parent_id": "projects", "sort_order": 2, "is_system": True},
        # Personal children
        {"id": "personal/preferences", "name": "Preferences", "slug": "personal/preferences", "parent_id": "personal", "sort_order": 0, "is_system": True},
        {"id": "personal/goals", "name": "Goals", "slug": "personal/goals", "parent_id": "personal", "sort_order": 1, "is_system": True},
        {"id": "personal/contacts", "name": "Contacts", "slug": "personal/contacts", "parent_id": "personal", "sort_order": 2, "is_system": True},
    ]

    async def seed_default_categories(self) -> int:
        """Seed default knowledge categories if none exist. Returns count created."""
        async with get_session() as session:
            count_result = await session.execute(
                select(sa_func.count()).select_from(KnowledgeCategoryModel)
            )
            if count_result.scalar_one() > 0:
                return 0

        count = 0
        for cat_data in self.DEFAULT_CATEGORIES:
            async with get_session() as session:
                row = KnowledgeCategoryModel(
                    id=cat_data["id"],
                    name=cat_data["name"],
                    slug=cat_data["slug"],
                    parent_id=cat_data.get("parent_id"),
                    description=cat_data.get("description"),
                    icon=cat_data.get("icon"),
                    color=cat_data.get("color"),
                    sort_order=cat_data.get("sort_order", 0),
                    is_system=cat_data.get("is_system", True),
                )
                session.add(row)
            count += 1

        logger.info("Seeded default knowledge categories", count=count)
        return count

    # ==========================================================================
    # Utility Methods
    # ==========================================================================

    @staticmethod
    def _orm_to_category(row: KnowledgeCategoryModel) -> KnowledgeCategory:
        """Convert ORM row to Pydantic model."""
        return KnowledgeCategory(
            id=row.id,
            name=row.name,
            slug=row.slug,
            parent_id=row.parent_id,
            description=row.description,
            icon=row.icon,
            color=row.color,
            metadata=row.metadata_ or {},
            sort_order=row.sort_order,
            is_system=row.is_system,
            created_at=row.created_at,
        )

    def _build_category_tree(self, rows: list) -> List[KnowledgeCategory]:
        """Build a nested tree from flat list of category rows."""
        by_id = {}
        for row in rows:
            cat = self._orm_to_category(row)
            by_id[cat.id] = cat

        roots = []
        for cat in by_id.values():
            if cat.parent_id and cat.parent_id in by_id:
                by_id[cat.parent_id].children.append(cat)
            else:
                roots.append(cat)

        return roots

    @staticmethod
    def _orm_to_note(row: NoteModel) -> Note:
        """Convert a NoteModel ORM object to a Note Pydantic model."""
        return Note(
            id=row.id,
            type=row.type,
            title=row.title,
            content=row.content,
            source=row.source,
            source_reference=row.source_reference,
            tags=row.tags or [],
            project_id=row.project_id,
            task_id=row.task_id,
            category_id=row.category_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


@lru_cache()
def get_knowledge_service() -> KnowledgeService:
    """Get cached knowledge service instance."""
    return KnowledgeService()
