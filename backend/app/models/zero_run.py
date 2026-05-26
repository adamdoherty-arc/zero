"""Zero Supervisor Run + Event + Critic-Review SQLAlchemy models (Migration 053).

Backs the /api/zero/run/* and /api/zero/critic/* surfaces. Mirrors Legion's
LegionRunDB / LegionRunEventDB / CriticReviewDB structure so the three
supervisor surfaces share an event vocabulary. Sprint state lives in Legion
at :8005 project_id=7 — these tables record the supervisor run + critic
review only.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.infrastructure.database import Base


class ZeroRunDB(Base):
    """One row per Zero supervisor invocation."""
    __tablename__ = "zero_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=False), nullable=False, unique=True, index=True)
    goal = Column(Text, nullable=False)
    focus = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, server_default="running", index=True)
    robot_state = Column(String(20), nullable=True)
    dnd = Column(Boolean, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    summary = Column(JSONB, nullable=True)
    metrics = Column(JSONB, nullable=True)
    supervisor_version = Column(String(40), nullable=True)


class ZeroRunEventDB(Base):
    """One row per supervisor gate event for Zero."""
    __tablename__ = "zero_run_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=False), nullable=False, index=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    phase = Column(String(40), nullable=True, index=True)
    event = Column(String(80), nullable=False, index=True)
    payload = Column(JSONB, nullable=True)
    metrics = Column(JSONB, nullable=True)
    links = Column(JSONB, nullable=True)
    robot_state = Column(String(20), nullable=True)
    dnd = Column(Boolean, nullable=True)
    partition = Column(String(20), nullable=True)
    approval_record_id = Column(String(120), nullable=True)
    vault_audit_id = Column(String(120), nullable=True)
    salience = Column(Float, nullable=True)
    delegation_target = Column(String(20), nullable=True)
    legion_sprint_id = Column(Integer, nullable=True)


class ZeroCriticReviewDB(Base):
    """One row per clean-context critic invocation for Zero work. The
    sprint_id refers to a row in Legion's sprints table (project_id=7),
    not a local one — Zero's sprint state lives in Legion."""
    __tablename__ = "zero_critic_reviews"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=False), nullable=True, index=True)
    legion_sprint_id = Column(Integer, nullable=False, index=True)
    round = Column(Integer, nullable=False, server_default="1")
    files_reviewed = Column(JSONB, nullable=False, server_default="[]")
    ac_extracted = Column(Text, nullable=True)
    critic_prompt = Column(Text, nullable=False)
    critique_text = Column(Text, nullable=True)
    scores = Column(JSONB, nullable=True)
    verdict = Column(String(20), nullable=True, index=True)
    reject_reasons = Column(JSONB, nullable=True)
    model_used = Column(String(80), nullable=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
