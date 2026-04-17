"""Observability service — hierarchical span tracing and analytics."""
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, Any, List, Optional
from uuid import uuid4

from sqlalchemy import select, func, desc, and_, case
import structlog

from app.db.models import ObservabilitySpanModel
from app.infrastructure.database import get_session

logger = structlog.get_logger()


def _ulid() -> str:
    ts = int(time.time() * 1000)
    return f"{ts:013x}-{uuid4().hex[:12]}"


class ObservabilityService:
    async def create_span(
        self, trace_id: str, name: str, span_type: str,
        parent_span_id: Optional[str] = None,
        input_data: Optional[dict] = None,
    ) -> str:
        span_id = _ulid()
        async with get_session() as session:
            row = ObservabilitySpanModel(
                id=span_id, trace_id=trace_id, parent_span_id=parent_span_id,
                name=name, span_type=span_type, input_data=input_data,
                status="running",
            )
            session.add(row)
        return span_id

    async def end_span(
        self, span_id: str, output_data: Optional[dict] = None,
        duration_ms: Optional[float] = None,
        tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0,
        status: str = "completed", quality_score: Optional[float] = None,
    ) -> None:
        async with get_session() as session:
            row = (await session.execute(
                select(ObservabilitySpanModel).where(ObservabilitySpanModel.id == span_id)
            )).scalar_one_or_none()
            if row:
                row.output_data = output_data
                row.duration_ms = duration_ms
                row.tokens_in = tokens_in
                row.tokens_out = tokens_out
                row.cost_usd = cost_usd
                row.status = status
                row.quality_score = quality_score
                row.completed_at = datetime.now(timezone.utc)

    async def get_trace_tree(self, trace_id: str) -> List[Dict[str, Any]]:
        async with get_session() as session:
            stmt = (
                select(ObservabilitySpanModel)
                .where(ObservabilitySpanModel.trace_id == trace_id)
                .order_by(ObservabilitySpanModel.started_at)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._span_to_dict(r) for r in rows]

    async def get_latency_percentiles(self, hours: int = 24) -> Dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with get_session() as session:
            stmt = (
                select(
                    ObservabilitySpanModel.span_type,
                    func.count().label("count"),
                    func.avg(ObservabilitySpanModel.duration_ms).label("avg_ms"),
                    func.min(ObservabilitySpanModel.duration_ms).label("min_ms"),
                    func.max(ObservabilitySpanModel.duration_ms).label("max_ms"),
                )
                .where(and_(
                    ObservabilitySpanModel.started_at >= since,
                    ObservabilitySpanModel.duration_ms.isnot(None),
                ))
                .group_by(ObservabilitySpanModel.span_type)
            )
            rows = (await session.execute(stmt)).all()
            return {
                "hours": hours,
                "by_type": [
                    {
                        "span_type": r.span_type,
                        "count": r.count,
                        "avg_ms": round(r.avg_ms or 0, 1),
                        "min_ms": round(r.min_ms or 0, 1),
                        "max_ms": round(r.max_ms or 0, 1),
                    }
                    for r in rows
                ],
            }

    async def get_cost_breakdown(self, hours: int = 24) -> Dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with get_session() as session:
            stmt = (
                select(
                    ObservabilitySpanModel.span_type,
                    func.sum(ObservabilitySpanModel.cost_usd).label("total_cost"),
                    func.sum(ObservabilitySpanModel.tokens_in).label("total_tokens_in"),
                    func.sum(ObservabilitySpanModel.tokens_out).label("total_tokens_out"),
                )
                .where(ObservabilitySpanModel.started_at >= since)
                .group_by(ObservabilitySpanModel.span_type)
            )
            rows = (await session.execute(stmt)).all()
            return {
                "hours": hours,
                "by_type": [
                    {
                        "span_type": r.span_type,
                        "total_cost_usd": round(r.total_cost or 0, 6),
                        "total_tokens_in": r.total_tokens_in or 0,
                        "total_tokens_out": r.total_tokens_out or 0,
                    }
                    for r in rows
                ],
            }

    async def get_performance_scorecards(self, hours: int = 24) -> List[Dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with get_session() as session:
            stmt = (
                select(
                    ObservabilitySpanModel.name,
                    func.count().label("count"),
                    func.avg(ObservabilitySpanModel.duration_ms).label("avg_ms"),
                    func.sum(case((ObservabilitySpanModel.status == "failed", 1), else_=0)).label("errors"),
                    func.avg(ObservabilitySpanModel.quality_score).label("avg_quality"),
                )
                .where(ObservabilitySpanModel.started_at >= since)
                .group_by(ObservabilitySpanModel.name)
                .order_by(desc("count"))
            )
            rows = (await session.execute(stmt)).all()
            return [
                {
                    "name": r.name,
                    "count": r.count,
                    "avg_latency_ms": round(r.avg_ms or 0, 1),
                    "error_count": r.errors or 0,
                    "error_rate": round((r.errors or 0) / r.count, 3) if r.count > 0 else 0,
                    "avg_quality": round(r.avg_quality or 0, 2) if r.avg_quality else None,
                }
                for r in rows
            ]

    def _span_to_dict(self, row) -> Dict[str, Any]:
        return {
            "id": row.id,
            "trace_id": row.trace_id,
            "parent_span_id": row.parent_span_id,
            "name": row.name,
            "span_type": row.span_type,
            "duration_ms": row.duration_ms,
            "tokens_in": row.tokens_in,
            "tokens_out": row.tokens_out,
            "cost_usd": row.cost_usd,
            "status": row.status,
            "quality_score": row.quality_score,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }


@lru_cache()
def get_observability_service() -> ObservabilityService:
    return ObservabilityService()
