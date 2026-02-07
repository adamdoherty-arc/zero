"""
Knowledge management service for ZERO's Second Brain functionality.
Handles notes, user profile, and memory recall.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache
import structlog

from app.models.knowledge import (
    Note, NoteCreate, NoteUpdate, NoteType, NoteSource,
    UserProfile, UserProfileUpdate, UserFact, UserContact,
    RecallRequest, RecallResult
)
from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger()


class KnowledgeService:
    """Service for knowledge management and second brain functionality."""

    def __init__(self):
        self.storage = JsonStorage(get_workspace_path("knowledge"))
        self._notes_file = "notes.json"
        self._user_file = "user.json"

    async def _load_notes_data(self) -> Dict[str, Any]:
        """Load notes data from storage."""
        return await self.storage.read(self._notes_file)

    async def _save_notes_data(self, data: Dict[str, Any]) -> bool:
        """Save notes data to storage."""
        return await self.storage.write(self._notes_file, data)

    async def _load_user_data(self) -> Dict[str, Any]:
        """Load user profile data from storage."""
        return await self.storage.read(self._user_file)

    async def _save_user_data(self, data: Dict[str, Any]) -> bool:
        """Save user profile data to storage."""
        return await self.storage.write(self._user_file, data)

    def _normalize_note_data(self, note_data: Dict) -> Dict:
        """Normalize note data from storage format to Pydantic model format."""
        return {
            "id": note_data.get("id"),
            "type": note_data.get("type", "note"),
            "title": note_data.get("title"),
            "content": note_data.get("content"),
            "source": note_data.get("source", "manual"),
            "source_reference": note_data.get("sourceReference"),
            "tags": note_data.get("tags", []),
            "project_id": note_data.get("projectId"),
            "task_id": note_data.get("taskId"),
            "embedding": note_data.get("embedding"),
            "created_at": note_data.get("createdAt"),
            "updated_at": note_data.get("updatedAt"),
        }

    def _to_storage_format(self, note: Note) -> Dict:
        """Convert note to storage format (camelCase)."""
        return {
            "id": note.id,
            "type": note.type.value if hasattr(note.type, 'value') else note.type,
            "title": note.title,
            "content": note.content,
            "source": note.source.value if hasattr(note.source, 'value') else note.source,
            "sourceReference": note.source_reference,
            "tags": note.tags,
            "projectId": note.project_id,
            "taskId": note.task_id,
            "embedding": note.embedding,
            "createdAt": note.created_at.isoformat() if note.created_at else None,
            "updatedAt": note.updated_at.isoformat() if note.updated_at else None,
        }

    # ==========================================================================
    # Note Operations
    # ==========================================================================

    async def create_note(self, note_data: NoteCreate) -> Note:
        """Create a new note."""
        data = await self._load_notes_data()

        # Generate new note ID
        next_id = data.get("nextNoteId", 1)
        note_id = f"note-{next_id}"

        now = datetime.utcnow()

        note = Note(
            id=note_id,
            type=note_data.type,
            title=note_data.title,
            content=note_data.content,
            source=note_data.source,
            source_reference=note_data.source_reference,
            tags=note_data.tags,
            project_id=note_data.project_id,
            task_id=note_data.task_id,
            created_at=now
        )

        # Add to notes list
        notes = data.get("notes", [])
        notes.append(self._to_storage_format(note))

        # Update data
        data["notes"] = notes
        data["nextNoteId"] = next_id + 1

        await self._save_notes_data(data)

        logger.info("Note created", note_id=note_id, type=note.type.value)
        return note

    async def list_notes(
        self,
        type_filter: Optional[NoteType] = None,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50
    ) -> List[Note]:
        """Get notes with optional filters."""
        data = await self._load_notes_data()
        notes_data = data.get("notes", [])

        notes = []
        for n in notes_data:
            # Apply filters
            if type_filter and n.get("type") != type_filter.value:
                continue
            if tags:
                note_tags = set(n.get("tags", []))
                if not note_tags.intersection(set(tags)):
                    continue
            if project_id and n.get("projectId") != project_id:
                continue
            if search:
                search_lower = search.lower()
                title = (n.get("title") or "").lower()
                content = (n.get("content") or "").lower()
                if search_lower not in title and search_lower not in content:
                    continue

            normalized = self._normalize_note_data(n)
            notes.append(Note(**normalized))

            if len(notes) >= limit:
                break

        # Sort by created_at descending
        notes.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
        return notes

    async def get_note(self, note_id: str) -> Optional[Note]:
        """Get note by ID."""
        data = await self._load_notes_data()
        for n in data.get("notes", []):
            if n["id"] == note_id:
                normalized = self._normalize_note_data(n)
                return Note(**normalized)
        return None

    async def update_note(self, note_id: str, updates: NoteUpdate) -> Optional[Note]:
        """Update a note."""
        data = await self._load_notes_data()
        notes = data.get("notes", [])

        for i, n in enumerate(notes):
            if n["id"] == note_id:
                # Apply updates
                update_dict = updates.model_dump(exclude_unset=True)
                for key, value in update_dict.items():
                    if value is not None:
                        # Convert snake_case to camelCase for storage
                        storage_key = self._to_camel_case(key)
                        # Handle enums
                        if hasattr(value, 'value'):
                            value = value.value
                        n[storage_key] = value

                n["updatedAt"] = datetime.utcnow().isoformat()
                notes[i] = n
                data["notes"] = notes
                await self._save_notes_data(data)

                logger.info("Note updated", note_id=note_id)
                normalized = self._normalize_note_data(n)
                return Note(**normalized)

        return None

    async def delete_note(self, note_id: str) -> bool:
        """Delete a note."""
        data = await self._load_notes_data()
        notes = data.get("notes", [])

        for i, n in enumerate(notes):
            if n["id"] == note_id:
                del notes[i]
                data["notes"] = notes
                await self._save_notes_data(data)
                logger.info("Note deleted", note_id=note_id)
                return True

        return False

    async def search_notes(self, query: str, limit: int = 10) -> List[Note]:
        """Search notes by text (simple text search for now)."""
        return await self.list_notes(search=query, limit=limit)

    # ==========================================================================
    # User Profile Operations
    # ==========================================================================

    async def get_user_profile(self) -> UserProfile:
        """Get user profile (USER.md equivalent)."""
        data = await self._load_user_data()

        if not data:
            # Return default profile
            return UserProfile()

        # Normalize facts
        facts = []
        for f in data.get("facts", []):
            facts.append(UserFact(
                id=f.get("id", str(uuid.uuid4())),
                fact=f.get("fact"),
                category=f.get("category", "general"),
                confidence=f.get("confidence", 1.0),
                source=f.get("source", "manual"),
                learned_at=datetime.fromisoformat(f["learnedAt"]) if f.get("learnedAt") else datetime.utcnow()
            ))

        # Normalize contacts
        contacts = []
        for c in data.get("contacts", []):
            contacts.append(UserContact(
                name=c.get("name"),
                relation=c.get("relation"),
                email=c.get("email"),
                phone=c.get("phone"),
                notes=c.get("notes")
            ))

        return UserProfile(
            name=data.get("name", "User"),
            timezone=data.get("timezone", "America/New_York"),
            facts=facts,
            preferences=data.get("preferences", {}),
            communication_style=data.get("communicationStyle"),
            work_hours=data.get("workHours"),
            interests=data.get("interests", []),
            skills=data.get("skills", []),
            contacts=contacts,
            goals=data.get("goals", []),
            updated_at=datetime.fromisoformat(data["updatedAt"]) if data.get("updatedAt") else None
        )

    async def update_user_profile(self, updates: UserProfileUpdate) -> UserProfile:
        """Update user profile."""
        data = await self._load_user_data()
        if not data:
            data = {}

        update_dict = updates.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            if value is not None:
                storage_key = self._to_camel_case(key)
                data[storage_key] = value

        data["updatedAt"] = datetime.utcnow().isoformat()

        await self._save_user_data(data)
        logger.info("User profile updated")

        return await self.get_user_profile()

    async def learn_fact(self, fact: str, category: str = "general", source: str = "manual") -> UserFact:
        """Learn a new fact about the user."""
        data = await self._load_user_data()
        if not data:
            data = {"facts": []}

        fact_id = f"fact-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow()

        user_fact = UserFact(
            id=fact_id,
            fact=fact,
            category=category,
            confidence=1.0,
            source=source,
            learned_at=now
        )

        facts = data.get("facts", [])
        facts.append({
            "id": fact_id,
            "fact": fact,
            "category": category,
            "confidence": 1.0,
            "source": source,
            "learnedAt": now.isoformat()
        })

        data["facts"] = facts
        data["updatedAt"] = now.isoformat()

        await self._save_user_data(data)
        logger.info("Fact learned", fact_id=fact_id, category=category)

        return user_fact

    async def add_contact(self, contact: UserContact) -> UserProfile:
        """Add a contact to the user's network."""
        data = await self._load_user_data()
        if not data:
            data = {"contacts": []}

        contacts = data.get("contacts", [])
        contacts.append({
            "name": contact.name,
            "relation": contact.relation,
            "email": contact.email,
            "phone": contact.phone,
            "notes": contact.notes
        })

        data["contacts"] = contacts
        data["updatedAt"] = datetime.utcnow().isoformat()

        await self._save_user_data(data)
        logger.info("Contact added", name=contact.name)

        return await self.get_user_profile()

    # ==========================================================================
    # Memory Recall
    # ==========================================================================

    async def recall(self, request: RecallRequest) -> RecallResult:
        """Recall relevant memories based on context.

        This is a simple text-based recall for now.
        Can be enhanced with vector embeddings for semantic search.
        """
        result = RecallResult()

        if request.include_notes:
            # Search notes by context
            result.notes = await self.search_notes(request.context, limit=request.limit)

        if request.include_facts:
            # Get relevant facts
            profile = await self.get_user_profile()
            context_lower = request.context.lower()
            relevant_facts = []
            for fact in profile.facts:
                if any(word in fact.fact.lower() for word in context_lower.split()):
                    relevant_facts.append(fact)
            result.facts = relevant_facts[:request.limit]

        if request.include_tasks:
            # Get related tasks (import here to avoid circular import)
            try:
                from app.services.task_service import get_task_service
                task_service = get_task_service()
                tasks = await task_service.list_tasks()
                context_lower = request.context.lower()
                related = []
                for task in tasks[:50]:  # Limit search
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
    # Utility Methods
    # ==========================================================================

    def _to_camel_case(self, snake_str: str) -> str:
        """Convert snake_case to camelCase."""
        components = snake_str.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])


@lru_cache()
def get_knowledge_service() -> KnowledgeService:
    """Get cached knowledge service instance."""
    return KnowledgeService()
