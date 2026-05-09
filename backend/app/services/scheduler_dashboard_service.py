"""Scheduler dashboard service — aggregated job execution data."""
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from functools import lru_cache

from sqlalchemy import select, desc
import structlog

from app.db.models import SchedulerAuditLogModel
from app.infrastructure.database import get_session

logger = structlog.get_logger()

from app.services.scheduler_service import get_job_category


class SchedulerDashboardService:
    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Aggregate scheduler audit log + APScheduler metadata."""
        from app.services.scheduler_service import get_scheduler_service

        status = await get_scheduler_service().get_status_detailed()
        jobs = status.get("jobs", [])
        total_success = sum(job.get("success_count", 0) for job in jobs)
        total_failures = sum(job.get("failure_count", 0) for job in jobs)
        total_runs = total_success + total_failures

        return {
            "jobs": sorted(jobs, key=lambda j: (j["category"], j["name"])),
            "total_jobs": status.get("total_jobs", len(jobs)),
            "total_runs_24h": total_runs,
            "success_rate_24h": round(total_success / total_runs * 100, 1) if total_runs > 0 else 100.0,
            "errors_today": total_failures,
            "enabled_jobs": status.get("enabled_jobs", 0),
            "disabled_jobs": status.get("disabled_jobs", 0),
        }

    async def get_job_timeline(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Sorted execution list for Gantt view."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with get_session() as session:
            stmt = (
                select(SchedulerAuditLogModel)
                .where(SchedulerAuditLogModel.started_at >= since)
                .order_by(SchedulerAuditLogModel.started_at)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "job_name": r.job_name,
                    "category": get_job_category(r.job_name),
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "duration_s": round(r.duration_seconds, 2) if r.duration_seconds else None,
                    "status": r.status,
                    "error": r.error,
                }
                for r in rows
            ]

    async def get_job_history(self, job_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Detailed history for a single job."""
        async with get_session() as session:
            stmt = (
                select(SchedulerAuditLogModel)
                .where(SchedulerAuditLogModel.job_name == job_name)
                .order_by(desc(SchedulerAuditLogModel.started_at))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": r.id,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "duration_s": round(r.duration_seconds, 2) if r.duration_seconds else None,
                    "status": r.status,
                    "error": r.error,
                }
                for r in rows
            ]


@lru_cache()
def get_scheduler_dashboard_service() -> SchedulerDashboardService:
    return SchedulerDashboardService()
