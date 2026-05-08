"""Scheduler dashboard service — aggregated job execution data."""
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from functools import lru_cache

from sqlalchemy import select, func, desc, and_, case
import structlog

from app.db.models import SchedulerAuditLogModel
from app.infrastructure.database import get_session

logger = structlog.get_logger()

# Job categories for grouping
JOB_CATEGORIES = {
    "Briefing": ["morning_briefing", "midday_check", "evening_review"],
    "Email": ["gmail_check", "gmail_digest", "email_automation_check", "email_to_tasks"],
    "Research": ["research_daily", "research_weekly_deep_dive", "rules_recalibration"],
    "Ecosystem": ["ecosystem_quick_sync", "ecosystem_full_sync", "ecosystem_execution_monitor", "ecosystem_lifecycle_check"],
    "Autonomous": ["autonomous_daily_orchestration", "autonomous_continuous_monitor", "autonomous_enhancement_cycle"],
    "Enhancement": ["continuous_enhancement_engine", "daily_improvement_plan", "daily_improvement_execute", "daily_improvement_verify"],
    "Monitoring": ["health_aggregation", "qa_verification", "disk_space_monitor", "embedding_backfill", "alerting_check", "metrics_snapshot"],
    "Tasks": ["task_worker", "task_progress_check", "blocked_task_escalation", "smart_suggestions"],
    "Revenue": ["money_maker_cycle", "money_maker_weekly_report"],
    "Calendar": ["meeting_prep"],
    "Resources": ["gpu_refresh", "reminder_check", "notion_bidirectional_sync"],
    "TikTok": ["tiktok_continuous_research", "tiktok_niche_deep_dive", "tiktok_approval_reminder", "tiktok_auto_content_pipeline", "tiktok_content_generation_check", "tiktok_performance_sync", "tiktok_pipeline_health", "tiktok_weekly_report"],
    "Predictions": ["prediction_market_sync", "prediction_price_snapshot", "prediction_bettor_discovery", "prediction_research", "prediction_push_to_ada", "prediction_quality_check"],
    "LLM": ["llm_budget_reset"],
}


def _get_category(job_name: str) -> str:
    for cat, jobs in JOB_CATEGORIES.items():
        if job_name in jobs:
            return cat
    return "Other"


class SchedulerDashboardService:
    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Aggregate scheduler audit log + APScheduler metadata."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        # Get APScheduler job metadata using job.id (internal name) as key
        # Also build cron schedule from DAILY_SCHEDULE config
        from app.services.scheduler_service import get_scheduler_service, DAILY_SCHEDULE
        cron_lookup = {name: cfg.get("cron", "") for name, cfg in DAILY_SCHEDULE.items()}
        jobs_meta = {}
        try:
            svc = get_scheduler_service()
            for job in svc.scheduler.get_jobs():
                jobs_meta[job.id] = {
                    "id": job.id,
                    "name": job.name,
                    "schedule": cron_lookup.get(job.id, ""),
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "enabled": job.next_run_time is not None,
                }
        except Exception as e:
            logger.warning("scheduler_meta_fetch_failed", error=str(e))

        async with get_session() as session:
            # Aggregate per job for last 24h
            stmt = (
                select(
                    SchedulerAuditLogModel.job_name,
                    func.count().label("total_runs"),
                    func.sum(case((SchedulerAuditLogModel.status == "completed", 1), else_=0)).label("success_count"),
                    func.sum(case((SchedulerAuditLogModel.status == "failed", 1), else_=0)).label("failure_count"),
                    func.avg(SchedulerAuditLogModel.duration_seconds).label("avg_duration"),
                    func.max(SchedulerAuditLogModel.started_at).label("last_run"),
                )
                .where(SchedulerAuditLogModel.started_at >= since)
                .group_by(SchedulerAuditLogModel.job_name)
            )
            rows = (await session.execute(stmt)).all()

        stats_by_job = {}
        for row in rows:
            stats_by_job[row.job_name] = {
                "total_runs": row.total_runs or 0,
                "success_count": row.success_count or 0,
                "failure_count": row.failure_count or 0,
                "avg_duration_s": round(row.avg_duration or 0, 2),
                "last_run": row.last_run.isoformat() if row.last_run else None,
            }

        # Build job cards
        jobs = []
        for name, meta in jobs_meta.items():
            audit = stats_by_job.get(name, {})
            success = audit.get("success_count", 0)
            failures = audit.get("failure_count", 0)
            total = success + failures
            health = "green"
            if failures > 0 and total > 0:
                health = "red" if (failures / total) > 0.3 else "yellow"
            elif total == 0:
                health = "gray"

            jobs.append({
                "name": name,
                "category": _get_category(name),
                "schedule": meta.get("schedule", ""),
                "next_run": meta.get("next_run"),
                "enabled": meta.get("enabled", True),
                "health": health,
                **audit,
            })

        # Top stats
        total_success = sum(s.get("success_count", 0) for s in stats_by_job.values())
        total_failures = sum(s.get("failure_count", 0) for s in stats_by_job.values())
        total_runs = total_success + total_failures

        return {
            "jobs": sorted(jobs, key=lambda j: (j["category"], j["name"])),
            "total_jobs": len(jobs_meta),
            "total_runs_24h": total_runs,
            "success_rate_24h": round(total_success / total_runs * 100, 1) if total_runs > 0 else 100.0,
            "errors_today": total_failures,
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
                    "category": _get_category(r.job_name),
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
