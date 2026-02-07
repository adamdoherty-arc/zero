"""
Email data models for ZERO.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class EmailCategory(str, Enum):
    """Email classification categories."""
    URGENT = "urgent"
    IMPORTANT = "important"
    NORMAL = "normal"
    LOW_PRIORITY = "low_priority"
    SPAM = "spam"
    NEWSLETTER = "newsletter"


class EmailStatus(str, Enum):
    """Email processing status."""
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"
    DELETED = "deleted"


class EmailAddress(BaseModel):
    """Email address with optional name."""
    email: str
    name: Optional[str] = None


class EmailAttachment(BaseModel):
    """Email attachment metadata."""
    filename: str
    mime_type: str
    size_bytes: int
    attachment_id: Optional[str] = None


class Email(BaseModel):
    """Full email model."""
    id: str
    thread_id: str
    subject: str
    snippet: str
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    from_address: EmailAddress
    to_addresses: List[EmailAddress] = Field(default_factory=list)
    cc_addresses: List[EmailAddress] = Field(default_factory=list)
    bcc_addresses: List[EmailAddress] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)
    attachments: List[EmailAttachment] = Field(default_factory=list)
    category: EmailCategory = EmailCategory.NORMAL
    status: EmailStatus = EmailStatus.UNREAD
    is_starred: bool = False
    is_important: bool = False
    received_at: datetime
    internal_date: int  # Gmail internal timestamp
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class EmailSummary(BaseModel):
    """Lightweight email summary for lists."""
    id: str
    thread_id: str
    subject: str
    snippet: str
    from_address: EmailAddress
    category: EmailCategory = EmailCategory.NORMAL
    status: EmailStatus = EmailStatus.UNREAD
    is_starred: bool = False
    is_important: bool = False
    has_attachments: bool = False
    received_at: datetime


class EmailThread(BaseModel):
    """Email thread/conversation."""
    id: str
    subject: str
    messages: List[Email] = Field(default_factory=list)
    message_count: int = 0
    participants: List[EmailAddress] = Field(default_factory=list)
    snippet: str
    labels: List[str] = Field(default_factory=list)
    last_message_at: datetime


class EmailLabel(BaseModel):
    """Gmail label."""
    id: str
    name: str
    type: str  # 'system' or 'user'
    message_count: int = 0
    unread_count: int = 0


class GmailCredentials(BaseModel):
    """Gmail OAuth credentials."""
    access_token: str
    refresh_token: str
    token_uri: str
    client_id: str
    client_secret: str
    scopes: List[str]
    expiry: Optional[datetime] = None


class EmailSyncStatus(BaseModel):
    """Email sync status."""
    connected: bool = False
    email_address: Optional[str] = None
    last_sync: Optional[datetime] = None
    total_messages: int = 0
    unread_count: int = 0
    sync_errors: List[str] = Field(default_factory=list)


class EmailDigest(BaseModel):
    """Daily email digest."""
    date: datetime
    total_emails: int = 0
    unread_emails: int = 0
    by_category: Dict[str, int] = Field(default_factory=dict)
    urgent_emails: List[EmailSummary] = Field(default_factory=list)
    important_emails: List[EmailSummary] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)


class EmailToTaskRequest(BaseModel):
    """Request to convert email to task."""
    email_id: str
    sprint_id: Optional[str] = None
    project_id: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
