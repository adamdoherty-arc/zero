"""
Daily Automation Scheduler Service for ZERO.

Handles scheduled automation tasks including:
- Morning briefing generation and delivery
- Midday health checks
- Evening review and sprint updates
- Enhancement scans
- Notification routing
- Workspace backups

Uses APScheduler for cron-based scheduling.
All job executions are logged to PostgreSQL (scheduler_audit_log) for observability.
"""
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from functools import lru_cache
import structlog

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, func as sa_func

from app.infrastructure.database import get_session
from app.db.models import SchedulerAuditLogModel

logger = structlog.get_logger(__name__)


# ============================================
# SCHEDULE CONFIGURATION
# ============================================

DAILY_SCHEDULE = {
    "morning_briefing": {
        "cron": "0 7 * * *",  # 7:00 AM daily
        "description": "Generate and send morning briefing",
        "enabled": True
    },
    "midday_check": {
        "cron": "0 12 * * *",  # 12:00 PM daily
        "description": "Check blocked tasks and sprint health",
        "enabled": True
    },
    "evening_review": {
        "cron": "0 18 * * *",  # 6:00 PM daily
        "description": "Generate evening progress summary",
        "enabled": True
    },
    "enhancement_scan": {
        "cron": "0 9 * * *",  # 9:00 AM daily (superseded by autonomous_enhancement_cycle)
        "description": "Scan projects for enhancement signals",
        "enabled": False
    },
    "health_aggregation": {
        "cron": "0 */4 * * *",  # Every 4 hours
        "description": "Aggregate project health from Legion",
        "enabled": True
    },
    "money_maker_cycle": {
        "cron": "0 8 * * *",  # 8:00 AM daily
        "description": "Generate and research money-making ideas",
        "enabled": True
    },
    "money_maker_weekly_report": {
        "cron": "0 9 * * 0",  # Sunday 9:00 AM
        "description": "Weekly money maker summary to Discord",
        "enabled": True
    },
    "gmail_check": {
        "cron": "*/5 * * * *",  # Every 5 minutes
        "description": "Incremental Gmail sync and alert check",
        "enabled": True
    },
    "gmail_digest": {
        "cron": "5 7 * * *",  # 7:05 AM daily (after briefing)
        "description": "Generate and send daily email digest",
        "enabled": True
    },
    "email_automation_check": {
        "cron": "*/5 * * * *",  # Every 5 minutes
        "description": "Process new emails through automation workflow",
        "enabled": True
    },
    "legion_enhancement_sync": {
        "cron": "30 9 * * *",  # 9:30 AM daily (superseded by autonomous_enhancement_cycle)
        "description": "Auto-create Legion tasks from enhancement signals",
        "enabled": False
    },
    "email_to_tasks": {
        "cron": "0 10 * * *",  # 10:00 AM daily
        "description": "Convert email action items to Legion tasks",
        "enabled": True
    },
    "meeting_prep": {
        "cron": "0 7 * * *",  # 7:00 AM daily (with briefing)
        "description": "Create prep tasks for upcoming meetings",
        "enabled": True
    },
    "blocked_task_escalation": {
        "cron": "0 14 * * *",  # 2:00 PM daily
        "description": "Escalate blocked Legion tasks via Discord",
        "enabled": True
    },
    "smart_suggestions": {
        "cron": "55 6 * * *",  # 6:55 AM daily (before briefing)
        "description": "Generate cross-project smart task suggestions",
        "enabled": True
    },
    "backup_hourly": {
        "cron": "0 * * * *",  # Every hour
        "description": "Hourly workspace backup",
        "enabled": True
    },
    "backup_daily": {
        "cron": "0 2 * * *",  # 2:00 AM daily
        "description": "Daily workspace backup",
        "enabled": True
    },
    "backup_weekly": {
        "cron": "0 3 * * 0",  # Sunday 3:00 AM
        "description": "Weekly workspace backup",
        "enabled": True
    },
    "research_daily": {
        "cron": "0 11 * * *",  # 11:00 AM daily
        "description": "Daily research cycle - scan topics and discover new findings",
        "enabled": True
    },
    "research_weekly_deep_dive": {
        "cron": "0 10 * * 6",  # Saturday 10:00 AM
        "description": "Weekly deep dive research with expanded search and trend report",
        "enabled": True
    },
    # Ecosystem sync (S70)
    "ecosystem_quick_sync": {
        "cron": "*/15 * * * *",  # Every 15 minutes
        "description": "Quick ecosystem sync from Legion (lightweight)",
        "enabled": True
    },
    "ecosystem_full_sync": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "Full ecosystem sync with all project data",
        "enabled": True
    },
    "ecosystem_execution_monitor": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Monitor Legion autonomous execution status",
        "enabled": True
    },
    "ecosystem_lifecycle_check": {
        "cron": "55 6 * * *",  # 6:55 AM daily (before briefing)
        "description": "Detect sprint lifecycle events across all projects",
        "enabled": True
    },
    # Autonomous orchestration (S70 Phase 2)
    "autonomous_daily_orchestration": {
        "cron": "0 8 * * *",  # 8:00 AM daily
        "description": "Full autopilot: sync ecosystem, trigger swarm execution, plan sprints",
        "enabled": True
    },
    "autonomous_continuous_monitor": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Monitor for failed/stuck executions across all projects",
        "enabled": True
    },
    "autonomous_enhancement_cycle": {
        "cron": "0 9 * * *",  # 9:00 AM daily
        "description": "Multi-project enhancement scan + auto-create Legion tasks",
        "enabled": True
    },
    # QA Verification
    "qa_verification": {
        "cron": "0 6 * * *",  # 6:00 AM daily
        "description": "Full QA verification of all systems (Docker, build, types, API, logs)",
        "enabled": True
    },
    # Daily Self-Improvement Cycle
    "daily_improvement_plan": {
        "cron": "15 9 * * *",  # 9:15 AM daily (after enhancement scan)
        "description": "Select top 5 improvements for today's cycle",
        "enabled": True
    },
    "daily_improvement_execute": {
        "cron": "30 9 * * *",  # 9:30 AM daily (after planning)
        "description": "Execute today's improvement plan (auto-fix + task creation)",
        "enabled": True
    },
    "daily_improvement_verify": {
        "cron": "0 10 * * *",  # 10:00 AM daily (after execution)
        "description": "Verify improvements were successful, update metrics",
        "enabled": True
    },
    # Autonomous Task Worker
    "task_worker": {
        "cron": "*/2 * * * *",  # Every 2 minutes
        "description": "Pick up queued autonomous tasks and execute them",
        "enabled": True
    },
    "task_progress_check": {
        "cron": "*/5 * * * *",  # Every 5 minutes
        "description": "Report progress on currently executing autonomous task",
        "enabled": True
    },
    # Continuous Enhancement Engine
    "continuous_enhancement_engine": {
        "cron": "*/10 * * * *",  # Every 10 minutes
        "description": "Continuous enhancement engine - scan, analyze, queue improvements for Zero and Legion",
        "enabled": True
    },
    # GPU/Ollama Resource Manager
    "gpu_refresh": {
        "cron": "* * * * *",  # Every minute
        "description": "Refresh GPU/Ollama resource status (loaded models, VRAM)",
        "enabled": True
    },
    # Reminder Check
    "reminder_check": {
        "cron": "*/5 * * * *",  # Every 5 minutes
        "description": "Check for due reminders and send notifications",
        "enabled": True
    },
    # Research Rules Engine
    "rules_recalibration": {
        "cron": "0 4 * * 0",  # Sunday 4:00 AM
        "description": "Weekly recalibration of research rules based on effectiveness",
        "enabled": True
    },
    # Disk Space Monitoring
    "disk_space_monitor": {
        "cron": "0 */4 * * *",  # Every 4 hours
        "description": "Monitor disk space usage and alert when >85% full",
        "enabled": True
    },
    # Embedding Backfill
    "embedding_backfill": {
        "cron": "30 3 * * *",  # 3:30 AM daily
        "description": "Backfill embeddings for notes/facts missing vectors",
        "enabled": True
    },
    # Alerting
    "alerting_check": {
        "cron": "*/5 * * * *",  # Every 5 minutes
        "description": "Evaluate alert rules and send notifications",
        "enabled": True
    },
    # Metrics Snapshot
    "metrics_snapshot": {
        "cron": "0 * * * *",  # Every hour
        "description": "Persist hourly metrics snapshot to PostgreSQL",
        "enabled": True
    },
    # Backup Restore Test
    "backup_restore_test": {
        "cron": "0 4 * * 0",  # Sunday 4:00 AM
        "description": "Weekly backup extraction + validation test",
        "enabled": True
    },
    # Notion Bidirectional Sync
    "notion_bidirectional_sync": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Bidirectional sync with Notion",
        "enabled": True
    },
    # TikTok Shop Research Agent
    "tiktok_shop_research": {
        "cron": "0 10 * * *",  # 10:00 AM daily
        "description": "TikTok Shop product discovery and opportunity scoring",
        "enabled": True
    },
    "tiktok_shop_deep_research": {
        "cron": "0 11 * * 6",  # Saturday 11:00 AM
        "description": "Deep research on top TikTok Shop products",
        "enabled": True
    },
    # TikTok 24/7 Pipeline Automation
    "tiktok_continuous_research": {
        "cron": "0 */4 * * *",  # Every 4 hours
        "description": "Continuous TikTok product discovery pipeline (4x daily)",
        "enabled": True
    },
    "tiktok_niche_deep_dive": {
        "cron": "0 14 * * *",  # 2:00 PM daily
        "description": "Deep dive research into top performing niches",
        "enabled": True
    },
    "tiktok_approval_reminder": {
        "cron": "0 9,17 * * *",  # 9 AM and 5 PM daily
        "description": "Discord reminder for products pending approval",
        "enabled": True
    },
    "tiktok_auto_content_pipeline": {
        "cron": "0 */6 * * *",  # Every 6 hours
        "description": "Auto-generate video scripts for approved products",
        "enabled": True
    },
    "tiktok_content_generation_check": {
        "cron": "*/15 * * * *",  # Every 15 minutes
        "description": "Poll AIContentTools for completed video generation jobs",
        "enabled": True
    },
    "tiktok_performance_sync": {
        "cron": "0 */3 * * *",  # Every 3 hours
        "description": "Sync TikTok performance metrics and run improvement cycle",
        "enabled": True
    },
    "tiktok_pipeline_health": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "TikTok pipeline health check, alert on failures, retry stuck jobs",
        "enabled": True
    },
    "tiktok_weekly_report": {
        "cron": "0 10 * * 0",  # Sunday 10:00 AM
        "description": "Weekly TikTok Shop performance report to Discord",
        "enabled": True
    },
    # Content Agent
    "content_performance_sync": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "Sync content performance metrics from AIContentTools",
        "enabled": True
    },
    "content_improvement_cycle": {
        "cron": "30 9 * * *",  # 9:30 AM daily
        "description": "Content rule improvement from performance feedback",
        "enabled": True
    },
    "content_trend_research": {
        "cron": "0 13 * * *",  # 1:00 PM daily
        "description": "Research trending content for active topics",
        "enabled": True
    },
    # Gateway Auto-Update
    "gateway_update_check": {
        "cron": "0 4 * * *",  # 4:00 AM daily
        "description": "Check for OpenClaw gateway updates via GitHub API",
        "enabled": True
    },
    # Prediction Market Intelligence
    "prediction_market_sync": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Sync Kalshi + Polymarket markets",
        "enabled": True
    },
    "prediction_price_snapshot": {
        "cron": "*/15 * * * *",  # Every 15 minutes
        "description": "Capture prediction market price snapshots",
        "enabled": True
    },
    "prediction_bettor_discovery": {
        "cron": "0 10 * * *",  # 10:00 AM daily
        "description": "Discover and update top prediction market bettors",
        "enabled": True
    },
    "prediction_research": {
        "cron": "30 11 * * *",  # 11:30 AM daily
        "description": "SearXNG prediction market research",
        "enabled": True
    },
    "prediction_push_to_ada": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Push prediction market data to ADA",
        "enabled": True
    },
    "prediction_quality_check": {
        "cron": "0 9 * * *",  # 9:00 AM daily
        "description": "Prediction market quality + Legion progress report + Discord alert",
        "enabled": True
    },
    # LLM Budget Reset
    "llm_budget_reset": {
        "cron": "0 0 * * *",  # Midnight daily
        "description": "Reset daily LLM spending counter for budget enforcement",
        "enabled": True
    },
}


# ============================================
# SCHEDULER SERVICE
# ============================================

class SchedulerService:
    """
    Manages scheduled automation tasks for Zero.

    Uses APScheduler for reliable cron-based execution.
    All job executions are logged to PostgreSQL (scheduler_audit_log table).
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._jobs: Dict[str, str] = {}  # job_name -> job_id

    async def start(self):
        """Start the scheduler with all configured jobs."""
        if self._running:
            logger.warning("scheduler_already_running")
            return

        logger.info("scheduler_starting")

        # Register all jobs
        for job_name, config in DAILY_SCHEDULE.items():
            if config.get("enabled", True):
                await self._register_job(job_name, config)

        self.scheduler.start()
        self._running = True

        logger.info(
            "scheduler_started",
            jobs=list(self._jobs.keys())
        )

    async def stop(self):
        """Stop the scheduler."""
        if not self._running:
            return

        logger.info("scheduler_stopping")
        self.scheduler.shutdown(wait=False)
        self._running = False
        logger.info("scheduler_stopped")

    async def _register_job(self, job_name: str, config: Dict[str, Any]):
        """Register a scheduled job, wrapped with audit logging."""
        handler = self._get_handler(job_name)
        if not handler:
            logger.warning("no_handler_for_job", job=job_name)
            return

        # Wrap handler with audit logging
        async def audited_handler(_name=job_name, _handler=handler):
            await self._run_with_audit(_name, _handler)

        trigger = CronTrigger.from_crontab(config["cron"])

        job = self.scheduler.add_job(
            audited_handler,
            trigger=trigger,
            id=job_name,
            name=config.get("description", job_name),
            replace_existing=True
        )

        self._jobs[job_name] = job.id
        logger.info(
            "job_registered",
            job=job_name,
            cron=config["cron"]
        )

    async def _run_with_audit(self, job_name: str, handler: Callable):
        """Execute a handler and record the result in the audit log."""
        started = datetime.utcnow()
        t0 = time.monotonic()
        status = "completed"
        error_msg = None

        try:
            await handler()
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            logger.error("job_failed", job=job_name, error=error_msg)
        finally:
            duration = round(time.monotonic() - t0, 2)
            completed = datetime.utcnow()
            await self._append_audit(
                job_name=job_name,
                started_at=started,
                completed_at=completed,
                status=status,
                duration_seconds=duration,
                error=error_msg,
            )
            # Record metrics
            try:
                from app.services.metrics_service import get_metrics_service
                m = get_metrics_service()
                m.record("job_duration", duration, {"job": job_name})
                m.increment(f"job_{status}")
                m.increment(f"job_{job_name}_{status}")
            except Exception:
                pass
            logger.info("job_audit", job=job_name, status=status, duration=duration)

    async def _append_audit(
        self,
        job_name: str,
        started_at: datetime,
        completed_at: datetime,
        status: str,
        duration_seconds: float,
        error: Optional[str] = None,
    ):
        """Persist an execution record to the scheduler_audit_log table."""
        try:
            async with get_session() as session:
                session.add(SchedulerAuditLogModel(
                    job_name=job_name,
                    started_at=started_at,
                    completed_at=completed_at,
                    status=status,
                    duration_seconds=duration_seconds,
                    error=error,
                ))
        except Exception as e:
            logger.error("audit_log_write_failed", error=str(e))

    async def get_audit_log(self, limit: int = 50) -> Dict[str, Any]:
        """Return recent audit log entries from PostgreSQL."""
        try:
            async with get_session() as session:
                # Get total count
                count_result = await session.execute(
                    select(sa_func.count()).select_from(SchedulerAuditLogModel)
                )
                total = count_result.scalar() or 0

                # Get recent entries ordered by created_at DESC
                result = await session.execute(
                    select(SchedulerAuditLogModel)
                    .order_by(SchedulerAuditLogModel.created_at.desc())
                    .limit(limit)
                )
                rows = result.scalars().all()

                executions = [
                    {
                        "job_name": row.job_name,
                        "started_at": row.started_at.isoformat() if row.started_at else None,
                        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                        "status": row.status,
                        "duration_seconds": row.duration_seconds,
                        "error": row.error,
                    }
                    for row in reversed(rows)  # Return in chronological order
                ]

                return {"executions": executions, "total": total}
        except Exception as e:
            logger.error("audit_log_read_failed", error=str(e))
            return {"executions": [], "total": 0}

    def _get_handler(self, job_name: str) -> Optional[Callable]:
        """Get the handler function for a job."""
        handlers = {
            "morning_briefing": self._run_morning_briefing,
            "midday_check": self._run_midday_check,
            "evening_review": self._run_evening_review,
            "enhancement_scan": self._run_enhancement_scan,
            "health_aggregation": self._run_health_aggregation,
            "money_maker_cycle": self._run_money_maker_cycle,
            "money_maker_weekly_report": self._run_money_maker_weekly_report,
            "gmail_check": self._run_gmail_check,
            "gmail_digest": self._run_gmail_digest,
            "email_automation_check": self._run_email_automation_check,
            "legion_enhancement_sync": self._run_legion_enhancement_sync,
            "email_to_tasks": self._run_email_to_tasks,
            "meeting_prep": self._run_meeting_prep,
            "blocked_task_escalation": self._run_blocked_task_escalation,
            "smart_suggestions": self._run_smart_suggestions,
            "backup_hourly": self._run_backup_hourly,
            "backup_daily": self._run_backup_daily,
            "backup_weekly": self._run_backup_weekly,
            "research_daily": self._run_research_daily,
            "research_weekly_deep_dive": self._run_research_weekly_deep_dive,
            # Ecosystem (S70)
            "ecosystem_quick_sync": self._run_ecosystem_quick_sync,
            "ecosystem_full_sync": self._run_ecosystem_full_sync,
            "ecosystem_execution_monitor": self._run_ecosystem_execution_monitor,
            "ecosystem_lifecycle_check": self._run_ecosystem_lifecycle_check,
            # Autonomous orchestration (S70 Phase 2)
            "autonomous_daily_orchestration": self._run_autonomous_daily_orchestration,
            "autonomous_continuous_monitor": self._run_autonomous_continuous_monitor,
            "autonomous_enhancement_cycle": self._run_autonomous_enhancement_cycle,
            # QA Verification
            "qa_verification": self._run_qa_verification,
            # Daily Self-Improvement
            "daily_improvement_plan": self._run_daily_improvement_plan,
            "daily_improvement_execute": self._run_daily_improvement_execute,
            "daily_improvement_verify": self._run_daily_improvement_verify,
            # Autonomous Task Worker
            "task_worker": self._run_task_worker,
            "task_progress_check": self._run_task_progress_check,
            # Continuous Enhancement Engine
            "continuous_enhancement_engine": self._run_continuous_enhancement_engine,
            # GPU/Ollama Resource Manager
            "gpu_refresh": self._run_gpu_refresh,
            # Reminder Check
            "reminder_check": self._run_reminder_check,
            # Research Rules Engine
            "rules_recalibration": self._run_rules_recalibration,
            # Disk Space Monitoring
            "disk_space_monitor": self._run_disk_space_monitor,
            # Embedding Backfill
            "embedding_backfill": self._run_embedding_backfill,
            # Alerting
            "alerting_check": self._run_alerting_check,
            # Metrics Snapshot
            "metrics_snapshot": self._run_metrics_snapshot,
            # Backup Restore Test
            "backup_restore_test": self._run_backup_restore_test,
            # Notion Bidirectional Sync
            "notion_bidirectional_sync": self._run_notion_bidirectional_sync,
            # TikTok Shop Research Agent
            "tiktok_shop_research": self._run_tiktok_shop_research,
            "tiktok_shop_deep_research": self._run_tiktok_shop_deep_research,
            # TikTok 24/7 Pipeline Automation
            "tiktok_continuous_research": self._run_tiktok_continuous_research,
            "tiktok_niche_deep_dive": self._run_tiktok_niche_deep_dive,
            "tiktok_approval_reminder": self._run_tiktok_approval_reminder,
            "tiktok_auto_content_pipeline": self._run_tiktok_auto_content_pipeline,
            "tiktok_content_generation_check": self._run_tiktok_content_generation_check,
            "tiktok_performance_sync": self._run_tiktok_performance_sync,
            "tiktok_pipeline_health": self._run_tiktok_pipeline_health,
            "tiktok_weekly_report": self._run_tiktok_weekly_report,
            # Content Agent
            "content_performance_sync": self._run_content_performance_sync,
            "content_improvement_cycle": self._run_content_improvement_cycle,
            "content_trend_research": self._run_content_trend_research,
            # Gateway Auto-Update
            "gateway_update_check": self._run_gateway_update_check,
            # Prediction Market Intelligence
            "prediction_market_sync": self._run_prediction_market_sync,
            "prediction_price_snapshot": self._run_prediction_price_snapshot,
            "prediction_bettor_discovery": self._run_prediction_bettor_discovery,
            "prediction_research": self._run_prediction_research,
            "prediction_push_to_ada": self._run_prediction_push_to_ada,
            "prediction_quality_check": self._run_prediction_quality_check,
            # LLM Budget Reset
            "llm_budget_reset": self._run_llm_budget_reset,
        }
        return handlers.get(job_name)

    # ============================================
    # JOB HANDLERS
    # ============================================

    async def _run_morning_briefing(self):
        """
        Morning briefing automation.

        1. Generate comprehensive briefing with Legion data
        2. Send via Discord (direct API + notification service)
        """
        logger.info("running_morning_briefing")

        try:
            from app.services.briefing_service import get_briefing_service
            from app.services.notification_service import get_notification_service

            # Generate briefing
            briefing_service = get_briefing_service()
            briefing = await briefing_service.generate_briefing()

            # Format for messaging
            message = self._format_briefing_message(briefing)

            # Send via notification service (UI + DB)
            notification_service = get_notification_service()
            await notification_service.create_notification(
                title="Morning Briefing",
                message=message,
                channel="discord",
                source="scheduler"
            )

            # Send directly to Discord #zero channel
            await self._send_to_discord(
                title="Morning Briefing",
                message=message,
                color=0x57F287,  # green
            )

            logger.info(
                "morning_briefing_sent",
                sections=len(briefing.sections)
            )

        except Exception as e:
            logger.error("morning_briefing_failed", error=str(e))

    async def _run_midday_check(self):
        """
        Midday health check.

        1. Check for blocked tasks in Legion
        2. Alert if there are issues
        """
        logger.info("running_midday_check")

        try:
            from app.services.legion_client import get_legion_client
            from app.services.notification_service import get_notification_service

            legion = get_legion_client()

            # Check if Legion is reachable
            if not await legion.health_check():
                logger.warning("legion_not_reachable_midday")
                return

            # Get blocked tasks
            blocked = await legion.get_blocked_tasks()

            if blocked:
                message = f"**Midday Alert**: {len(blocked)} blocked task(s)\n\n"
                for task in blocked[:5]:
                    message += f"- {task.get('title')} ({task.get('sprint_name', 'Unknown')})\n"

                notification_service = get_notification_service()
                await notification_service.create_notification(
                    title="Blocked Tasks Alert",
                    message=message,
                    channel="discord",
                    source="scheduler"
                )

                # Send directly to Discord #zero channel
                await self._send_to_discord(
                    title="Blocked Tasks Alert",
                    message=message,
                    color=0xED4245,  # red
                )

                logger.info("midday_check_alert_sent", blocked=len(blocked))
            else:
                logger.info("midday_check_no_issues")

        except Exception as e:
            logger.error("midday_check_failed", error=str(e))

    async def _run_evening_review(self):
        """
        Evening progress review.

        1. Summarize day's progress from Legion
        2. Prepare for tomorrow
        """
        logger.info("running_evening_review")

        try:
            from app.services.legion_client import get_legion_client
            from app.services.notification_service import get_notification_service

            legion = get_legion_client()

            if not await legion.health_check():
                logger.warning("legion_not_reachable_evening")
                return

            # Get recent executions (today)
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
            executions = await legion.get_recent_executions(since=today_start)

            completed_today = len([
                e for e in executions
                if e.get("status") == "completed"
            ])

            # Get daily summary
            summary = await legion.get_daily_summary()

            message = f"""**Evening Progress Report**

Completed today: {completed_today} task(s)
Active sprints: {summary.get('active_sprints', 0)}
Blocked tasks: {summary.get('blocked_count', 0)}
Project health: {summary.get('healthy_projects', 0)}/{summary.get('total_projects', 0)} healthy

Have a great evening!"""

            notification_service = get_notification_service()
            await notification_service.create_notification(
                title="Evening Progress Report",
                message=message,
                channel="discord",
                source="scheduler"
            )

            # Send directly to Discord #zero channel
            await self._send_to_discord(
                title="Evening Progress Report",
                message=message,
                color=0xFEE75C,  # yellow
            )

            logger.info(
                "evening_review_sent",
                completed=completed_today
            )

        except Exception as e:
            logger.error("evening_review_failed", error=str(e))

    async def _run_enhancement_scan(self):
        """
        Run enhancement signal scan.

        1. Scan all projects for TODO/FIXME/etc.
        2. Convert high-confidence signals to Legion tasks
        """
        logger.info("running_enhancement_scan")

        try:
            from app.services.enhancement_service import get_enhancement_service

            enhancement_service = get_enhancement_service()

            # Scan for signals
            results = await enhancement_service.scan_for_signals()

            logger.info(
                "enhancement_scan_complete",
                signals_found=results.get("total_signals", 0),
                new_signals=results.get("new_signals", 0)
            )

        except Exception as e:
            logger.error("enhancement_scan_failed", error=str(e))

    async def _run_health_aggregation(self):
        """
        Aggregate health data from Legion.

        Updates local health cache for faster briefing generation.
        """
        logger.info("running_health_aggregation")

        try:
            from app.services.legion_client import get_legion_client

            legion = get_legion_client()

            if not await legion.health_check():
                logger.warning("legion_not_reachable_health")
                return

            # Get all project health
            projects = await legion.get_all_projects_summary()

            logger.info(
                "health_aggregation_complete",
                projects=len(projects)
            )

        except Exception as e:
            logger.error("health_aggregation_failed", error=str(e))

    async def _run_money_maker_cycle(self):
        """
        Run the daily money maker cycle.

        1. Generate new ideas using LLM
        2. Research top unresearched ideas via SearXNG
        3. Rank all ideas by viability
        4. Send notification if high-potential ideas found
        """
        logger.info("running_money_maker_cycle")

        try:
            from app.services.money_maker_service import get_money_maker_service

            service = get_money_maker_service()
            result = await service.run_daily_cycle()

            logger.info(
                "money_maker_cycle_complete",
                generated=result.get("generated", 0),
                researched=result.get("researched", 0),
                high_potential=len(result.get("high_potential", []))
            )

        except Exception as e:
            logger.error("money_maker_cycle_failed", error=str(e))

    async def _run_money_maker_weekly_report(self):
        """
        Generate and send weekly money maker summary.
        """
        logger.info("running_money_maker_weekly_report")

        try:
            from app.services.money_maker_service import get_money_maker_service
            from app.services.notification_service import get_notification_service

            service = get_money_maker_service()
            stats = await service.get_stats()
            top_ideas = await service.get_top_ideas(limit=5)

            # Build report message
            lines = ["**Weekly Money Maker Report**\n"]
            lines.append(f"Total ideas: {stats.get('totalIdeas', 0)}")
            lines.append(f"Ideas this week: {stats.get('ideasThisWeek', 0)}")
            lines.append(f"Researched this week: {stats.get('researchedThisWeek', 0)}")
            lines.append(f"Top viability score: {stats.get('topViabilityScore', 0):.1f}")
            lines.append(f"Average viability: {stats.get('avgViabilityScore', 0):.1f}")

            if top_ideas:
                lines.append("\n**Top 5 Ideas:**")
                for idea in top_ideas:
                    lines.append(f"- {idea.title} (Score: {idea.viability_score:.1f})")

            report_message = "\n".join(lines)

            notification_service = get_notification_service()
            await notification_service.create_notification(
                title="Weekly Money Maker Report",
                message=report_message,
                channel="discord",
                source="money_maker"
            )

            # Send directly to Discord #zero channel
            await self._send_to_discord(
                title="Weekly Money Maker Report",
                message=report_message,
                color=0x57F287,  # green
            )

            logger.info("money_maker_weekly_report_sent")

        except Exception as e:
            logger.error("money_maker_weekly_report_failed", error=str(e))

    async def _run_gmail_check(self):
        """
        Incremental Gmail sync every 5 minutes.
        Uses History API for efficient delta sync and checks alert rules.
        """
        logger.info("running_gmail_check")
        try:
            from app.services.gmail_service import get_gmail_service
            gmail = get_gmail_service()

            if not await gmail.is_connected():
                return  # Gmail not configured, skip silently

            result = await gmail.sync_incremental()
            new_count = result.get("new_emails", 0)
            if new_count > 0:
                logger.info("gmail_check_new_emails", count=new_count)
        except Exception as e:
            logger.debug("gmail_check_skipped", error=str(e))

    async def _run_gmail_digest(self):
        """
        Daily email digest at 7:05 AM.
        Generates summary of emails and sends via notification service.
        """
        logger.info("running_gmail_digest")
        try:
            from app.services.gmail_service import get_gmail_service
            from app.services.notification_service import get_notification_service

            gmail = get_gmail_service()

            if not await gmail.is_connected():
                return

            digest = await gmail.generate_digest()

            lines = ["**Daily Email Digest**\n"]
            lines.append(f"Total emails: {digest.total_emails}")
            lines.append(f"Unread: {digest.unread_emails}")

            if digest.by_category:
                lines.append("\n**By Category:**")
                for cat, count in digest.by_category.items():
                    lines.append(f"  - {cat}: {count}")

            if digest.urgent_emails:
                lines.append(f"\n**Urgent ({len(digest.urgent_emails)}):**")
                for e in digest.urgent_emails[:3]:
                    lines.append(f"  - {e.subject} (from {e.from_address.email})")

            if digest.highlights:
                lines.append("\n**Highlights:**")
                for h in digest.highlights:
                    lines.append(f"  - {h}")

            digest_message = "\n".join(lines)

            notification_service = get_notification_service()
            await notification_service.create_notification(
                title="Daily Email Digest",
                message=digest_message,
                channel="discord",
                source="scheduler"
            )

            # Send directly to Discord #zero channel
            await self._send_to_discord(
                title="Daily Email Digest",
                message=digest_message,
                color=0x5865F2,  # blurple
            )

            logger.info("gmail_digest_sent", total=digest.total_emails)

        except Exception as e:
            logger.error("gmail_digest_failed", error=str(e))

    async def _run_email_automation_check(self):
        """
        Email automation check every 5 minutes.
        Processes new unread emails through the automation workflow.
        """
        logger.info("running_email_automation_check")
        try:
            from app.infrastructure.config import get_settings
            from app.services.email_automation_service import get_email_automation_service
            from app.services.gmail_service import get_gmail_service

            settings = get_settings()

            if not settings.email_automation_enabled:
                logger.debug("email_automation_disabled")
                return

            gmail = get_gmail_service()
            if not await gmail.is_connected():
                return  # Gmail not configured, skip silently

            # First, sync new emails
            await gmail.sync_incremental()

            # Then process them through automation
            automation = get_email_automation_service()
            result = await automation.process_new_emails()

            if result.get("processed", 0) > 0:
                logger.info(
                    "email_automation_check_complete",
                    processed=result.get("processed"),
                    succeeded=result.get("succeeded"),
                    questions=result.get("questions_created")
                )

        except Exception as e:
            logger.debug("email_automation_check_skipped", error=str(e))

    # ============================================
    # LEGION INTEGRATION HANDLERS (Sprint 43)
    # ============================================

    async def _run_legion_enhancement_sync(self):
        """Auto-create Legion tasks from high-confidence enhancement signals."""
        logger.info("running_legion_enhancement_sync")
        try:
            from app.services.legion_integration_service import get_legion_integration_service
            svc = get_legion_integration_service()
            result = await svc.auto_create_enhancement_tasks()
            logger.info("legion_enhancement_sync_complete", tasks_created=result.get("tasks_created", 0))
        except Exception as e:
            logger.error("legion_enhancement_sync_failed", error=str(e))

    async def _run_email_to_tasks(self):
        """Convert email action items to Legion tasks."""
        logger.info("running_email_to_tasks")
        try:
            from app.services.legion_integration_service import get_legion_integration_service
            svc = get_legion_integration_service()
            result = await svc.convert_emails_to_tasks()
            logger.info("email_to_tasks_complete", tasks_created=result.get("tasks_created", 0))
        except Exception as e:
            logger.error("email_to_tasks_failed", error=str(e))

    async def _run_meeting_prep(self):
        """Create prep tasks for upcoming meetings."""
        logger.info("running_meeting_prep")
        try:
            from app.services.legion_integration_service import get_legion_integration_service
            svc = get_legion_integration_service()
            result = await svc.create_meeting_prep_tasks()
            logger.info("meeting_prep_complete", tasks_created=result.get("tasks_created", 0))
        except Exception as e:
            logger.error("meeting_prep_failed", error=str(e))

    async def _run_blocked_task_escalation(self):
        """Escalate blocked Legion tasks via Discord."""
        logger.info("running_blocked_task_escalation")
        try:
            from app.services.legion_integration_service import get_legion_integration_service
            svc = get_legion_integration_service()
            result = await svc.escalate_blocked_tasks()
            logger.info("blocked_task_escalation_complete", escalated=result.get("escalated", 0))
        except Exception as e:
            logger.error("blocked_task_escalation_failed", error=str(e))

    async def _run_smart_suggestions(self):
        """Generate cross-project smart task suggestions for briefing."""
        logger.info("running_smart_suggestions")
        try:
            from app.services.legion_integration_service import get_legion_integration_service
            svc = get_legion_integration_service()
            result = await svc.generate_smart_suggestions()
            logger.info("smart_suggestions_complete", suggestions=len(result.get("suggestions", [])))
        except Exception as e:
            logger.error("smart_suggestions_failed", error=str(e))

    # ============================================
    # BACKUP HANDLERS (Sprint 64)
    # ============================================

    async def _run_backup_hourly(self):
        """Hourly workspace backup."""
        from app.services.backup_service import get_backup_service
        await get_backup_service().create_backup(tier="hourly")

    async def _run_backup_daily(self):
        """Daily workspace backup."""
        from app.services.backup_service import get_backup_service
        await get_backup_service().create_backup(tier="daily")

    async def _run_backup_weekly(self):
        """Weekly workspace backup."""
        from app.services.backup_service import get_backup_service
        await get_backup_service().create_backup(tier="weekly")

    async def _run_research_daily(self):
        """Daily research cycle - scan topics and discover new findings."""
        logger.info("running_research_daily")
        try:
            from app.services.research_service import get_research_service
            svc = get_research_service()
            result = await svc.run_daily_cycle()
            logger.info(
                "research_daily_complete",
                findings=result.new_findings,
                tasks=result.tasks_created,
            )
        except Exception as e:
            logger.error("research_daily_failed", error=str(e))

    async def _run_research_weekly_deep_dive(self):
        """Weekly deep dive research with expanded search and trend report."""
        logger.info("running_research_weekly_deep_dive")
        try:
            from app.services.research_service import get_research_service
            svc = get_research_service()
            result = await svc.run_weekly_deep_dive()
            logger.info(
                "research_weekly_complete",
                findings=result.new_findings,
                tasks=result.tasks_created,
            )
        except Exception as e:
            logger.error("research_weekly_failed", error=str(e))

    async def _run_rules_recalibration(self):
        """Weekly recalibration of research rules based on effectiveness."""
        logger.info("running_rules_recalibration")
        try:
            from app.services.research_rules_service import get_research_rules_service
            svc = get_research_rules_service()
            result = await svc.recalibrate_rules()
            logger.info(
                "rules_recalibration_complete",
                disabled=len(result.get("disabled", [])),
                boosted=len(result.get("boosted", [])),
            )
        except Exception as e:
            logger.error("rules_recalibration_failed", error=str(e))

    # ============================================
    # DISK SPACE & EMBEDDING HANDLERS
    # ============================================

    async def _run_disk_space_monitor(self):
        """Monitor disk space and alert when usage exceeds 85%."""
        import shutil
        logger.info("running_disk_space_monitor")
        try:
            alerts = []
            paths_to_check = {
                "workspace": "/app/workspace",
                "backups": "/app/backups",
                "system": "/",
            }
            for name, path in paths_to_check.items():
                try:
                    usage = shutil.disk_usage(path)
                    pct = (usage.used / usage.total) * 100
                    if pct > 85:
                        alerts.append(
                            f"{name} ({path}): {pct:.1f}% used "
                            f"({usage.free // (1024**3)}GB free)"
                        )
                except OSError:
                    pass

            if alerts:
                logger.warning("disk_space_alert", alerts=alerts)
                try:
                    from app.services.notification_service import get_notification_service
                    svc = get_notification_service()
                    await svc.create_notification(
                        title="Disk Space Warning",
                        message="Low disk space:\n" + "\n".join(alerts),
                        channel="discord",
                        source="disk_monitor",
                    )
                except Exception:
                    pass
            else:
                logger.info("disk_space_ok")
        except Exception as e:
            logger.error("disk_space_monitor_failed", error=str(e))

    async def _run_embedding_backfill(self):
        """Backfill embeddings for notes/facts that don't have them yet."""
        logger.info("running_embedding_backfill")
        try:
            from app.services.knowledge_service import get_knowledge_service
            svc = get_knowledge_service()
            result = await svc.backfill_embeddings(batch_size=50)
            if result["notes"] > 0 or result["facts"] > 0:
                logger.info("embedding_backfill_complete", **result)
        except Exception as e:
            logger.error("embedding_backfill_failed", error=str(e))

    # ============================================
    # ECOSYSTEM HANDLERS (S70)
    # ============================================

    async def _run_ecosystem_quick_sync(self):
        """Quick ecosystem sync — lightweight poll of Legion."""
        logger.info("running_ecosystem_quick_sync")
        try:
            from app.services.ecosystem_sync_service import get_ecosystem_sync_service
            svc = get_ecosystem_sync_service()
            result = await svc.quick_sync()
            logger.info("ecosystem_quick_sync_done", **{k: v for k, v in result.items() if k != "status"})
        except Exception as e:
            logger.error("ecosystem_quick_sync_failed", error=str(e))

    async def _run_ecosystem_full_sync(self):
        """Full ecosystem sync — deep fetch of all project data."""
        logger.info("running_ecosystem_full_sync")
        try:
            from app.services.ecosystem_sync_service import get_ecosystem_sync_service
            svc = get_ecosystem_sync_service()
            result = await svc.full_sync()
            logger.info("ecosystem_full_sync_done", **{k: v for k, v in result.items() if k != "status"})
        except Exception as e:
            logger.error("ecosystem_full_sync_failed", error=str(e))

    async def _run_ecosystem_execution_monitor(self):
        """Monitor Legion autonomous execution status."""
        logger.info("running_ecosystem_execution_monitor")
        try:
            from app.services.ecosystem_sync_service import get_ecosystem_sync_service
            svc = get_ecosystem_sync_service()
            result = await svc.sync_executions()
            if result.get("new_failures", 0) > 0:
                logger.warning("ecosystem_execution_failures_detected", failures=result["new_failures"])
        except Exception as e:
            logger.error("ecosystem_execution_monitor_failed", error=str(e))

    async def _run_ecosystem_lifecycle_check(self):
        """Detect sprint lifecycle events across all projects."""
        logger.info("running_ecosystem_lifecycle_check")
        try:
            from app.services.ecosystem_sync_service import get_ecosystem_sync_service
            svc = get_ecosystem_sync_service()
            events = await svc.detect_lifecycle_events()
            if events:
                logger.info("ecosystem_lifecycle_events", count=len(events))
        except Exception as e:
            logger.error("ecosystem_lifecycle_check_failed", error=str(e))

    # ============================================
    # AUTONOMOUS ORCHESTRATION HANDLERS (S70 Phase 2)
    # ============================================

    async def _run_autonomous_daily_orchestration(self):
        """Full autopilot: sync, trigger swarm, plan sprints across all projects."""
        logger.info("running_autonomous_daily_orchestration")
        try:
            from app.services.autonomous_orchestration_service import get_orchestration_service
            svc = get_orchestration_service()
            result = await svc.run_daily_orchestration()
            logger.info(
                "autonomous_daily_orchestration_complete",
                actions=result.get("actions_taken", 0),
                errors=result.get("errors", 0),
            )
        except Exception as e:
            logger.error("autonomous_daily_orchestration_failed", error=str(e))

    async def _run_autonomous_continuous_monitor(self):
        """Monitor for failed/stuck executions across all projects."""
        logger.info("running_autonomous_continuous_monitor")
        try:
            from app.services.autonomous_orchestration_service import get_orchestration_service
            svc = get_orchestration_service()
            result = await svc.run_continuous_monitor()
            if result.get("issue_count", 0) > 0:
                logger.warning("autonomous_monitor_issues", count=result["issue_count"])
        except Exception as e:
            logger.error("autonomous_continuous_monitor_failed", error=str(e))

    async def _run_autonomous_enhancement_cycle(self):
        """Multi-project enhancement scan + auto-create Legion tasks."""
        logger.info("running_autonomous_enhancement_cycle")
        try:
            from app.services.autonomous_orchestration_service import get_orchestration_service
            svc = get_orchestration_service()
            result = await svc.run_enhancement_cycle()
            logger.info(
                "autonomous_enhancement_cycle_complete",
                signals=result.get("signals_found", 0),
                tasks=result.get("tasks_created", 0),
            )
        except Exception as e:
            logger.error("autonomous_enhancement_cycle_failed", error=str(e))

    async def _run_qa_verification(self):
        """Daily QA verification of all systems."""
        logger.info("running_qa_verification")
        try:
            from app.services.qa_verification_service import get_qa_verification_service
            svc = get_qa_verification_service()
            report = await svc.run_full_verification(
                trigger="scheduled",
                auto_create_tasks=False,  # Don't auto-create tasks on scheduled runs
            )
            logger.info(
                "qa_verification_complete",
                report_id=report.report_id,
                status=report.overall_status.value,
                passed=report.passed_count,
                failed=report.failed_count,
            )
        except Exception as e:
            logger.error("qa_verification_failed", error=str(e))

    # ============================================
    # DAILY SELF-IMPROVEMENT HANDLERS
    # ============================================

    async def _run_daily_improvement_plan(self):
        """Select top 5 improvements for today."""
        logger.info("running_daily_improvement_plan")
        try:
            from app.services.daily_improvement_service import get_daily_improvement_service
            svc = get_daily_improvement_service()
            result = await svc.create_daily_plan()
            logger.info(
                "daily_improvement_plan_complete",
                improvements=len(result.get("selected_improvements", [])),
            )
        except Exception as e:
            logger.error("daily_improvement_plan_failed", error=str(e))

    async def _run_daily_improvement_execute(self):
        """Execute today's improvement plan."""
        logger.info("running_daily_improvement_execute")
        try:
            from app.services.daily_improvement_service import get_daily_improvement_service
            svc = get_daily_improvement_service()
            result = await svc.execute_daily_plan()
            logger.info(
                "daily_improvement_execute_complete",
                auto_fixes=result.get("auto_fixes_applied", 0),
                total=result.get("total_improvements", 0),
            )
        except Exception as e:
            logger.error("daily_improvement_execute_failed", error=str(e))

    async def _run_daily_improvement_verify(self):
        """Verify today's improvements and update metrics."""
        logger.info("running_daily_improvement_verify")
        try:
            from app.services.daily_improvement_service import get_daily_improvement_service
            svc = get_daily_improvement_service()
            result = await svc.verify_daily_plan()
            logger.info(
                "daily_improvement_verify_complete",
                verified=result.get("verified", 0),
                failed=result.get("failed", 0),
            )
        except Exception as e:
            logger.error("daily_improvement_verify_failed", error=str(e))

    # ============================================
    # AUTONOMOUS TASK WORKER
    # ============================================

    async def _run_task_worker(self):
        """Pick up queued autonomous tasks and execute them."""
        logger.info("running_task_worker")
        try:
            from app.services.task_execution_service import get_task_execution_service
            executor = get_task_execution_service()
            await executor.check_and_execute()
        except Exception as e:
            logger.error("task_worker_failed", error=str(e))

    async def _run_task_progress_check(self):
        """Report progress on currently executing autonomous task."""
        try:
            from app.services.task_execution_service import get_task_execution_service
            executor = get_task_execution_service()

            if not executor.is_busy():
                return

            status = executor.get_status()
            current = status.get("current_task")
            if not current:
                return

            title = current.get("title", "Unknown")
            step = current.get("current_step", 0)
            total = current.get("total_steps", 0)
            progress = current.get("progress_percent", 0)

            logger.info(
                "task_progress_report",
                title=title,
                step=f"{step}/{total}",
                progress=f"{progress}%",
            )
        except Exception as e:
            logger.error("task_progress_check_failed", error=str(e))

    # ============================================
    # CONTINUOUS ENHANCEMENT ENGINE
    # ============================================

    async def _run_continuous_enhancement_engine(self):
        """Run one cycle of the continuous enhancement engine."""
        logger.info("running_continuous_enhancement_engine")
        try:
            from app.services.continuous_enhancement_service import get_continuous_enhancement_service
            engine = get_continuous_enhancement_service()
            await engine.run_cycle()
        except Exception as e:
            logger.error("continuous_enhancement_engine_failed", error=str(e))

    async def _run_gpu_refresh(self):
        """Refresh GPU/Ollama resource status."""
        try:
            from app.services.gpu_manager_service import get_gpu_manager_service
            svc = get_gpu_manager_service()
            await svc.refresh()
        except Exception as e:
            logger.error("gpu_refresh_failed", error=str(e))

    # ============================================
    # REMINDER CHECK
    # ============================================

    async def _run_reminder_check(self):
        """Check for due reminders and send notifications."""
        try:
            from app.services.reminder_service import get_reminder_service
            from app.services.notification_service import get_notification_service

            reminder_service = get_reminder_service()
            due_reminders = await reminder_service.get_due_reminders()

            if not due_reminders:
                return

            notification_service = get_notification_service()

            for reminder in due_reminders:
                # Send notification
                channel = "discord"
                if reminder.channels:
                    channel = reminder.channels[0].value if hasattr(reminder.channels[0], 'value') else reminder.channels[0]

                await notification_service.create_notification(
                    title=f"Reminder: {reminder.title}",
                    message=reminder.description or reminder.title,
                    channel=channel,
                    source="reminder",
                    source_id=reminder.id,
                )

                # Mark as triggered (handles recurrence automatically)
                await reminder_service.trigger_reminder(reminder.id)

            logger.info("reminder_check_complete", triggered=len(due_reminders))

        except Exception as e:
            logger.error("reminder_check_failed", error=str(e))

    # ============================================
    # ALERTING & METRICS HANDLERS
    # ============================================

    async def _run_alerting_check(self):
        """Evaluate alert rules and fire Discord notifications."""
        try:
            from app.services.alerting_service import get_alerting_service
            svc = get_alerting_service()
            await svc.check_alerts()
        except Exception as e:
            logger.error("alerting_check_failed", error=str(e))

    async def _run_metrics_snapshot(self):
        """Persist hourly metrics summary to PostgreSQL."""
        try:
            from app.services.metrics_service import get_metrics_service
            svc = get_metrics_service()
            await svc.persist_snapshot()
            logger.info("metrics_snapshot_complete")
        except Exception as e:
            logger.error("metrics_snapshot_failed", error=str(e))

    async def _run_backup_restore_test(self):
        """Weekly backup extraction and validation test."""
        logger.info("running_backup_restore_test")
        try:
            from app.services.backup_service import get_backup_service
            svc = get_backup_service()
            result = await svc.test_restore()
            if result.get("success"):
                logger.info("backup_restore_test_passed", files=result.get("files_restored", 0))
            else:
                logger.error("backup_restore_test_failed", error=result.get("error"))
                from app.services.notification_service import get_notification_service
                await get_notification_service().create_notification(
                    title="Backup Restore Test FAILED",
                    message=f"Weekly backup test failed: {result.get('error')}",
                    channel="discord",
                    source="alerting",
                )
        except Exception as e:
            logger.error("backup_restore_test_failed", error=str(e))

    # ============================================
    # NOTION BIDIRECTIONAL SYNC
    # ============================================

    async def _run_notion_bidirectional_sync(self):
        """Bidirectional sync with Notion."""
        logger.info("running_notion_bidirectional_sync")
        try:
            from app.services.notion_service import get_notion_service
            svc = get_notion_service()
            if svc:
                result = await svc.sync_bidirectional()
                if result.get("synced_from_notion", 0) > 0:
                    logger.info("notion_sync_complete", **result)
        except Exception as e:
            logger.error("notion_bidirectional_sync_failed", error=str(e))

    # ============================================
    # TIKTOK SHOP & CONTENT AGENT HANDLERS
    # ============================================

    async def _run_tiktok_shop_research(self):
        """Daily TikTok Shop product discovery and opportunity scoring."""
        logger.info("running_tiktok_shop_research")
        try:
            from app.services.tiktok_shop_service import get_tiktok_shop_service
            svc = get_tiktok_shop_service()
            result = await svc.run_daily_research_cycle()
            logger.info("tiktok_shop_research_complete",
                        discovered=result.products_discovered,
                        researched=result.products_researched,
                        topics_created=result.content_topics_created,
                        tasks_created=result.legion_tasks_created)
            if result.products_discovered > 0:
                await self._send_to_discord(
                    "TikTok Shop Research",
                    f"Discovered {result.products_discovered} products, "
                    f"created {result.content_topics_created} content topics, "
                    f"{result.legion_tasks_created} Legion tasks",
                    color=0xFF6B6B,
                )
        except Exception as e:
            logger.error("tiktok_shop_research_failed", error=str(e))

    async def _run_tiktok_shop_deep_research(self):
        """Saturday deep research on top TikTok Shop products."""
        logger.info("running_tiktok_shop_deep_research")
        try:
            from app.services.tiktok_shop_service import get_tiktok_shop_service
            svc = get_tiktok_shop_service()
            products = await svc.list_products(limit=10)
            # Deep research on top-scoring products
            products.sort(key=lambda p: p.opportunity_score or 0, reverse=True)
            researched = 0
            for p in products[:5]:
                try:
                    await svc.research_product_deep(p.id)
                    researched += 1
                except Exception:
                    continue
            logger.info("tiktok_shop_deep_research_complete", researched=researched)
        except Exception as e:
            logger.error("tiktok_shop_deep_research_failed", error=str(e))

    # ============================================
    # TIKTOK 24/7 PIPELINE AUTOMATION
    # ============================================

    async def _run_tiktok_continuous_research(self):
        """Run the TikTok research pipeline every 4 hours."""
        logger.info("running_tiktok_continuous_research")
        try:
            from app.services.tiktok_agent_graph import invoke_tiktok_pipeline
            result = await invoke_tiktok_pipeline(mode="research_only")
            logger.info("tiktok_continuous_research_complete",
                        status=result["status"],
                        discovered=result.get("products_discovered", 0))
            if result.get("products_discovered", 0) > 0:
                await self._send_to_discord(
                    "TikTok Continuous Research",
                    f"Discovered {result['products_discovered']} new products. "
                    f"Auto-approved: {result.get('auto_approved', 0)}, "
                    f"Pending review: {result.get('pending_review', 0)}",
                    color=0xFF6B6B,
                )
        except Exception as e:
            logger.error("tiktok_continuous_research_failed", error=str(e))

    async def _run_tiktok_niche_deep_dive(self):
        """Deep dive into top-performing niches for new product ideas."""
        logger.info("running_tiktok_niche_deep_dive")
        try:
            from app.services.tiktok_shop_service import get_tiktok_shop_service
            svc = get_tiktok_shop_service()
            stats = await svc.get_stats()
            top_niches = stats.top_niches[:3] if stats.top_niches else []
            researched = 0
            for niche in top_niches:
                try:
                    products = await svc.list_products(niche=niche, limit=5)
                    for p in products[:3]:
                        await svc.research_product_deep(p.id)
                        researched += 1
                except Exception:
                    continue
            logger.info("tiktok_niche_deep_dive_complete",
                        niches=len(top_niches), researched=researched)
        except Exception as e:
            logger.error("tiktok_niche_deep_dive_failed", error=str(e))

    async def _run_tiktok_approval_reminder(self):
        """Send Discord reminder for products pending approval."""
        logger.info("running_tiktok_approval_reminder")
        try:
            from app.services.tiktok_shop_service import get_tiktok_shop_service
            svc = get_tiktok_shop_service()
            pending = await svc.list_pending(limit=50)
            if pending:
                lines = [f"**{len(pending)} TikTok products awaiting your approval:**\n"]
                for p in pending[:10]:
                    lines.append(f"- [{p.opportunity_score:.0f}] {p.name} ({p.niche or 'general'})")
                if len(pending) > 10:
                    lines.append(f"\n...and {len(pending) - 10} more")
                lines.append("\nReview in the TikTok Shop dashboard → Approval Queue tab.")
                await self._send_to_discord(
                    "TikTok Approval Reminder",
                    "\n".join(lines),
                    color=0xFFA500,
                )
                logger.info("tiktok_approval_reminder_sent", pending=len(pending))
            else:
                logger.info("tiktok_approval_reminder_none_pending")
        except Exception as e:
            logger.error("tiktok_approval_reminder_failed", error=str(e))

    async def _run_tiktok_auto_content_pipeline(self):
        """Auto-generate video scripts for approved products that don't have scripts yet."""
        logger.info("running_tiktok_auto_content_pipeline")
        try:
            from app.services.tiktok_agent_graph import invoke_tiktok_pipeline
            result = await invoke_tiktok_pipeline(mode="content_only")
            logger.info("tiktok_auto_content_pipeline_complete",
                        status=result["status"],
                        scripts=result.get("scripts_generated", 0),
                        queued=result.get("generation_jobs", 0))
            if result.get("scripts_generated", 0) > 0:
                await self._send_to_discord(
                    "TikTok Content Pipeline",
                    f"Generated {result['scripts_generated']} video scripts, "
                    f"queued {result.get('generation_jobs', 0)} for video generation.",
                    color=0x9B59B6,
                )
        except Exception as e:
            logger.error("tiktok_auto_content_pipeline_failed", error=str(e))

    async def _run_tiktok_content_generation_check(self):
        """Poll AIContentTools for completed video generation jobs."""
        logger.info("running_tiktok_content_generation_check")
        try:
            from app.services.tiktok_video_service import get_tiktok_video_service
            video_svc = get_tiktok_video_service()
            queue = await video_svc.list_content_queue(status="generating")
            checked = 0
            completed = 0
            for item in queue:
                try:
                    updated = await video_svc.check_generation_status(item.id)
                    checked += 1
                    if updated and updated.status == "completed":
                        completed += 1
                except Exception:
                    continue
            logger.info("tiktok_content_generation_check_complete",
                        checked=checked, completed=completed)
        except Exception as e:
            logger.error("tiktok_content_generation_check_failed", error=str(e))

    async def _run_tiktok_performance_sync(self):
        """Sync TikTok performance metrics and run improvement cycle."""
        logger.info("running_tiktok_performance_sync")
        try:
            from app.services.tiktok_agent_graph import invoke_tiktok_pipeline
            result = await invoke_tiktok_pipeline(mode="performance_only")
            logger.info("tiktok_performance_sync_complete",
                        status=result["status"],
                        summary=result.get("summary", ""))
        except Exception as e:
            logger.error("tiktok_performance_sync_failed", error=str(e))

    async def _run_tiktok_pipeline_health(self):
        """Health check for TikTok pipeline — alert on failures, retry stuck jobs."""
        logger.info("running_tiktok_pipeline_health")
        try:
            from app.services.tiktok_video_service import get_tiktok_video_service
            video_svc = get_tiktok_video_service()
            stats = await video_svc.get_queue_stats()
            issues = []
            if stats.failed > 0:
                issues.append(f"{stats.failed} failed generation jobs")
            # Check for stuck generating jobs (>30 min)
            generating = await video_svc.list_content_queue(status="generating")
            stuck = 0
            for item in generating:
                try:
                    from datetime import datetime, timezone
                    created = datetime.fromisoformat(item.created_at.replace("Z", "+00:00")) if isinstance(item.created_at, str) else item.created_at
                    if (datetime.now(timezone.utc) - created).total_seconds() > 1800:
                        stuck += 1
                except Exception:
                    pass
            if stuck > 0:
                issues.append(f"{stuck} stuck generating jobs (>30 min)")
            if issues:
                await self._send_to_discord(
                    "TikTok Pipeline Health Alert",
                    "Issues detected:\n" + "\n".join(f"- {i}" for i in issues),
                    color=0xED4245,
                )
            logger.info("tiktok_pipeline_health_check_complete", issues=len(issues))
        except Exception as e:
            logger.error("tiktok_pipeline_health_failed", error=str(e))

    async def _run_tiktok_weekly_report(self):
        """Sunday weekly TikTok Shop performance report to Discord."""
        logger.info("running_tiktok_weekly_report")
        try:
            from app.services.tiktok_shop_service import get_tiktok_shop_service
            from app.services.tiktok_video_service import get_tiktok_video_service
            shop_svc = get_tiktok_shop_service()
            video_svc = get_tiktok_video_service()
            stats = await shop_svc.get_stats()
            queue_stats = await video_svc.get_queue_stats()
            report = (
                f"**Weekly TikTok Shop Report**\n\n"
                f"Products: {stats.total_products} total "
                f"({stats.active_products} active, {stats.approved_products} approved, "
                f"{stats.pending_approval_products} pending)\n"
                f"Avg opportunity score: {stats.avg_opportunity_score:.1f}\n"
                f"Top niches: {', '.join(stats.top_niches[:5]) if stats.top_niches else 'none'}\n\n"
                f"**Content Pipeline:**\n"
                f"Scripts: {queue_stats.total_scripts}\n"
                f"Videos completed: {queue_stats.completed}\n"
                f"Videos queued: {queue_stats.total_queued}\n"
                f"Videos failed: {queue_stats.failed}"
            )
            await self._send_to_discord(
                "TikTok Weekly Report",
                report,
                color=0x3498DB,
            )
            logger.info("tiktok_weekly_report_sent")
        except Exception as e:
            logger.error("tiktok_weekly_report_failed", error=str(e))

    async def _run_content_performance_sync(self):
        """Sync content performance metrics from AIContentTools."""
        logger.info("running_content_performance_sync")
        try:
            from app.services.content_agent_service import get_content_agent_service
            svc = get_content_agent_service()
            updated = await svc.sync_performance_metrics()
            if updated > 0:
                logger.info("content_performance_sync_complete", updated=updated)
        except Exception as e:
            logger.error("content_performance_sync_failed", error=str(e))

    async def _run_content_improvement_cycle(self):
        """Daily content rule improvement from performance feedback."""
        logger.info("running_content_improvement_cycle")
        try:
            from app.services.content_agent_service import get_content_agent_service
            svc = get_content_agent_service()
            result = await svc.run_improvement_cycle()
            logger.info("content_improvement_cycle_complete", result=result)
        except Exception as e:
            logger.error("content_improvement_cycle_failed", error=str(e))

    async def _run_content_trend_research(self):
        """Research trending content for active topics."""
        logger.info("running_content_trend_research")
        try:
            from app.services.content_agent_service import get_content_agent_service
            svc = get_content_agent_service()
            topics = await svc.list_topics(status="active")
            researched = 0
            for topic in topics[:5]:
                try:
                    await svc.research_content_trends(topic.id)
                    researched += 1
                except Exception:
                    continue
            logger.info("content_trend_research_complete", topics_researched=researched)
        except Exception as e:
            logger.error("content_trend_research_failed", error=str(e))

    # ============================================
    # GATEWAY AUTO-UPDATE
    # ============================================

    async def _run_gateway_update_check(self):
        """Check for OpenClaw gateway updates via GitHub API."""
        logger.info("running_gateway_update_check")
        try:
            from app.services.gateway_updater_service import get_gateway_updater_service
            svc = get_gateway_updater_service()
            result = await svc.check_for_updates()
            if result.get("update_available"):
                logger.info(
                    "gateway_update_available",
                    current=result["current"],
                    latest=result["latest"],
                )
            else:
                logger.info("gateway_up_to_date", version=result.get("current"))
        except Exception as e:
            logger.error("gateway_update_check_failed", error=str(e))

    # ============================================
    # PREDICTION MARKET INTELLIGENCE
    # ============================================

    async def _run_prediction_market_sync(self):
        """Sync Kalshi + Polymarket markets."""
        logger.info("running_prediction_market_sync")
        try:
            from app.services.prediction_market_service import get_prediction_market_service
            svc = get_prediction_market_service()
            kalshi = await svc.sync_kalshi_markets()
            polymarket = await svc.sync_polymarket_markets()
            logger.info("prediction_market_sync_complete", kalshi=kalshi, polymarket=polymarket)
        except Exception as e:
            logger.error("prediction_market_sync_failed", error=str(e))

    async def _run_prediction_price_snapshot(self):
        """Capture prediction market price snapshots."""
        try:
            from app.services.prediction_market_service import get_prediction_market_service
            svc = get_prediction_market_service()
            result = await svc.capture_price_snapshots()
            logger.info("prediction_price_snapshot_complete", count=result.get("snapshots_created", 0))
        except Exception as e:
            logger.error("prediction_price_snapshot_failed", error=str(e))

    async def _run_prediction_bettor_discovery(self):
        """Discover and update top prediction market bettors."""
        logger.info("running_prediction_bettor_discovery")
        try:
            from app.services.prediction_market_service import get_prediction_market_service
            svc = get_prediction_market_service()
            result = await svc.discover_top_bettors()
            await svc.update_bettor_stats()
            logger.info("prediction_bettor_discovery_complete", result=result)
        except Exception as e:
            logger.error("prediction_bettor_discovery_failed", error=str(e))

    async def _run_prediction_research(self):
        """SearXNG prediction market research."""
        logger.info("running_prediction_research")
        try:
            from app.services.prediction_market_service import get_prediction_market_service
            svc = get_prediction_market_service()
            result = await svc.research_market_insights()
            logger.info("prediction_research_complete", findings=result.get("findings_count", 0))
        except Exception as e:
            logger.error("prediction_research_failed", error=str(e))

    async def _run_prediction_push_to_ada(self):
        """Push prediction market data to ADA."""
        try:
            from app.services.prediction_market_service import get_prediction_market_service
            svc = get_prediction_market_service()
            result = await svc.push_to_ada()
            logger.info("prediction_push_to_ada_complete", result=result)
        except Exception as e:
            logger.error("prediction_push_to_ada_failed", error=str(e))

    async def _run_prediction_quality_check(self):
        """Prediction market quality + Legion progress report."""
        logger.info("running_prediction_quality_check")
        try:
            from app.services.prediction_market_service import get_prediction_market_service
            from app.services.prediction_legion_manager import get_prediction_legion_manager
            svc = get_prediction_market_service()
            mgr = get_prediction_legion_manager()

            quality = await svc.get_quality_report()
            legion = await mgr.report_legion_quality()

            # Alert to Discord if issues detected
            issues = []
            collection = quality.get("collection_health", {})
            if collection.get("sync_success_rate_24h", 1.0) < 0.9:
                issues.append(f"Sync success rate: {collection.get('sync_success_rate_24h', 0):.0%}")
            if legion.get("quality_score", 100) < 50:
                issues.append(f"Legion quality score: {legion.get('quality_score', 0):.0f}/100")

            if issues:
                await self._send_to_discord(
                    "⚠️ Prediction Market Issues",
                    "\n".join(issues),
                    color=0xFF9900
                )

            logger.info(
                "prediction_quality_check_complete",
                legion_score=legion.get("quality_score", 0),
                issues=len(issues),
            )
        except Exception as e:
            logger.error("prediction_quality_check_failed", error=str(e))

    # ============================================
    # LLM BUDGET RESET
    # ============================================

    async def _run_llm_budget_reset(self):
        """Reset daily LLM spend counter at midnight."""
        try:
            from app.infrastructure.llm_router import get_llm_router
            router = get_llm_router()
            await router.reset_daily_budget()
            logger.info("llm_budget_reset_complete")
        except Exception as e:
            logger.error("llm_budget_reset_failed", error=str(e))

    # ============================================
    # UTILITIES
    # ============================================

    async def _send_to_discord(self, title: str, message: str, color: int = 0x5865F2):
        """Send a notification to the #zero Discord channel via embed."""
        try:
            from app.services.discord_notifier import get_discord_notifier
            notifier = get_discord_notifier()
            if notifier.configured:
                await notifier.send_embed(title=title, description=message[:4096], color=color)
        except Exception as e:
            logger.debug("discord_direct_send_skipped", error=str(e))

    def _format_briefing_message(self, briefing) -> str:
        """Format briefing for messaging."""
        lines = [f"**{briefing.greeting}**\n"]

        for section in briefing.sections:
            lines.append(f"\n{section.icon} **{section.title}**")
            for item in section.items[:5]:
                lines.append(f"  {item}")

        if briefing.suggestions:
            lines.append("\n💡 **Suggestions**")
            for suggestion in briefing.suggestions[:3]:
                lines.append(f"  - {suggestion}")

        return "\n".join(lines)

    # ============================================
    # MANUAL TRIGGERS
    # ============================================

    async def trigger_job(self, job_name: str) -> Dict[str, Any]:
        """Manually trigger a scheduled job (goes through audit log)."""
        handler = self._get_handler(job_name)
        if not handler:
            return {"success": False, "error": f"Unknown job: {job_name}"}

        try:
            await self._run_with_audit(job_name, handler)
            return {"success": True, "job": job_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            })

        return {
            "running": self._running,
            "jobs": jobs,
            "job_count": len(jobs)
        }


# ============================================
# SINGLETON
# ============================================

_scheduler_service: Optional[SchedulerService] = None


def get_scheduler_service() -> SchedulerService:
    """Get the singleton scheduler service instance."""
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService()
    return _scheduler_service


async def start_scheduler():
    """Start the scheduler (call from app startup)."""
    scheduler = get_scheduler_service()
    await scheduler.start()


async def stop_scheduler():
    """Stop the scheduler (call from app shutdown)."""
    scheduler = get_scheduler_service()
    await scheduler.stop()
