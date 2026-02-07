"""
Knowledge management API endpoints.
Handles notes, user profile, and memory recall for ZERO's Second Brain.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
import structlog

from app.models.knowledge import (
    Note, NoteCreate, NoteUpdate, NoteType,
    UserProfile, UserProfileUpdate, UserFact, UserContact,
    RecallRequest, RecallResult
)
from app.services.knowledge_service import get_knowledge_service

router = APIRouter()
logger = structlog.get_logger()


# ==========================================================================
# Notes Endpoints
# ==========================================================================

@router.get("/notes", response_model=List[Note])
async def list_notes(
    type: Optional[NoteType] = Query(None, description="Filter by note type"),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter"),
    project_id: Optional[str] = Query(None, description="Filter by project"),
    search: Optional[str] = Query(None, description="Search in title and content"),
    limit: int = Query(50, ge=1, le=200, description="Maximum notes to return")
):
    """Get all notes with optional filters."""
    service = get_knowledge_service()
    tags_list = tags.split(",") if tags else None
    return await service.list_notes(
        type_filter=type,
        tags=tags_list,
        project_id=project_id,
        search=search,
        limit=limit
    )


@router.get("/notes/{note_id}", response_model=Note)
async def get_note(note_id: str):
    """Get note by ID."""
    service = get_knowledge_service()
    note = await service.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.post("/notes", response_model=Note)
async def create_note(note_data: NoteCreate):
    """Create a new note."""
    service = get_knowledge_service()
    return await service.create_note(note_data)


@router.patch("/notes/{note_id}", response_model=Note)
async def update_note(note_id: str, updates: NoteUpdate):
    """Update a note."""
    service = get_knowledge_service()
    note = await service.update_note(note_id, updates)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str):
    """Delete a note."""
    service = get_knowledge_service()
    deleted = await service.delete_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"status": "deleted", "note_id": note_id}


@router.get("/notes/search/{query}", response_model=List[Note])
async def search_notes(
    query: str,
    limit: int = Query(10, ge=1, le=50)
):
    """Search notes by text."""
    service = get_knowledge_service()
    return await service.search_notes(query, limit=limit)


# ==========================================================================
# User Profile Endpoints
# ==========================================================================

@router.get("/user", response_model=UserProfile)
async def get_user_profile():
    """Get user profile (USER.md equivalent)."""
    service = get_knowledge_service()
    return await service.get_user_profile()


@router.patch("/user", response_model=UserProfile)
async def update_user_profile(updates: UserProfileUpdate):
    """Update user profile."""
    service = get_knowledge_service()
    return await service.update_user_profile(updates)


@router.post("/user/facts", response_model=UserFact)
async def learn_fact(
    fact: str,
    category: str = Query("general", description="Fact category"),
    source: str = Query("manual", description="Source of the fact")
):
    """Learn a new fact about the user."""
    service = get_knowledge_service()
    return await service.learn_fact(fact, category=category, source=source)


@router.post("/user/contacts", response_model=UserProfile)
async def add_contact(contact: UserContact):
    """Add a contact to the user's network."""
    service = get_knowledge_service()
    return await service.add_contact(contact)


# ==========================================================================
# Memory Recall Endpoints
# ==========================================================================

@router.post("/recall", response_model=RecallResult)
async def recall_memories(request: RecallRequest):
    """Recall relevant memories based on context.

    This endpoint searches through notes, facts, and optionally tasks
    to find information relevant to the given context.
    """
    service = get_knowledge_service()
    return await service.recall(request)


@router.get("/recall/{context}", response_model=RecallResult)
async def recall_memories_get(
    context: str,
    limit: int = Query(5, ge=1, le=20),
    include_notes: bool = Query(True),
    include_facts: bool = Query(True),
    include_tasks: bool = Query(False)
):
    """Recall relevant memories based on context (GET version)."""
    service = get_knowledge_service()
    request = RecallRequest(
        context=context,
        limit=limit,
        include_notes=include_notes,
        include_facts=include_facts,
        include_tasks=include_tasks
    )
    return await service.recall(request)


# ==========================================================================
# Stats and Summary Endpoints
# ==========================================================================

@router.get("/stats")
async def get_knowledge_stats() -> Dict[str, Any]:
    """Get knowledge base statistics."""
    service = get_knowledge_service()

    notes = await service.list_notes(limit=1000)
    profile = await service.get_user_profile()

    # Count by type
    by_type = {}
    for note in notes:
        note_type = note.type.value if hasattr(note.type, 'value') else note.type
        by_type[note_type] = by_type.get(note_type, 0) + 1

    # Count by source
    by_source = {}
    for note in notes:
        source = note.source.value if hasattr(note.source, 'value') else note.source
        by_source[source] = by_source.get(source, 0) + 1

    # Get all tags
    all_tags = set()
    for note in notes:
        all_tags.update(note.tags)

    return {
        "total_notes": len(notes),
        "by_type": by_type,
        "by_source": by_source,
        "total_tags": len(all_tags),
        "top_tags": list(all_tags)[:10],
        "total_facts": len(profile.facts),
        "total_contacts": len(profile.contacts),
        "total_skills": len(profile.skills),
        "total_interests": len(profile.interests),
    }
