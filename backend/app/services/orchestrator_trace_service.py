"""
Orchestrator Trace Service — records and queries conversation + trace data.

Every orchestrator invocation is persisted with:
- Inbound conversation record (user message)
- Per-node trace records (router, domain node, synthesizer)
- Outbound conversation record (agent response)
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import desc, func, select, and_, distinct, case
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.db.models import OrchestratorConversationModel, OrchestratorTraceModel
from app.infrastructure.database import get_session
from app.models.orchestrator import (
    ActivityEvent,
    ConversationDetail,
    ConversationListItem,
    PaginatedConversations,
    RouteStatEntry,
    ThreadSummary,
    TraceNode,
)

logger = structlog.get_logger()


def _ulid() -> str:
    """Generate a sortable unique ID (timestamp prefix + random)."""
    ts = int(time.time() * 1000)
    return f"{ts:013x}-{uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# In-memory event bus for SSE
# ---------------------------------------------------------------------------

_activity_queues: list[asyncio.Queue] = []


def _broadcast_event(event: dict) -> None:
    """Push an event to all connected SSE listeners."""
    for q in _activity_queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Drop if client is slow


def subscribe_activity() -> asyncio.Queue:
    """Subscribe to the activity stream. Returns a queue to read from."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _activity_queues.append(q)
    return q


def unsubscribe_activity(q: asyncio.Queue) -> None:
    """Unsubscribe from the activity stream."""
    try:
        _activity_queues.remove(q)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Record operations
# ---------------------------------------------------------------------------

async def record_conversation(
    thread_id: str,
    channel: str,
    message: str,
    direction: str,
    route: Optional[str] = None,
    route_method: Optional[str] = None,
    route_confidence: Optional[int] = None,
    latency_ms: Optional[float] = None,
    tokens_used: int = 0,
    cost_usd: float = 0.0,
    error: Optional[str] = None,
) -> str:
    """Record a single conversation message (inbound or outbound). Returns conversation ID."""
    conv_id = _ulid()
    async with get_session() as session:
        row = OrchestratorConversationModel(
            id=conv_id,
            thread_id=thread_id,
            channel=channel,
            direction=direction,
            message=message[:10000],  # Truncate very long messages
            route=route,
            route_method=route_method,
            route_confidence=route_confidence,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            error=error,
        )
        session.add(row)

    # Broadcast
    _broadcast_event({
        "id": conv_id,
        "event_type": "invocation" if direction == "inbound" else "response",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": f"[{channel}] {message[:120]}",
        "route": route,
        "channel": channel,
        "latency_ms": latency_ms,
        "status": "error" if error else "ok",
    })

    return conv_id


async def update_conversation_route(
    conversation_id: str,
    route: Optional[str] = None,
    route_method: Optional[str] = None,
    route_confidence: Optional[int] = None,
    latency_ms: Optional[float] = None,
    tokens_used: int = 0,
    cost_usd: float = 0.0,
    error: Optional[str] = None,
) -> None:
    """Update an inbound conversation record with route info after graph execution."""
    async with get_session() as session:
        stmt = select(OrchestratorConversationModel).where(
            OrchestratorConversationModel.id == conversation_id
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            if route is not None:
                row.route = route
            if route_method is not None:
                row.route_method = route_method
            if route_confidence is not None:
                row.route_confidence = route_confidence
            if latency_ms is not None:
                row.latency_ms = latency_ms
            if tokens_used:
                row.tokens_used = tokens_used
            if cost_usd:
                row.cost_usd = cost_usd
            if error is not None:
                row.error = error


async def record_trace_node(
    conversation_id: str,
    thread_id: str,
    node_name: str,
    node_order: int,
    input_data: Optional[dict] = None,
) -> str:
    """Record the start of a node execution. Returns trace ID."""
    trace_id = _ulid()
    async with get_session() as session:
        row = OrchestratorTraceModel(
            id=trace_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            node_name=node_name,
            node_order=node_order,
            input_data=_safe_json(input_data),
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        session.add(row)
    return trace_id


async def complete_trace_node(
    trace_id: str,
    output_data: Optional[dict] = None,
    duration_ms: Optional[float] = None,
    llm_calls: int = 0,
    tokens_used: int = 0,
    cost_usd: float = 0.0,
    status: str = "completed",
    error: Optional[str] = None,
) -> None:
    """Record the completion of a node execution."""
    async with get_session() as session:
        stmt = select(OrchestratorTraceModel).where(OrchestratorTraceModel.id == trace_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.output_data = _safe_json(output_data)
            row.completed_at = datetime.now(timezone.utc)
            row.duration_ms = duration_ms
            row.llm_calls = llm_calls
            row.tokens_used = tokens_used
            row.cost_usd = cost_usd
            row.status = status
            row.error = error

    # Broadcast trace completion
    _broadcast_event({
        "id": trace_id,
        "event_type": "trace",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": f"Node '{node_name}' {status}" if (node_name := "") == "" else f"Trace {status}",
        "status": status,
        "latency_ms": duration_ms,
    })


# ---------------------------------------------------------------------------
# Query operations
# ---------------------------------------------------------------------------

async def list_conversations(
    thread_id: Optional[str] = None,
    channel: Optional[str] = None,
    route: Optional[str] = None,
    errors_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedConversations:
    """List conversations with optional filters, newest first."""
    async with get_session() as session:
        conditions = []
        if thread_id:
            conditions.append(OrchestratorConversationModel.thread_id == thread_id)
        if channel:
            conditions.append(OrchestratorConversationModel.channel == channel)
        if route:
            conditions.append(OrchestratorConversationModel.route == route)
        if errors_only:
            conditions.append(OrchestratorConversationModel.error.isnot(None))

        # Only show inbound (user messages) in main list to avoid duplicates
        conditions.append(OrchestratorConversationModel.direction == "inbound")

        where = and_(*conditions) if conditions else True

        # Count
        count_stmt = select(func.count()).select_from(OrchestratorConversationModel).where(where)
        total = (await session.execute(count_stmt)).scalar() or 0

        # Items
        stmt = (
            select(OrchestratorConversationModel)
            .where(where)
            .order_by(desc(OrchestratorConversationModel.created_at))
            .offset(offset)
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()

        items = [_conv_to_model(r) for r in rows]
        return PaginatedConversations(items=items, total=total, limit=limit, offset=offset)


async def get_conversation_with_traces(conversation_id: str) -> Optional[ConversationDetail]:
    """Get a single conversation with its full execution trace."""
    async with get_session() as session:
        # Conversation
        stmt = select(OrchestratorConversationModel).where(
            OrchestratorConversationModel.id == conversation_id
        )
        conv = (await session.execute(stmt)).scalar_one_or_none()
        if not conv:
            return None

        # Traces
        trace_stmt = (
            select(OrchestratorTraceModel)
            .where(OrchestratorTraceModel.conversation_id == conversation_id)
            .order_by(OrchestratorTraceModel.node_order)
        )
        traces = (await session.execute(trace_stmt)).scalars().all()

        # Also get the outbound response for this thread at roughly the same time
        return ConversationDetail(
            conversation=_conv_to_model(conv),
            traces=[_trace_to_model(t) for t in traces],
        )


async def list_threads(limit: int = 20, offset: int = 0) -> List[ThreadSummary]:
    """List unique threads with summary info."""
    async with get_session() as session:
        # Subquery for latest message per thread
        subq = (
            select(
                OrchestratorConversationModel.thread_id,
                func.count().label("message_count"),
                func.max(OrchestratorConversationModel.created_at).label("last_active"),
            )
            .group_by(OrchestratorConversationModel.thread_id)
            .order_by(desc("last_active"))
            .offset(offset)
            .limit(limit)
            .subquery()
        )

        # Join back to get the last message details
        stmt = (
            select(
                OrchestratorConversationModel,
                subq.c.message_count,
            )
            .join(subq, and_(
                OrchestratorConversationModel.thread_id == subq.c.thread_id,
                OrchestratorConversationModel.created_at == subq.c.last_active,
            ))
            .order_by(desc(subq.c.last_active))
        )

        rows = (await session.execute(stmt)).all()

        results = []
        for conv, msg_count in rows:
            results.append(ThreadSummary(
                thread_id=conv.thread_id,
                channel=conv.channel,
                message_count=msg_count,
                last_message=conv.message[:200],
                last_route=conv.route,
                last_active=conv.created_at,
            ))
        return results


async def get_thread_history(thread_id: str, limit: int = 100) -> List[ConversationListItem]:
    """Get all messages in a thread."""
    async with get_session() as session:
        stmt = (
            select(OrchestratorConversationModel)
            .where(OrchestratorConversationModel.thread_id == thread_id)
            .order_by(OrchestratorConversationModel.created_at)
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_conv_to_model(r) for r in rows]


async def get_route_stats(hours: int = 24) -> List[RouteStatEntry]:
    """Get aggregated route statistics for the given time period."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with get_session() as session:
        stmt = (
            select(
                OrchestratorConversationModel.route,
                func.count().label("invocation_count"),
                func.avg(OrchestratorConversationModel.latency_ms).label("avg_latency_ms"),
                func.sum(case(
                    (OrchestratorConversationModel.error.isnot(None), 1),
                    else_=0,
                )).label("error_count"),
                func.sum(OrchestratorConversationModel.tokens_used).label("total_tokens"),
                func.sum(OrchestratorConversationModel.cost_usd).label("total_cost_usd"),
            )
            .where(and_(
                OrchestratorConversationModel.created_at >= since,
                OrchestratorConversationModel.direction == "inbound",
                OrchestratorConversationModel.route.isnot(None),
            ))
            .group_by(OrchestratorConversationModel.route)
            .order_by(desc("invocation_count"))
        )

        rows = (await session.execute(stmt)).all()

        results = []
        for row in rows:
            count = row.invocation_count or 0
            errors = row.error_count or 0
            results.append(RouteStatEntry(
                route=row.route or "unknown",
                invocation_count=count,
                avg_latency_ms=round(row.avg_latency_ms or 0, 1),
                error_count=errors,
                error_rate=round(errors / count, 3) if count > 0 else 0.0,
                total_tokens=row.total_tokens or 0,
                total_cost_usd=round(row.total_cost_usd or 0, 6),
            ))
        return results


async def get_activity_feed(limit: int = 50) -> List[ActivityEvent]:
    """Get recent activity events for the dashboard."""
    async with get_session() as session:
        stmt = (
            select(OrchestratorConversationModel)
            .where(OrchestratorConversationModel.direction == "inbound")
            .order_by(desc(OrchestratorConversationModel.created_at))
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()

        events = []
        for r in rows:
            events.append(ActivityEvent(
                id=r.id,
                event_type="error" if r.error else "invocation",
                timestamp=r.created_at,
                summary=f"[{r.channel}] {r.message[:120]}",
                route=r.route,
                channel=r.channel,
                latency_ms=r.latency_ms,
                status="error" if r.error else "ok",
            ))
        return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json(data: Optional[dict], max_size: int = 50000) -> Optional[dict]:
    """Truncate JSON data if it's too large to store."""
    if data is None:
        return None
    try:
        serialized = json.dumps(data, default=str)
        if len(serialized) > max_size:
            return {"_truncated": True, "preview": serialized[:2000]}
        return data
    except (TypeError, ValueError):
        return {"_error": "not serializable", "repr": str(data)[:2000]}


def _conv_to_model(row: OrchestratorConversationModel) -> ConversationListItem:
    return ConversationListItem(
        id=row.id,
        thread_id=row.thread_id,
        channel=row.channel,
        direction=row.direction,
        message=row.message[:500],
        route=row.route,
        route_method=row.route_method,
        route_confidence=row.route_confidence,
        latency_ms=row.latency_ms,
        tokens_used=row.tokens_used,
        cost_usd=row.cost_usd,
        error=row.error,
        created_at=row.created_at,
    )


def _trace_to_model(row: OrchestratorTraceModel) -> TraceNode:
    input_preview = None
    output_preview = None
    if row.input_data:
        try:
            input_preview = json.dumps(row.input_data, default=str)[:500]
        except Exception:
            input_preview = str(row.input_data)[:500]
    if row.output_data:
        try:
            output_preview = json.dumps(row.output_data, default=str)[:500]
        except Exception:
            output_preview = str(row.output_data)[:500]

    return TraceNode(
        id=row.id,
        conversation_id=row.conversation_id,
        node_name=row.node_name,
        node_order=row.node_order,
        input_preview=input_preview,
        output_preview=output_preview,
        started_at=row.started_at,
        completed_at=row.completed_at,
        duration_ms=row.duration_ms,
        llm_calls=row.llm_calls,
        tokens_used=row.tokens_used,
        cost_usd=row.cost_usd,
        status=row.status,
        error=row.error,
    )


@lru_cache()
def get_trace_service():
    """Singleton accessor (for consistency with other services, returns module)."""
    import app.services.orchestrator_trace_service as svc
    return svc
