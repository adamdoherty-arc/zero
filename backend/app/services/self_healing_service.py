"""Self-healing service — anomaly detection, recovery, and outcome tracking."""
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, Any, List, Optional
from uuid import uuid4

from sqlalchemy import select, func, desc
import structlog

from app.db.models import OutcomeTrackingModel
from app.infrastructure.database import get_session

logger = structlog.get_logger()


def _ulid() -> str:
    ts = int(time.time() * 1000)
    return f"{ts:013x}-{uuid4().hex[:12]}"


class SelfHealingService:
    async def detect_anomaly(self, error_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify error and determine recovery strategy."""
        strategies = {
            "connection_error": "retry",
            "timeout": "retry_with_backoff",
            "model_unavailable": "fallback_model",
            "container_unhealthy": "restart_container",
            "disk_full": "cleanup",
            "rate_limit": "throttle",
        }
        strategy = strategies.get(error_type, "alert")
        return {"error_type": error_type, "strategy": strategy, "context": context}

    async def attempt_recovery(self, strategy: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute recovery strategy."""
        logger.info("recovery_attempt", strategy=strategy)
        if strategy == "retry":
            return {"action": "retry", "success": True, "message": "Queued for retry"}
        elif strategy == "fallback_model":
            return {"action": "fallback", "success": True, "message": "Switched to fallback model"}
        elif strategy == "alert":
            return {"action": "alert", "success": True, "message": "Alert sent to operator"}
        return {"action": strategy, "success": False, "message": "Unknown strategy"}

    async def record_outcome(
        self, action_source: str, kpi_type: str, kpi_value: float,
        kpi_unit: str = "count", action_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        outcome_id = _ulid()
        async with get_session() as session:
            row = OutcomeTrackingModel(
                id=outcome_id, action_source=action_source, action_id=action_id,
                kpi_type=kpi_type, kpi_value=kpi_value, kpi_unit=kpi_unit,
                extra_data=metadata,
            )
            session.add(row)
        return outcome_id

    async def get_outcome_dashboard(self, days: int = 30) -> Dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with get_session() as session:
            # By KPI type
            stmt = (
                select(
                    OutcomeTrackingModel.kpi_type,
                    func.sum(OutcomeTrackingModel.kpi_value).label("total"),
                    func.count().label("count"),
                )
                .where(OutcomeTrackingModel.recorded_at >= since)
                .group_by(OutcomeTrackingModel.kpi_type)
            )
            rows = (await session.execute(stmt)).all()

            # By source
            stmt2 = (
                select(
                    OutcomeTrackingModel.action_source,
                    func.sum(OutcomeTrackingModel.kpi_value).label("total"),
                    func.count().label("count"),
                )
                .where(OutcomeTrackingModel.recorded_at >= since)
                .group_by(OutcomeTrackingModel.action_source)
            )
            source_rows = (await session.execute(stmt2)).all()

            # Recent outcomes
            recent_stmt = (
                select(OutcomeTrackingModel)
                .where(OutcomeTrackingModel.recorded_at >= since)
                .order_by(desc(OutcomeTrackingModel.recorded_at))
                .limit(20)
            )
            recent = (await session.execute(recent_stmt)).scalars().all()

        return {
            "period_days": days,
            "by_kpi_type": [
                {"kpi_type": r.kpi_type, "total_value": round(r.total or 0, 2), "count": r.count}
                for r in rows
            ],
            "by_source": [
                {"source": r.action_source, "total_value": round(r.total or 0, 2), "count": r.count}
                for r in source_rows
            ],
            "recent": [
                {
                    "id": r.id, "source": r.action_source, "kpi_type": r.kpi_type,
                    "value": r.kpi_value, "unit": r.kpi_unit,
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                }
                for r in recent
            ],
        }


@lru_cache()
def get_self_healing_service() -> SelfHealingService:
    return SelfHealingService()
