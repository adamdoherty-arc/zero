"""
Knowledge management data models for ZERO's Second Brain functionality.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class NoteType(str, Enum):
    """Type of knowledge note."""
    NOTE = "note"
    IDEA = "idea"
    FACT = "fact"
    PREFERENCE = "preference"
    MEMORY = "memory"
    BOOKMARK = "bookmark"
    SNIPPET = "snippet"


class NoteSource(str, Enum):
    """Source of the note."""
    MANUAL = "manual"
    WHATSAPP = "whatsapp"
    DISCORD = "discord"
    SLACK = "slack"
    AUDIO = "audio"
    EMAIL = "email"
    WEB_CLIP = "web_clip"
    TASK = "task"
    GITHUB = "github"


class NoteCreate(BaseModel):
    """Schema for creating a new note."""
    type: NoteType = NoteType.NOTE
    title: Optional[str] = None
    content: str = Field(..., min_length=1)
    source: NoteSource = NoteSource.MANUAL
    source_reference: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None
    task_id: Optional[str] = None


class NoteUpdate(BaseModel):
    """Schema for updating a note."""
    type: Optional[NoteType] = None
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    project_id: Optional[str] = None
    task_id: Optional[str] = None


class Note(BaseModel):
    """Full note model."""
    id: str
    type: NoteType = NoteType.NOTE
    title: Optional[str] = None
    content: str
    source: NoteSource = NoteSource.MANUAL
    source_reference: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    embedding: Optional[List[float]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserFact(BaseModel):
    """A fact learned about the user."""
    id: str
    fact: str
    category: str = "general"  # general, work, preference, skill, contact
    confidence: float = 1.0
    source: str = "manual"  # manual, inferred, conversation
    learned_at: datetime = Field(default_factory=datetime.utcnow)


class UserContact(BaseModel):
    """A contact in the user's network."""
    name: str
    relation: Optional[str] = None  # colleague, friend, family, etc.
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class UserProfile(BaseModel):
    """Long-term user profile (USER.md equivalent)."""
    name: str = "User"
    timezone: str = "America/New_York"
    facts: List[UserFact] = Field(default_factory=list)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    communication_style: Optional[str] = None
    work_hours: Optional[Dict[str, str]] = None  # {"start": "09:00", "end": "17:00"}
    interests: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    contacts: List[UserContact] = Field(default_factory=list)
    goals: List[str] = Field(default_factory=list)
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    """Schema for updating user profile."""
    name: Optional[str] = None
    timezone: Optional[str] = None
    communication_style: Optional[str] = None
    work_hours: Optional[Dict[str, str]] = None
    interests: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    goals: Optional[List[str]] = None


class IdentityConfig(BaseModel):
    """AI assistant identity configuration."""
    name: str = "ZERO"
    personality: str = "helpful, professional, proactive"
    voice_style: str = "concise and clear"
    expertise_areas: List[str] = Field(default_factory=list)
    greeting_style: Optional[str] = None
    sign_off_style: Optional[str] = None


class RecallRequest(BaseModel):
    """Request to recall relevant memories."""
    context: str
    limit: int = 5
    include_notes: bool = True
    include_facts: bool = True
    include_tasks: bool = False


class RecallResult(BaseModel):
    """Result from memory recall."""
    notes: List[Note] = Field(default_factory=list)
    facts: List[UserFact] = Field(default_factory=list)
    related_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Optional[str] = None
