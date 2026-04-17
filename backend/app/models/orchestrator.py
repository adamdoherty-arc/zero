"""
Pydantic models for orchestrator conversations, traces, and analytics.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Conversation models
# ---------------------------------------------------------------------------

class ConversationListItem(BaseModel):
    id: str
    thread_id: str
    channel: str
    direction: str
    message: str
    route: Optional[str] = None
    route_method: Optional[str] = None
    route_confidence: Optional[int] = None
    latency_ms: Optional[float] = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
    created_at: datetime


class TraceNode(BaseModel):
    id: str
    conversation_id: str
    node_name: str
    node_order: int
    input_preview: Optional[str] = None
    output_preview: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    llm_calls: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    status: str = "running"
    error: Optional[str] = None


class ConversationDetail(BaseModel):
    conversation: ConversationListItem
    traces: List[TraceNode] = []


# ---------------------------------------------------------------------------
# Thread models
# ---------------------------------------------------------------------------

class ThreadSummary(BaseModel):
    thread_id: str
    channel: str
    message_count: int
    last_message: str
    last_route: Optional[str] = None
    last_active: datetime


# ---------------------------------------------------------------------------
# Route analytics
# ---------------------------------------------------------------------------

class RouteStatEntry(BaseModel):
    route: str
    invocation_count: int
    avg_latency_ms: float
    error_count: int
    error_rate: float
    total_tokens: int
    total_cost_usd: float


# ---------------------------------------------------------------------------
# Activity feed
# ---------------------------------------------------------------------------

class ActivityEvent(BaseModel):
    id: str
    event_type: str  # "invocation", "route", "error", "cron_run"
    timestamp: datetime
    summary: str
    route: Optional[str] = None
    channel: Optional[str] = None
    latency_ms: Optional[float] = None
    status: str = "ok"


# ---------------------------------------------------------------------------
# Request / pagination
# ---------------------------------------------------------------------------

class ConversationFilters(BaseModel):
    thread_id: Optional[str] = None
    channel: Optional[str] = None
    route: Optional[str] = None
    errors_only: bool = False
    limit: int = Field(default=50, le=200)
    offset: int = 0


class PaginatedConversations(BaseModel):
    items: List[ConversationListItem]
    total: int
    limit: int
    offset: int
