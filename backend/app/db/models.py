"""
SQLAlchemy ORM models for ZERO API.

All tables for the PostgreSQL database, replacing JSON file storage.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.infrastructure.database import Base


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    project_type: Mapped[str] = mapped_column(String(20), default="local")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    scan_config: Mapped[Optional[dict]] = mapped_column(JSONB, default={})
    tags: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])

    # Scan metadata
    last_scan: Mapped[Optional[dict]] = mapped_column(JSONB)
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    open_signals: Mapped[int] = mapped_column(Integer, default=0)

    # Git metadata
    git_remote: Mapped[Optional[str]] = mapped_column(Text)
    git_branch: Mapped[Optional[str]] = mapped_column(String(200))
    last_commit_hash: Mapped[Optional[str]] = mapped_column(String(64))
    last_commit_message: Mapped[Optional[str]] = mapped_column(Text)

    # GitHub integration
    github_repo_url: Mapped[Optional[str]] = mapped_column(Text)
    github_owner: Mapped[Optional[str]] = mapped_column(String(200))
    github_repo: Mapped[Optional[str]] = mapped_column(String(200))
    github_default_branch: Mapped[Optional[str]] = mapped_column(String(200))
    github_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    github_last_sync: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    github_sync_issues: Mapped[bool] = mapped_column(Boolean, default=True)
    github_sync_prs: Mapped[bool] = mapped_column(Boolean, default=True)
    github_open_issues: Mapped[int] = mapped_column(Integer, default=0)
    github_open_prs: Mapped[int] = mapped_column(Integer, default=0)
    github_stars: Mapped[int] = mapped_column(Integer, default=0)
    github_forks: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Sprints
# ---------------------------------------------------------------------------

class SprintModel(Base):
    __tablename__ = "sprints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="planning", index=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_days: Mapped[int] = mapped_column(Integer, default=14)
    goals: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    completed_points: Mapped[int] = mapped_column(Integer, default=0)
    project_id: Mapped[Optional[int]] = mapped_column(Integer)
    project_name: Mapped[Optional[str]] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sprint_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="backlog", index=True)
    category: Mapped[str] = mapped_column(String(20), default="feature")
    priority: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    points: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30), default="MANUAL")
    source_reference: Mapped[Optional[str]] = mapped_column(Text)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Knowledge - Categories (hierarchical taxonomy)
# ---------------------------------------------------------------------------

class KnowledgeCategoryModel(Base):
    __tablename__ = "knowledge_categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[Optional[str]] = mapped_column(String(50))
    color: Mapped[Optional[str]] = mapped_column(String(7))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default={})
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Knowledge - Notes
# ---------------------------------------------------------------------------

class NoteModel(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(20), default="note", index=True)
    title: Mapped[Optional[str]] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    source_reference: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    project_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64))
    category_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), index=True)
    embedding = mapped_column(Vector(768), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("idx_notes_tags", "tags", postgresql_using="gin"),
    )


# ---------------------------------------------------------------------------
# Knowledge - User Profile (singleton)
# ---------------------------------------------------------------------------

class UserProfileModel(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(200), default="User")
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")
    preferences: Mapped[Optional[dict]] = mapped_column(JSONB, default={})
    communication_style: Mapped[Optional[str]] = mapped_column(Text)
    work_hours: Mapped[Optional[dict]] = mapped_column(JSONB)
    interests: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    skills: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    goals: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("id = 1", name="single_profile_row"),
    )


class UserFactModel(Base):
    __tablename__ = "user_facts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    category_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), index=True)
    embedding = mapped_column(Vector(768), nullable=True)
    learned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserContactModel(Base):
    __tablename__ = "user_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    relation: Mapped[Optional[str]] = mapped_column(String(100))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------

class ResearchTopicModel(Base):
    __tablename__ = "research_topics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    search_queries: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    aspects: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    category_tags: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    frequency: Mapped[str] = mapped_column(String(10), default="daily")
    last_researched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    relevance_score: Mapped[float] = mapped_column(Float, default=50.0)
    category_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchFindingModel(Base):
    __tablename__ = "research_findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="")
    source_engine: Mapped[Optional[str]] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(20), default="other")
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)

    # Scoring
    relevance_score: Mapped[float] = mapped_column(Float, default=50.0)
    novelty_score: Mapped[float] = mapped_column(Float, default=50.0)
    actionability_score: Mapped[float] = mapped_column(Float, default=50.0)
    composite_score: Mapped[float] = mapped_column(Float, default=50.0)

    # LLM analysis
    llm_summary: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    suggested_task: Mapped[Optional[str]] = mapped_column(Text)
    linked_task_id: Mapped[Optional[str]] = mapped_column(String(64))
    category_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), index=True)
    fired_rule_ids: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    embedding = mapped_column(Vector(768), nullable=True)

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_research_findings_score", "composite_score"),
        Index("idx_research_findings_url", "url"),
    )


class ResearchCycleModel(Base):
    __tablename__ = "research_cycles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    topics_researched: Mapped[int] = mapped_column(Integer, default=0)
    total_results: Mapped[int] = mapped_column(Integer, default=0)
    new_findings: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_filtered: Mapped[int] = mapped_column(Integer, default=0)
    high_value_findings: Mapped[int] = mapped_column(Integer, default=0)
    tasks_created: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])


# ---------------------------------------------------------------------------
# Research Rules (dynamic rules engine)
# ---------------------------------------------------------------------------

class ResearchRuleModel(Base):
    __tablename__ = "research_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    # Conditions and actions stored as JSONB
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actions: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Metadata
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    category_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), index=True)

    # Self-improvement tracking
    times_fired: Mapped[int] = mapped_column(Integer, default=0)
    times_useful: Mapped[int] = mapped_column(Integer, default=0)
    effectiveness_score: Mapped[float] = mapped_column(Float, default=50.0)

    # Audit
    created_by: Mapped[str] = mapped_column(String(50), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Money Maker
# ---------------------------------------------------------------------------

class MoneyIdeaModel(Base):
    __tablename__ = "money_ideas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20), default="other")
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)

    # Scoring
    revenue_potential: Mapped[float] = mapped_column(Float, default=0)
    effort_score: Mapped[float] = mapped_column(Float, default=50)
    time_to_roi: Mapped[str] = mapped_column(String(20), default="medium")
    market_validation: Mapped[float] = mapped_column(Float, default=50)
    competition_score: Mapped[float] = mapped_column(Float, default=50)
    skill_match: Mapped[float] = mapped_column(Float, default=50)
    viability_score: Mapped[float] = mapped_column(Float, default=0)

    # Research data
    research_notes: Mapped[Optional[str]] = mapped_column(Text)
    market_size: Mapped[Optional[str]] = mapped_column(Text)
    competitors: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    resources_needed: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    first_steps: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])

    source: Mapped[str] = mapped_column(String(30), default="llm_generated")
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    park_reason: Mapped[Optional[str]] = mapped_column(Text)
    linked_task_ids: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_researched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Enhancement Signals
# ---------------------------------------------------------------------------

class EnhancementSignalModel(Base):
    __tablename__ = "enhancement_signals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    source_file: Mapped[Optional[str]] = mapped_column(Text)
    line_number: Mapped[Optional[int]] = mapped_column(Integer)
    context: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=80.0)
    impact_score: Mapped[float] = mapped_column(Float, default=50.0)
    risk_score: Mapped[float] = mapped_column(Float, default=30.0)
    priority_score: Mapped[float] = mapped_column(Float, default=0)
    project_name: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    converted_to_task: Mapped[Optional[str]] = mapped_column(String(64))
    converted_to_legion_task: Mapped[Optional[int]] = mapped_column(Integer)
    converted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class NotificationModel(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="ui")
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    action_url: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(String(50))
    source_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_notifications_created", "created_at"),
    )


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

class ReminderModel(Base):
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    trigger_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    recurrence: Mapped[str] = mapped_column(String(20), default="once")
    cron_expression: Mapped[Optional[str]] = mapped_column(String(100))
    channels: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=["ui"])
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    snooze_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    task_id: Mapped[Optional[str]] = mapped_column(String(64))
    project_id: Mapped[Optional[str]] = mapped_column(String(64))
    tags: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Email Cache (Gmail sync)
# ---------------------------------------------------------------------------

class EmailCacheModel(Base):
    __tablename__ = "email_cache"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    subject: Mapped[Optional[str]] = mapped_column(Text)
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    from_address: Mapped[Optional[dict]] = mapped_column(JSONB)
    to_addresses: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    cc_addresses: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    labels: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    attachments: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    category: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    status: Mapped[str] = mapped_column(String(20), default="unread")
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    is_important: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    internal_date: Mapped[Optional[int]] = mapped_column(BigInteger)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_email_received", "received_at"),
    )


# ---------------------------------------------------------------------------
# Calendar Event Cache (Google Calendar sync)
# ---------------------------------------------------------------------------

class CalendarEventCacheModel(Base):
    __tablename__ = "calendar_event_cache"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    calendar_id: Mapped[str] = mapped_column(String(100), default="primary")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text)
    start_dt: Mapped[dict] = mapped_column(JSONB, nullable=False)
    end_dt: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    visibility: Mapped[str] = mapped_column(String(20), default="default")
    html_link: Mapped[Optional[str]] = mapped_column(Text)
    hangout_link: Mapped[Optional[str]] = mapped_column(Text)
    attendees: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    reminders: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    recurrence: Mapped[Optional[list]] = mapped_column(ARRAY(Text))
    recurring_event_id: Mapped[Optional[str]] = mapped_column(String(255))
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Sync Status (Gmail, Calendar)
# ---------------------------------------------------------------------------

class SyncStatusModel(Base):
    __tablename__ = "sync_status"

    service_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    email_address: Mapped[Optional[str]] = mapped_column(String(200))
    last_sync: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default={})
    errors: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])


# ---------------------------------------------------------------------------
# Scheduler Audit Log
# ---------------------------------------------------------------------------

class SchedulerAuditLogModel(Base):
    __tablename__ = "scheduler_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_audit_created", "created_at"),
    )


# ---------------------------------------------------------------------------
# Service Configs (generic key-value store)
# ---------------------------------------------------------------------------

class ServiceConfigModel(Base):
    __tablename__ = "service_configs"

    service_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default={})
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------

class AgentStateModel(Base):
    __tablename__ = "agent_state"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="main")
    current_task: Mapped[Optional[dict]] = mapped_column(JSONB)
    queue: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    history: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    status: Mapped[str] = mapped_column(String(20), default="idle")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# Email Rules
# ---------------------------------------------------------------------------

class MetricsSnapshotModel(Base):
    __tablename__ = "metrics_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    metrics_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    period: Mapped[str] = mapped_column(String(20), default="hourly")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Email Rules
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TikTok Shop Products
# ---------------------------------------------------------------------------

class TikTokProductModel(Base):
    __tablename__ = "tiktok_products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="general", index=True)
    niche: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Discovery metadata
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    source_engine: Mapped[Optional[str]] = mapped_column(String(50))
    marketplace_url: Mapped[Optional[str]] = mapped_column(Text)
    product_type: Mapped[str] = mapped_column(String(20), default="unknown", index=True)

    # Market scoring (3-layer: heuristic -> LLM -> rules)
    trend_score: Mapped[float] = mapped_column(Float, default=50.0)
    competition_score: Mapped[float] = mapped_column(Float, default=50.0)
    margin_score: Mapped[float] = mapped_column(Float, default=50.0)
    opportunity_score: Mapped[float] = mapped_column(Float, default=50.0)

    # Market data
    price_range_min: Mapped[Optional[float]] = mapped_column(Float)
    price_range_max: Mapped[Optional[float]] = mapped_column(Float)
    estimated_monthly_sales: Mapped[Optional[int]] = mapped_column(Integer)
    competitor_count: Mapped[Optional[int]] = mapped_column(Integer)
    commission_rate: Mapped[Optional[float]] = mapped_column(Float)
    tags: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    llm_analysis: Mapped[Optional[str]] = mapped_column(Text)
    content_ideas: Mapped[Optional[list]] = mapped_column(JSONB, default=[])

    # Workflow
    status: Mapped[str] = mapped_column(String(20), default="discovered", index=True)
    linked_content_topic_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    linked_legion_task_id: Mapped[Optional[str]] = mapped_column(String(64))
    embedding = mapped_column(Vector(768), nullable=True)

    # Approval tracking
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)

    # LLM extraction metadata
    source_article_title: Mapped[Optional[str]] = mapped_column(String(500))
    source_article_url: Mapped[Optional[str]] = mapped_column(Text)
    is_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    why_trending: Mapped[Optional[str]] = mapped_column(Text)
    estimated_price_range: Mapped[Optional[str]] = mapped_column(String(50))

    # Images
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    image_urls: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    image_search_done: Mapped[bool] = mapped_column(Boolean, default=False)
    image_validated: Mapped[bool] = mapped_column(Boolean, default=False)

    # Success rating
    success_rating: Mapped[Optional[float]] = mapped_column(Float)
    success_factors: Mapped[Optional[dict]] = mapped_column(JSONB, default={})

    # Sourcing
    supplier_url: Mapped[Optional[str]] = mapped_column(Text)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(200))
    sourcing_method: Mapped[Optional[str]] = mapped_column(String(50))
    sourcing_notes: Mapped[Optional[str]] = mapped_column(Text)
    sourcing_links: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    listing_steps: Mapped[Optional[list]] = mapped_column(JSONB, default=[])

    # Affiliate & import tracking
    affiliate_link: Mapped[Optional[str]] = mapped_column(Text)
    tiktok_shop_url: Mapped[Optional[str]] = mapped_column(Text)
    import_url: Mapped[Optional[str]] = mapped_column(Text)
    import_source: Mapped[Optional[str]] = mapped_column(String(30))

    # Content performance feedback (Sprint 2)
    content_performance_score: Mapped[Optional[float]] = mapped_column(Float)
    best_template_type: Mapped[Optional[str]] = mapped_column(String(30))
    last_performance_update_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_researched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_tiktok_products_score", "opportunity_score"),
    )


# ---------------------------------------------------------------------------
# Content Topics
# ---------------------------------------------------------------------------

class ContentTopicModel(Base):
    __tablename__ = "content_topics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    niche: Mapped[str] = mapped_column(String(100), default="general", index=True)
    platform: Mapped[str] = mapped_column(String(30), default="tiktok", index=True)

    # Associated product (optional)
    tiktok_product_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    # Rules (LLM-generated and user-refined)
    rules: Mapped[Optional[list]] = mapped_column(JSONB, default=[])

    # Content parameters
    content_style: Mapped[Optional[str]] = mapped_column(String(50))
    target_audience: Mapped[Optional[str]] = mapped_column(Text)
    tone_guidelines: Mapped[Optional[str]] = mapped_column(Text)
    hashtag_strategy: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])

    # Performance
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    examples_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_performance_score: Mapped[float] = mapped_column(Float, default=0.0)
    content_generated_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Content Examples
# ---------------------------------------------------------------------------

class ContentExampleModel(Base):
    __tablename__ = "content_examples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic_id: Mapped[str] = mapped_column(String(64), ForeignKey("content_topics.id", ondelete="CASCADE"), index=True)

    # Content
    title: Mapped[Optional[str]] = mapped_column(Text)
    caption: Mapped[Optional[str]] = mapped_column(Text)
    script: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(String(30), default="tiktok")

    # Performance (if known)
    views: Mapped[Optional[int]] = mapped_column(Integer)
    likes: Mapped[Optional[int]] = mapped_column(Integer)
    comments: Mapped[Optional[int]] = mapped_column(Integer)
    shares: Mapped[Optional[int]] = mapped_column(Integer)
    performance_score: Mapped[float] = mapped_column(Float, default=50.0)

    # Metadata
    source: Mapped[str] = mapped_column(String(30), default="manual")
    rule_contributions: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    embedding = mapped_column(Vector(768), nullable=True)

    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_content_examples_perf", "performance_score"),
    )


# ---------------------------------------------------------------------------
# Content Performance
# ---------------------------------------------------------------------------

class ContentPerformanceModel(Base):
    __tablename__ = "content_performance"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic_id: Mapped[str] = mapped_column(String(64), index=True)
    tiktok_product_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    # AIContentTools reference
    act_generation_id: Mapped[Optional[str]] = mapped_column(String(64))
    act_persona_id: Mapped[Optional[str]] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(30), default="tiktok")

    # Content metadata
    content_type: Mapped[str] = mapped_column(String(30), default="video")
    caption: Mapped[Optional[str]] = mapped_column(Text)
    hashtags: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    rules_applied: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])

    # Metrics
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    performance_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Feedback
    feedback_processed: Mapped[bool] = mapped_column(Boolean, default=False)

    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_content_perf_topic", "topic_id"),
        Index("idx_content_perf_score", "performance_score"),
    )


# ---------------------------------------------------------------------------
# Video Scripts
# ---------------------------------------------------------------------------

class VideoScriptModel(Base):
    __tablename__ = "video_scripts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), index=True)
    topic_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    template_type: Mapped[str] = mapped_column(String(30), default="voiceover_broll", index=True)
    hook_text: Mapped[Optional[str]] = mapped_column(Text)
    body_json: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    cta_text: Mapped[Optional[str]] = mapped_column(Text)
    text_overlays: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    voiceover_script: Mapped[Optional[str]] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    reference_video_id: Mapped[Optional[str]] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Reference Videos (TikTok video inspiration / copy)
# ---------------------------------------------------------------------------

class ReferenceVideoModel(Base):
    __tablename__ = "reference_videos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tiktok_url: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    # oEmbed metadata
    title: Mapped[Optional[str]] = mapped_column(Text)
    author_name: Mapped[Optional[str]] = mapped_column(String(200))
    author_url: Mapped[Optional[str]] = mapped_column(Text)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text)
    caption: Mapped[Optional[str]] = mapped_column(Text)
    hashtags: Mapped[Optional[list]] = mapped_column(JSONB, default=[])

    # Engagement metrics
    views: Mapped[Optional[int]] = mapped_column(Integer)
    likes: Mapped[Optional[int]] = mapped_column(Integer)
    comments: Mapped[Optional[int]] = mapped_column(Integer)
    shares: Mapped[Optional[int]] = mapped_column(Integer)

    # LLM analysis
    hook_analysis: Mapped[Optional[str]] = mapped_column(Text)
    structure_analysis: Mapped[Optional[str]] = mapped_column(Text)
    style_notes: Mapped[Optional[str]] = mapped_column(Text)
    content_type: Mapped[Optional[str]] = mapped_column(String(30))
    estimated_duration: Mapped[Optional[int]] = mapped_column(Integer)

    # Generated script link
    generated_script_id: Mapped[Optional[str]] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Content Generation Queue
# ---------------------------------------------------------------------------

class ContentQueueModel(Base):
    __tablename__ = "content_queue"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    script_id: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[str] = mapped_column(String(64), index=True)
    generation_type: Mapped[str] = mapped_column(String(30), default="text_to_video")
    act_job_id: Mapped[Optional[str]] = mapped_column(String(128))
    act_generation_id: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Publishing
    publish_status: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    publish_platform: Mapped[Optional[str]] = mapped_column(String(30))
    publish_url: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    publish_error: Mapped[Optional[str]] = mapped_column(Text)
    caption: Mapped[Optional[str]] = mapped_column(Text)
    hashtags: Mapped[Optional[list]] = mapped_column(JSONB)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Email Rules
# ---------------------------------------------------------------------------

class EmailRuleModel(Base):
    __tablename__ = "email_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    stop_after_match: Mapped[bool] = mapped_column(Boolean, default=False)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False)
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    last_matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Prediction Markets
# ---------------------------------------------------------------------------

class PredictionMarketModel(Base):
    __tablename__ = "prediction_markets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="other", index=True)
    yes_price: Mapped[float] = mapped_column(Float, default=0.0)
    no_price: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    open_interest: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    close_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    result: Mapped[Optional[str]] = mapped_column(String(10))
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_pred_market_platform_status", "platform", "status"),
    )


class PredictionBettorModel(Base):
    __tablename__ = "prediction_bettors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    bettor_address: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(200))
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_volume: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_total: Mapped[float] = mapped_column(Float, default=0.0)
    avg_bet_size: Mapped[float] = mapped_column(Float, default=0.0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    categories: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    composite_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    tracked_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_pred_bettor_win_rate", "win_rate"),
        Index("idx_pred_bettor_pnl", "pnl_total"),
    )


class PredictionSnapshotModel(Base):
    __tablename__ = "prediction_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    market_id: Mapped[str] = mapped_column(String(64), ForeignKey("prediction_markets.id", ondelete="CASCADE"), index=True)
    yes_price: Mapped[float] = mapped_column(Float, default=0.0)
    no_price: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


# ---------------------------------------------------------------------------
# LLM Usage Tracking
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Orchestrator Conversations & Traces
# ---------------------------------------------------------------------------

class OrchestratorConversationModel(Base):
    """Every message exchanged through the orchestrator gateway."""
    __tablename__ = "orchestrator_conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(30), default="api")
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    route: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    route_method: Mapped[Optional[str]] = mapped_column(String(30))
    route_confidence: Mapped[Optional[int]] = mapped_column(Integer)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("idx_orch_conv_thread_created", "thread_id", "created_at"),
        Index("idx_orch_conv_channel", "channel"),
    )


class OrchestratorTraceModel(Base):
    """Per-node execution trace for an orchestrator invocation."""
    __tablename__ = "orchestrator_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), ForeignKey("orchestrator_conversations.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    node_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    node_order: Mapped[int] = mapped_column(Integer, nullable=False)
    input_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    output_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[Optional[float]] = mapped_column(Float)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_orch_trace_conv", "conversation_id"),
        Index("idx_orch_trace_node_time", "node_name", "started_at"),
    )


# ---------------------------------------------------------------------------
# LLM Usage Tracking
# ---------------------------------------------------------------------------

class LlmUsageModel(Base):
    """Track all LLM API calls across providers for cost/performance analysis."""
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_llm_usage_provider_date", "provider", "created_at"),
        Index("ix_llm_usage_task_provider", "task_type", "provider"),
    )


# ---------------------------------------------------------------------------
# Sprint 2: Gateway Agent Configs
# ---------------------------------------------------------------------------

class GatewayAgentConfigModel(Base):
    __tablename__ = "gateway_agent_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default="general", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    routes: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    channels: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=[])
    model_override: Mapped[Optional[str]] = mapped_column(String(100))
    system_prompt_override: Mapped[Optional[str]] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    proactive_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    proactive_triggers: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Sprint 3: Observability Spans
# ---------------------------------------------------------------------------

class ObservabilitySpanModel(Base):
    __tablename__ = "observability_spans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_span_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    span_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    input_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    output_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_obs_span_trace", "trace_id"),
        Index("idx_obs_span_type_time", "span_type", "started_at"),
    )


# ---------------------------------------------------------------------------
# Sprint 3: Approval Requests (Human-in-the-Loop)
# ---------------------------------------------------------------------------

class ApprovalRequestModel(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    context_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    initiated_by: Mapped[str] = mapped_column(String(50), default="system")
    route: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decision_by: Mapped[Optional[str]] = mapped_column(String(50))
    decision_reason: Mapped[Optional[str]] = mapped_column(Text)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    auto_action_on_expiry: Mapped[str] = mapped_column(String(20), default="reject")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("idx_approval_status_created", "status", "created_at"),
    )


# ---------------------------------------------------------------------------
# Sprint 4: Visual Workflow Definitions
# ---------------------------------------------------------------------------

class VisualWorkflowDefinitionModel(Base):
    __tablename__ = "visual_workflow_definitions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    nodes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=[])
    edges: Mapped[dict] = mapped_column(JSONB, nullable=False, default=[])
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    trigger_type: Mapped[Optional[str]] = mapped_column(String(30))
    trigger_config: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class VisualWorkflowExecutionModel(Base):
    __tablename__ = "visual_workflow_executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), ForeignKey("visual_workflow_definitions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    current_node_id: Mapped[Optional[str]] = mapped_column(String(64))
    execution_log: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    output: Mapped[Optional[dict]] = mapped_column(JSONB)
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Sprint 4: Outcome Tracking (Business KPIs)
# ---------------------------------------------------------------------------

class OutcomeTrackingModel(Base):
    __tablename__ = "outcome_tracking"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action_id: Mapped[Optional[str]] = mapped_column(String(64))
    kpi_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    kpi_value: Mapped[float] = mapped_column(Float, nullable=False)
    kpi_unit: Mapped[str] = mapped_column(String(30), default="count")
    extra_data: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("idx_outcome_source_type", "action_source", "kpi_type"),
    )


# ---------------------------------------------------------------------------
# Meeting Intelligence (migrated from DailyMemory)
# ---------------------------------------------------------------------------

class MeetingModel(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    calendar_event_id: Mapped[Optional[str]] = mapped_column(String(255))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    participants: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("idx_meetings_start_time", "start_time"),
    )


class MeetingRecordingModel(Base):
    __tablename__ = "meeting_recordings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(10), default="wav")
    sample_rate: Mapped[int] = mapped_column(Integer, default=16000)
    channels: Mapped[int] = mapped_column(Integer, default=1)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(10), default="mixed")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingTranscriptSegmentModel(Base):
    __tablename__ = "meeting_transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    speaker: Mapped[Optional[str]] = mapped_column(String(100))
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    embedding = mapped_column(Vector(768), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingSummaryModel(Base):
    __tablename__ = "meeting_summaries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    key_topics: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    action_items: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    decisions: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    generation_time_ms: Mapped[Optional[int]] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingSpeakerMappingModel(Base):
    __tablename__ = "meeting_speaker_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    speaker_label: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)


# ---------------------------------------------------------------------------
# Conversation Sessions (persistent)
# ---------------------------------------------------------------------------

class ConversationSessionModel(Base):
    """Persistent conversation sessions that survive restarts."""
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(Text)
    project_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(30), default="web")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_sessions_last_active", "last_active"),
    )


class ConversationMessageModel(Base):
    """Individual messages within a conversation session."""
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("conversation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # human, ai, system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Feedback & Preference Learning
# ---------------------------------------------------------------------------

class FeedbackModel(Base):
    """User feedback on AI responses for learning."""
    __tablename__ = "user_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # -1, 0, 1
    feedback_type: Mapped[str] = mapped_column(String(30), default="response_quality")  # response_quality, routing, tone, detail_level
    comment: Mapped[Optional[str]] = mapped_column(Text)
    context: Mapped[Optional[dict]] = mapped_column(JSONB, default={})  # route, model, response_length, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LearnedPreferenceModel(Base):
    """Preferences learned from user behavior and feedback."""
    __tablename__ = "learned_preferences"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # response_style, detail_level, tone, schedule
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence_count: Mapped[int] = mapped_column(Integer, default=1)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_pref_cat_key", "category", "key", unique=True),
    )


# ---------------------------------------------------------------------------
# Goal Tracking
# ---------------------------------------------------------------------------

class GoalModel(Base):
    """User goals with progress tracking."""
    __tablename__ = "user_goals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active, completed, paused, abandoned
    target_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    milestones: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class GoalCheckInModel(Base):
    """Weekly/daily check-ins on goal progress."""
    __tablename__ = "goal_checkins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(String(64), ForeignKey("user_goals.id", ondelete="CASCADE"), nullable=False, index=True)
    progress_delta: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[Optional[str]] = mapped_column(Text)
    blockers: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
