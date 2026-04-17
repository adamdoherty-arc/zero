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
        "cron": "*/5 * * * *",  # Every 5 minutes (was 2min — too aggressive)
        "description": "Pick up queued autonomous tasks and execute them",
        "enabled": True
    },
    "task_progress_check": {
        "cron": "*/10 * * * *",  # Every 10 minutes (was 5min)
        "description": "Report progress on currently executing autonomous task",
        "enabled": True
    },
    # Continuous Enhancement Engine
    "continuous_enhancement_engine": {
        "cron": "*/30 * * * *",  # Every 30 minutes (was 10min — too aggressive, hits SearXNG limits)
        "description": "Continuous enhancement engine - scan, analyze, queue improvements for Zero and Legion",
        "enabled": True
    },
    # GPU/Ollama Resource Manager
    "gpu_refresh": {
        "cron": "*/5 * * * *",  # Every 5 minutes (was every 1 min — too aggressive)
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
        "cron": "0 */4 * * *",  # Every 4 hours (was 2h — reduced to ease SearXNG load)
        "description": "Continuous TikTok product discovery pipeline (6x daily)",
        "enabled": True
    },
    "tiktok_niche_deep_dive": {
        "cron": "0 14 * * *",  # 2:00 PM daily
        "description": "Deep dive research into top performing niches",
        "enabled": True
    },
    "tiktok_niche_rotation": {
        "cron": "30 */3 * * *",  # Every 3 hours, offset by 30min
        "description": "Rotate through random niches for deeper product discovery",
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
    "tiktok_reference_discovery": {
        "cron": "0 */6 * * *",  # Every 6 hours
        "description": "Auto-discover reference videos from successful sellers for approved products",
        "enabled": True
    },
    "tiktok_weekly_report": {
        "cron": "0 10 * * 0",  # Sunday 10:00 AM
        "description": "Weekly TikTok Shop performance report to Discord",
        "enabled": True
    },
    "tiktok_image_revalidation": {
        "cron": "0 3 * * *",  # Daily at 3:00 AM
        "description": "Revalidate product images and re-fetch broken ones",
        "enabled": True
    },
    "tiktok_article_cleanup": {
        "cron": "30 1 * * *",  # Daily at 1:30 AM
        "description": "Clean up products with article titles instead of product names",
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
    # Prediction Market Intelligence
    "prediction_market_sync": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Sync Kalshi + Polymarket markets",
        "enabled": True
    },
    "prediction_price_snapshot": {
        "cron": "*/30 * * * *",  # Every 30 minutes (was 15min — reduced API load)
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
    # Daily Autonomous Report
    "daily_autonomous_report": {
        "cron": "0 20 * * *",  # 8:00 PM daily — end-of-day summary
        "description": "Generate daily report of all autonomous activity, failures, and missing jobs",
        "enabled": True
    },
    # AI Company — Deep Research & Experiments
    "ai_company_deep_research": {
        "cron": "0 */6 * * *",  # Every 6 hours
        "description": "Run deep research on highest-priority queued topic",
        "enabled": True
    },
    "ai_company_idea_validation": {
        "cron": "0 */4 * * *",  # Every 4 hours
        "description": "Deep-validate top-scoring unvalidated money-maker ideas",
        "enabled": True
    },
    "ai_company_daily_council": {
        "cron": "0 9 * * *",  # 9:00 AM daily
        "description": "CEO proposes strategic decisions based on overnight findings for council vote",
        "enabled": True
    },
    "ai_company_experiment_monitor": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "Check running experiments, flag stale ones",
        "enabled": True
    },
    # Character Content
    "character_research_refresh": {
        "cron": "0 3 * * *",  # 3:00 AM daily
        "description": "Re-research characters with stale data (>7 days old)",
        "enabled": True
    },
    "character_content_generation": {
        "cron": "0 */4 * * *",  # Every 4 hours - aggressive 24/7 content production
        "description": "Auto-generate carousels for researched characters, priority-tier ordered",
        "enabled": True
    },
    "character_performance_sync": {
        "cron": "0 */6 * * *",  # Every 6 hours
        "description": "Sync performance metrics from published character carousels",
        "enabled": True
    },
    "character_auto_publish": {
        "cron": "0 10,14,18 * * *",  # 10am, 2pm, 6pm
        "description": "Auto-publish approved carousels at optimal times",
        "enabled": True
    },
    "character_content_learning": {
        "cron": "0 */4 * * *",  # Every 4 hours
        "description": "Character content learning & template scoring",
        "enabled": True
    },
    "carousel_banned_hook_backfill": {
        "cron": "0 4 * * *",  # 4:00 AM daily
        "description": "Scan non-published carousels for banned hook patterns (e.g. 'The Hammer Lie') and rewrite them",
        "enabled": True,
    },
    "character_reference_video_processor": {
        "cron": "* * * * *",  # Every 1 minute
        "description": "Download / transcribe / analyze newly ingested TikTok reference videos",
        "enabled": True
    },
    "character_reference_video_cleanup": {
        "cron": "0 4 * * *",  # 4:00 AM daily
        "description": "Purge video/audio files for reference videos older than 30 days (keep metadata + thumbnail)",
        "enabled": True
    },
    "character_image_cleanup": {
        "cron": "0 */6 * * *",  # Every 6 hours
        "description": "Auto-delete broken character image URLs and blocklist them",
        "enabled": True
    },
    # Phase 024: Character Autopilot (6 new jobs)
    "character_auto_approval": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Auto-approve carousels with final_review_score >= threshold",
        "enabled": True
    },
    "character_publish_backlog": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "Keep approved+queued backlog above target (generates + approves as needed)",
        "enabled": True
    },
    "character_discovery": {
        "cron": "0 1 * * *",  # 1:00 AM daily
        "description": "Autonomous character discovery (Wikipedia + TMDB + Reddit + SearXNG)",
        "enabled": True
    },
    "character_gap_audit": {
        "cron": "0 2 * * *",  # 2:00 AM daily
        "description": "Audit characters for image/angle/fact/hook gaps, enqueue fill work",
        "enabled": True
    },
    "character_hook_audit": {
        "cron": "0 */6 * * *",  # Every 6 hours
        "description": "Score and regenerate weak hooks (hook_strength < 6)",
        "enabled": True
    },
    "character_discovery_refvideos": {
        "cron": "*/15 * * * *",  # Every 15 minutes
        "description": "Promote proposed characters from analyzed TikTok reference videos",
        "enabled": True
    },
    "character_final_review_backfill": {
        "cron": "*/20 * * * *",  # Every 20 minutes
        "description": "Run Stage 2 final review on carousels with ai_review_score >= 7 AND final_review_score IS NULL",
        "enabled": True
    },
    # Zero Brain Intelligence
    "brain_benchmark": {
        "cron": "0 */6 * * *",  # Every 6 hours
        "description": "Run full brain benchmark (10-dimension employee scoring)",
        "enabled": True
    },
    "brain_learning_cycle": {
        "cron": "0 */4 * * *",  # Every 4 hours
        "description": "Run brain learning aggregation (outcomes, memories, metrics)",
        "enabled": True
    },
    "brain_content_learn": {
        "cron": "0 * * * *",  # Every 1 hour
        "description": "Process content outcomes and extract learnings",
        "enabled": True
    },
    "brain_experiment_monitor": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "Check brain content experiments for completion",
        "enabled": True
    },
    "brain_prompt_evolve": {
        "cron": "0 */12 * * *",  # Every 12 hours
        "description": "Evolve prompt variants from outcome data",
        "enabled": True
    },
    "brain_prompt_grade": {
        "cron": "*/10 * * * *",  # Every 10 minutes
        "description": "Kimi-as-judge grades ungraded prompt runs",
        "enabled": True
    },
    "brain_episodic_extract": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Extract episodic memories from recent LLM interactions",
        "enabled": True
    },
    "brain_improvement": {
        "cron": "0 3 * * *",  # Daily at 3 AM
        "description": "Auto-improve weakest benchmark dimension",
        "enabled": True
    },
    "brain_reflection": {
        "cron": "0 */8 * * *",  # Every 8 hours
        "description": "Run reflection on recent decisions and outcomes",
        "enabled": True
    },
    "brain_memory_cleanup": {
        "cron": "0 4 * * *",  # Daily at 4 AM
        "description": "Cleanup expired episodic memories",
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
            "tiktok_niche_rotation": self._run_tiktok_niche_rotation,
            "tiktok_approval_reminder": self._run_tiktok_approval_reminder,
            "tiktok_auto_content_pipeline": self._run_tiktok_auto_content_pipeline,
            "tiktok_content_generation_check": self._run_tiktok_content_generation_check,
            "tiktok_performance_sync": self._run_tiktok_performance_sync,
            "tiktok_pipeline_health": self._run_tiktok_pipeline_health,
            "tiktok_reference_discovery": self._run_tiktok_reference_discovery,
            "tiktok_weekly_report": self._run_tiktok_weekly_report,
            "tiktok_image_revalidation": self._run_tiktok_image_revalidation,
            "tiktok_article_cleanup": self._run_tiktok_article_cleanup,
            # Content Agent
            "content_performance_sync": self._run_content_performance_sync,
            "content_improvement_cycle": self._run_content_improvement_cycle,
            "content_trend_research": self._run_content_trend_research,
            # Prediction Market Intelligence
            "prediction_market_sync": self._run_prediction_market_sync,
            "prediction_price_snapshot": self._run_prediction_price_snapshot,
            "prediction_bettor_discovery": self._run_prediction_bettor_discovery,
            "prediction_research": self._run_prediction_research,
            "prediction_push_to_ada": self._run_prediction_push_to_ada,
            "prediction_quality_check": self._run_prediction_quality_check,
            # LLM Budget Reset
            "llm_budget_reset": self._run_llm_budget_reset,
            # Daily Autonomous Report
            "daily_autonomous_report": self._run_daily_autonomous_report,
            # AI Company
            "ai_company_deep_research": self._run_ai_company_deep_research,
            "ai_company_idea_validation": self._run_ai_company_idea_validation,
            "ai_company_daily_council": self._run_ai_company_daily_council,
            "ai_company_experiment_monitor": self._run_ai_company_experiment_monitor,
            # Character Content
            "character_research_refresh": self._run_character_research_refresh,
            "character_content_generation": self._run_character_content_generation,
            "character_performance_sync": self._run_character_performance_sync,
            "character_auto_publish": self._run_character_auto_publish,
            "character_content_learning": self._run_character_content_learning,
            "carousel_banned_hook_backfill": self._run_carousel_banned_hook_backfill,
            "character_reference_video_processor": self._run_character_reference_video_processor,
            "character_reference_video_cleanup": self._run_character_reference_video_cleanup,
            "character_image_cleanup": self._run_character_image_cleanup,
            # Phase 024: Character Autopilot
            "character_auto_approval": self._run_character_auto_approval,
            "character_publish_backlog": self._run_character_publish_backlog,
            "character_discovery": self._run_character_discovery,
            "character_gap_audit": self._run_character_gap_audit,
            "character_hook_audit": self._run_character_hook_audit,
            "character_discovery_refvideos": self._run_character_discovery_refvideos,
            "character_final_review_backfill": self._run_character_final_review_backfill,
            # Zero Brain
            "brain_benchmark": self._run_brain_benchmark,
            "brain_learning_cycle": self._run_brain_learning_cycle,
            "brain_content_learn": self._run_brain_content_learn,
            "brain_experiment_monitor": self._run_brain_experiment_monitor,
            "brain_prompt_evolve": self._run_brain_prompt_evolve,
            "brain_prompt_grade": self._run_brain_prompt_grade,
            "brain_episodic_extract": self._run_brain_episodic_extract,
            "brain_improvement": self._run_brain_improvement,
            "brain_reflection": self._run_brain_reflection,
            "brain_memory_cleanup": self._run_brain_memory_cleanup,
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
            lines.append(f"Total ideas: {stats.get('total_ideas', 0)}")
            lines.append(f"Ideas this week: {stats.get('ideas_this_week', 0)}")
            lines.append(f"Researched this week: {stats.get('researched_this_week', 0)}")
            lines.append(f"Top viability score: {stats.get('top_viability_score', 0):.1f}")
            lines.append(f"Average viability: {stats.get('avg_viability_score', 0):.1f}")

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

    async def _run_tiktok_niche_rotation(self):
        """Pick 3-5 random niches and run targeted research for deeper product discovery."""
        import random
        logger.info("running_tiktok_niche_rotation")
        try:
            from app.services.tiktok_shop_service import get_tiktok_shop_service, DEFAULT_NICHES
            from app.services.searxng_service import get_searxng_service
            svc = get_tiktok_shop_service()
            searxng = get_searxng_service()

            # Pick 3-5 random niches
            niches_to_research = random.sample(DEFAULT_NICHES, min(5, len(DEFAULT_NICHES)))
            year = datetime.now().year
            total_discovered = 0

            for niche in niches_to_research:
                try:
                    queries = [
                        f"best {niche} products for tiktok content {year}",
                        f"tiktok shop {niche} trending items this month",
                        f"dropshipping {niche} trending products {year}",
                    ]
                    all_results = []
                    for q in queries:
                        try:
                            results = await searxng.search(q, num_results=8)
                            all_results.extend(results)
                        except Exception:
                            continue

                    if all_results:
                        products = await svc._extract_products_from_articles(all_results)
                        for p in products:
                            try:
                                from app.models.tiktok_shop import TikTokProductCreate
                                create_data = TikTokProductCreate(
                                    name=p["name"],
                                    category=p.get("category", niche),
                                    niche=niche,
                                    why_trending=p.get("why_trending", ""),
                                    estimated_price_range=p.get("estimated_price_range", ""),
                                    is_extracted=True,
                                )
                                await svc.create_product(create_data)
                                total_discovered += 1
                            except Exception:
                                continue
                except Exception as e:
                    logger.warning("tiktok_niche_rotation_niche_failed", niche=niche, error=str(e))

            logger.info("tiktok_niche_rotation_complete",
                        niches=niches_to_research, discovered=total_discovered)
        except Exception as e:
            logger.error("tiktok_niche_rotation_failed", error=str(e))

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
            # Auto-retry stuck/failed items (max 3 retries)
            retried = 0
            if stats.failed > 0 or stuck > 0:
                from app.infrastructure.database import get_session
                from app.db.models import ContentQueueModel
                from sqlalchemy import select, or_
                async with get_session() as session:
                    result = await session.execute(
                        select(ContentQueueModel).where(
                            or_(
                                ContentQueueModel.status == "failed",
                                ContentQueueModel.status == "generating",
                            )
                        )
                    )
                    stuck_items = result.scalars().all()
                    for item in stuck_items:
                        retry_count = item.retry_count or 0
                        if retry_count < 3:
                            item.status = "queued"
                            item.error_message = None
                            item.retry_count = retry_count + 1
                            retried += 1
                        elif item.status != "failed":
                            item.status = "failed"
                            item.error_message = f"Auto-retry exhausted after 3 attempts. {item.error_message or ''}"
                    await session.flush()
                if retried > 0:
                    issues.append(f"{retried} items auto-retried")

            if issues:
                await self._send_to_discord(
                    "TikTok Pipeline Health Alert",
                    "Issues detected:\n" + "\n".join(f"- {i}" for i in issues),
                    color=0xED4245,
                )
            logger.info("tiktok_pipeline_health_check_complete", issues=len(issues), retried=retried)
        except Exception as e:
            logger.error("tiktok_pipeline_health_failed", error=str(e))

    async def _run_tiktok_reference_discovery(self):
        """Auto-discover reference videos from successful sellers for approved products."""
        logger.info("running_tiktok_reference_discovery")
        try:
            from app.services.reference_video_service import get_reference_video_service
            from app.services.tiktok_shop_service import get_tiktok_shop_service
            ref_service = get_reference_video_service()
            shop_service = get_tiktok_shop_service()

            # Find approved products without reference videos
            approved = await shop_service.list_products(status="approved", limit=10)
            total_discovered = 0
            for product in approved[:5]:
                try:
                    refs = await ref_service.auto_discover_references(product.id, max_refs=3)
                    total_discovered += len(refs)
                except Exception as e:
                    logger.warning("reference_discovery_product_failed",
                                   product_id=product.id, error=str(e))

            logger.info("tiktok_reference_discovery_complete", discovered=total_discovered)
        except Exception as e:
            logger.error("tiktok_reference_discovery_failed", error=str(e))

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

    async def _run_tiktok_image_revalidation(self):
        """Revalidate product images and re-fetch broken ones."""
        logger.info("running_tiktok_image_revalidation")
        try:
            from app.services.tiktok_shop_service import get_tiktok_shop_service
            svc = get_tiktok_shop_service()
            result = await svc.revalidate_images(limit=20)
            logger.info("tiktok_image_revalidation_complete",
                        checked=result.get("checked", 0),
                        valid=result.get("still_valid", 0),
                        refetched=result.get("refetched", 0))
        except Exception as e:
            logger.error("tiktok_image_revalidation_failed", error=str(e))

    async def _run_tiktok_article_cleanup(self):
        """Clean up products with article titles instead of product names."""
        logger.info("running_tiktok_article_cleanup")
        try:
            from app.services.tiktok_shop_service import get_tiktok_shop_service
            svc = get_tiktok_shop_service()
            result = await svc.cleanup_article_title_products()
            logger.info("tiktok_article_cleanup_complete",
                        rejected=result.get("rejected", 0),
                        kept=result.get("kept", 0))
        except Exception as e:
            logger.error("tiktok_article_cleanup_failed", error=str(e))

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

    async def _run_daily_autonomous_report(self):
        """Generate and deliver daily autonomous activity report."""
        logger.info("running_daily_autonomous_report")
        try:
            from app.services.daily_report_service import get_daily_report_service
            from app.services.notification_service import get_notification_service

            service = get_daily_report_service()
            report = await service.generate_daily_report()

            # Deliver to Discord
            message = service.format_discord_message(report)
            await self._send_to_discord(
                title=f"Daily Report — Grade: {report['grade']}/100",
                message=message,
                color=0x57F287 if report["grade"] >= 80 else (
                    0xFEE75C if report["grade"] >= 50 else 0xED4245
                ),
            )

            # Store as notification in DB
            notification_service = get_notification_service()
            await notification_service.create_notification(
                title=f"Daily Report — {report['grade']}/100",
                message=message,
                channel="discord",
                source="daily_report",
            )

            logger.info("daily_autonomous_report_sent", grade=report["grade"])
        except Exception as e:
            logger.error("daily_autonomous_report_failed", error=str(e))

    # ============================================
    # AI COMPANY HANDLERS
    # ============================================

    async def _run_ai_company_deep_research(self):
        """Run deep research on highest-priority queued topic."""
        logger.info("running_ai_company_deep_research")
        try:
            from app.services.deep_research_service import get_deep_research_service
            from app.models.agent_company import DeepResearchRequest
            svc = get_deep_research_service()

            # Check for pending reports to resume, or pick a topic from research findings
            pending = await svc.list_reports(status="pending", limit=1)
            if pending:
                logger.info("ai_company_deep_research_skipped", reason="pending report exists")
                return

            # Auto-generate a research topic from money maker or research service
            from app.services.research_service import get_research_service
            research_svc = get_research_service()
            topics = await research_svc.list_findings(limit=5)
            if topics:
                # Pick the most recent finding as a deep research seed
                topic = topics[0]
                query = f"Deep analysis: {topic.get('title', 'emerging trends')}"
                await svc.start_research(DeepResearchRequest(query=query))
                logger.info("ai_company_deep_research_started", query=query)
            else:
                logger.info("ai_company_deep_research_skipped", reason="no topics available")
        except Exception as e:
            logger.error("ai_company_deep_research_failed", error=str(e))

    async def _run_ai_company_idea_validation(self):
        """Deep-validate top-scoring unvalidated money-maker ideas."""
        logger.info("running_ai_company_idea_validation")
        try:
            from app.services.money_maker_service import get_money_maker_service
            from app.services.agent_company_service import get_agent_company_service
            mm = get_money_maker_service()
            company = get_agent_company_service()

            ideas = await mm.list_ideas(limit=5)
            validated = 0
            for idea in ideas:
                score = idea.get("viability_score", 0)
                if score > 60 and not idea.get("deep_validated"):
                    # CEO plans a validation task
                    await company.ceo_plan_and_delegate(
                        f"Deep-validate business idea: {idea.get('title', 'Untitled')}. "
                        f"Current viability score: {score}. "
                        f"Analyze market size, competition, feasibility, and provide Go/No-Go recommendation."
                    )
                    validated += 1
                    if validated >= 2:
                        break
            logger.info("ai_company_idea_validation_done", validated=validated)
        except Exception as e:
            logger.error("ai_company_idea_validation_failed", error=str(e))

    async def _run_ai_company_daily_council(self):
        """CEO proposes strategic decisions for council vote based on overnight findings."""
        logger.info("running_ai_company_daily_council")
        try:
            from app.services.council_service import get_council_service
            from app.services.deep_research_service import get_deep_research_service
            from app.models.agent_company import CouncilProposal

            council = get_council_service()
            research = get_deep_research_service()

            # Check for completed research that hasn't been reviewed
            reports = await research.list_reports(status="completed", limit=3)
            for report in reports:
                # Propose a council decision based on research findings
                topic = f"Strategic review: {report.query[:200]} — Should we act on these findings?"
                await council.propose(CouncilProposal(
                    topic=topic,
                    context={"research_id": report.id, "source": "daily_council_auto"}
                ))
                # Run the vote immediately
                decisions = await council.list_decisions(status="proposed", limit=1)
                if decisions:
                    await council.conduct_vote(decisions[0].id)
                break  # One decision per day
            logger.info("ai_company_daily_council_done")
        except Exception as e:
            logger.error("ai_company_daily_council_failed", error=str(e))

    async def _run_ai_company_experiment_monitor(self):
        """Check running experiments and flag stale ones."""
        logger.info("running_ai_company_experiment_monitor")
        try:
            from app.services.experiment_service import get_experiment_service
            from datetime import datetime, timedelta
            svc = get_experiment_service()

            running = await svc.list_experiments(status="running", limit=20)
            stale_count = 0
            for exp in running:
                started = exp.started_at
                if started and isinstance(started, str):
                    from dateutil.parser import parse
                    started = parse(started)
                if started and (datetime.utcnow() - started.replace(tzinfo=None)) > timedelta(hours=24):
                    # Flag as stale — mark failed with timeout note
                    logger.warning("experiment_stale", exp_id=exp.id, title=exp.title)
                    stale_count += 1
            logger.info("ai_company_experiment_monitor_done", running=len(running), stale=stale_count)
        except Exception as e:
            logger.error("ai_company_experiment_monitor_failed", error=str(e))

    # ============================================
    # CHARACTER CONTENT AUTOMATION
    # ============================================

    async def _run_character_research_refresh(self):
        """Re-research characters with stale data (>7 days)."""
        logger.info("running_character_research_refresh")
        try:
            from app.services.character_content_service import get_character_content_service
            from datetime import datetime, timedelta, timezone
            svc = get_character_content_service()

            characters = await svc.list_characters(research_status="completed", limit=50)
            refreshed = 0
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            for char in characters:
                if char.last_researched and char.last_researched < cutoff:
                    await svc.research_character(char.id)
                    refreshed += 1
                    if refreshed >= 3:
                        break
            logger.info("character_research_refresh_done", refreshed=refreshed)
        except Exception as e:
            logger.error("character_research_refresh_failed", error=str(e))

    async def _run_character_content_generation(self):
        """Auto-generate carousels for researched characters.

        Prioritizes by priority_tier (priority > standard > probation),
        rotates angles for variety, and generates up to 10 per run.
        """
        logger.info("running_character_content_generation")
        try:
            from app.services.character_content_service import get_character_content_service
            from app.models.character_content import CarouselCreate, ContentAngle
            import random
            svc = get_character_content_service()

            characters = await svc.list_characters(research_status="completed", limit=100)
            angles = list(ContentAngle)
            # Sort by priority_tier: priority first, then standard, then probation
            tier_order = {"priority": 0, "standard": 1, "probation": 2}
            characters.sort(key=lambda c: (tier_order.get(getattr(c, "priority_tier", "standard"), 1), c.posts_created))

            generated = 0
            failed = 0
            max_per_run = 10
            for char in characters:
                if generated >= max_per_run:
                    break
                # Rotate angle based on character index for variety
                angle = angles[(generated + hash(char.id)) % len(angles)]
                try:
                    await svc.generate_carousel(CarouselCreate(
                        character_id=char.id, angle=angle
                    ))
                    generated += 1
                    logger.info(
                        "character_carousel_generated",
                        character=char.name,
                        angle=angle.value if hasattr(angle, "value") else str(angle),
                    )
                except Exception as e:
                    failed += 1
                    logger.warning(
                        "character_carousel_generation_item_failed",
                        character=char.name,
                        error=str(e)[:200],
                    )
                    continue
            logger.info("character_content_generation_done", generated=generated, failed=failed)
        except Exception as e:
            logger.error("character_content_generation_failed", error=str(e))
            await self._alert_pipeline_failure("character_content_generation", e)

    async def _run_character_performance_sync(self):
        """Sync performance metrics from published character carousels."""
        logger.info("running_character_performance_sync")
        try:
            from app.services.character_content_service import get_character_content_service
            svc = get_character_content_service()
            stats = await svc.get_stats()
            logger.info("character_performance_sync_done",
                        characters=stats.total_characters,
                        carousels=stats.total_carousels,
                        published=stats.total_published)
        except Exception as e:
            logger.error("character_performance_sync_failed", error=str(e))

    async def _run_character_auto_publish(self):
        """Auto-publish approved carousels at optimal times."""
        logger.info("running_character_auto_publish")
        try:
            from app.services.character_content_service import get_character_content_service
            svc = get_character_content_service()
            # Find approved carousels with queued publish_status
            carousels = await svc.list_carousels(status="approved", limit=10)
            published = 0
            for carousel in carousels:
                if carousel.publish_status == "queued":
                    try:
                        await svc.publish_carousel(carousel.id)
                        published += 1
                    except (ValueError, OSError) as e:
                        logger.warning("auto_publish_failed", carousel_id=carousel.id, error=str(e))
            logger.info("character_auto_publish_done", published=published, checked=len(carousels))
        except Exception as e:
            logger.error("character_auto_publish_failed", error=str(e))

    async def _run_character_content_learning(self):
        """Process carousel outcomes and update template scores."""
        logger.info("running_character_content_learning")
        try:
            from app.services.content_learning_engine import get_content_learning_engine
            engine = get_content_learning_engine()
            await engine.process_content_outcomes()
            await engine.check_experiments()
            logger.info("character_content_learning_complete")
        except Exception as e:
            logger.error("character_content_learning_failed", error=str(e))

    async def _run_carousel_banned_hook_backfill(self):
        """Rewrite banned hook patterns on existing non-published carousels."""
        logger.info("running_carousel_banned_hook_backfill")
        try:
            from app.services.character_content_service import get_character_content_service
            from app.models.character_content import BackfillBannedHooksRequest
            svc = get_character_content_service()
            result = await svc.backfill_banned_hooks(
                BackfillBannedHooksRequest(limit=50, dry_run=False),
                created_by="scheduler",
            )
            logger.info(
                "carousel_banned_hook_backfill_done",
                scanned=result.scanned,
                flagged=result.flagged,
                rewritten=result.rewritten,
                errors=len(result.errors),
            )
        except Exception as e:
            logger.error("carousel_banned_hook_backfill_failed", error=str(e))

    async def _run_character_reference_video_processor(self):
        """Advance the reference-video state machine: download / transcribe / analyze."""
        try:
            from app.services.character_reference_video_service import (
                get_character_reference_video_service,
            )
            service = get_character_reference_video_service()
            processed = await service.process_pending(batch_size=5)
            if processed:
                logger.info("character_reference_video_processor_tick", processed=processed)
        except Exception as e:
            logger.error("character_reference_video_processor_failed", error=str(e))

    async def _run_character_reference_video_cleanup(self):
        """Purge stale reference video files (30+ days old)."""
        logger.info("running_character_reference_video_cleanup")
        try:
            from app.services.character_reference_video_service import (
                get_character_reference_video_service,
            )
            service = get_character_reference_video_service()
            removed = await service.cleanup_old_files(age_days=30)
            logger.info("character_reference_video_cleanup_complete", removed=removed)
        except Exception as e:
            logger.error("character_reference_video_cleanup_failed", error=str(e))

    async def _run_character_image_cleanup(self):
        """Auto-delete broken character image URLs and add them to per-character blocklist."""
        logger.info("running_character_image_cleanup")
        try:
            from app.services.character_content_service import get_character_content_service
            service = get_character_content_service()
            result = await service.purge_broken_images(limit=200)
            logger.info("character_image_cleanup_complete",
                         checked=result.get("total_checked", 0),
                         purged=result.get("purged", 0),
                         kept=result.get("kept", 0))
        except Exception as e:
            logger.error("character_image_cleanup_failed", error=str(e))

    # ============================================
    # PHASE 024: CHARACTER AUTOPILOT
    # ============================================

    def _autopilot_disabled(self, job_name: str) -> bool:
        """Check global autopilot kill-switch. Logs a skip when disabled."""
        try:
            from app.infrastructure.config import get_settings
            if not getattr(get_settings(), "character_autopilot_enabled", True):
                logger.warning("autopilot_disabled_skip", job=job_name)
                return True
        except Exception:
            return False
        return False

    async def _alert_pipeline_failure(self, job_name: str, error: Exception) -> None:
        """Send UI notification when a critical content pipeline job fails."""
        try:
            from app.services.notification_service import get_notification_service
            svc = get_notification_service()
            await svc.create_notification(
                title="Content Pipeline Alert",
                message=f"{job_name} failed: {str(error)[:200]}",
                source="scheduler",
                source_id=job_name,
            )
        except Exception:
            pass

    async def _run_character_auto_approval(self):
        """Auto-approve carousels with final_review_score >= threshold."""
        if self._autopilot_disabled("character_auto_approval"):
            return
        logger.info("running_character_auto_approval")
        try:
            from app.services.character_content_service import get_character_content_service
            svc = get_character_content_service()
            result = await svc.auto_approve_eligible(limit=20)
            logger.info("character_auto_approval_complete", **result)
        except Exception as e:
            logger.error("character_auto_approval_failed", error=str(e))
            await self._alert_pipeline_failure("character_auto_approval", e)

    async def _run_character_publish_backlog(self):
        """Ensure approved+queued backlog stays above target."""
        if self._autopilot_disabled("character_publish_backlog"):
            return
        logger.info("running_character_publish_backlog")
        try:
            from app.services.character_content_service import get_character_content_service
            svc = get_character_content_service()
            result = await svc.ensure_publish_backlog(target=6)
            logger.info("character_publish_backlog_complete", **result)
        except Exception as e:
            logger.error("character_publish_backlog_failed", error=str(e))
            await self._alert_pipeline_failure("character_publish_backlog", e)

    async def _run_character_final_review_backfill(self):
        """Backfill Stage 2 final review on high-score carousels that missed it.

        Finds carousels where ai_review.overall_score >= 7 AND final_review_score
        IS NULL, then runs `_final_review_carousel` on each. Batches to 10 per
        run to respect LLM budgets. Any single-carousel failure is logged but
        does not stop the batch.
        """
        if self._autopilot_disabled("character_final_review_backfill"):
            return
        logger.info("running_character_final_review_backfill")
        try:
            import asyncio
            import aiohttp
            from sqlalchemy import select, Float
            from sqlalchemy.exc import SQLAlchemyError
            from app.db.models import CharacterCarouselModel
            from app.infrastructure.database import get_session
            from app.services.character_content_service import get_character_content_service

            svc = get_character_content_service()
            batch_limit = 10
            async with get_session() as session:
                # ai_review is JSONB; use the ->> text operator then cast for numeric compare.
                result = await session.execute(
                    select(
                        CharacterCarouselModel.id,
                        CharacterCarouselModel.ai_review,
                    )
                    .where(CharacterCarouselModel.final_review_score.is_(None))
                    .where(CharacterCarouselModel.ai_review.isnot(None))
                    .where(
                        CharacterCarouselModel.ai_review["overall_score"].astext.cast(Float) >= 7.0
                    )
                    .order_by(CharacterCarouselModel.created_at.desc())
                    .limit(batch_limit)
                )
                rows = result.all()

            processed = 0
            failed = 0
            for carousel_id, ai_review in rows:
                try:
                    await svc._final_review_carousel(carousel_id, ai_review or {})
                    processed += 1
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                    failed += 1
                    logger.warning(
                        "character_final_review_backfill_item_failed",
                        carousel_id=carousel_id,
                        error=str(e),
                    )

            logger.info(
                "character_final_review_backfill_complete",
                candidates=len(rows),
                processed=processed,
                failed=failed,
            )
        except Exception as e:
            logger.error("character_final_review_backfill_failed", error=str(e))
            await self._alert_pipeline_failure("character_final_review_backfill", e)

    async def _run_character_discovery(self):
        """Autonomous character discovery from 4 free sources."""
        if self._autopilot_disabled("character_discovery"):
            return
        logger.info("running_character_discovery")
        try:
            from app.infrastructure.config import get_settings
            if not getattr(get_settings(), "character_discovery_enabled", True):
                logger.info("character_discovery_skipped_flag")
                return
            from app.services.character_discovery_service import get_character_discovery_service
            svc = get_character_discovery_service()
            result = await svc.run_all_sources()
            logger.info("character_discovery_complete", **result)
        except Exception as e:
            logger.error("character_discovery_failed", error=str(e))

    async def _run_character_gap_audit(self):
        """Audit characters for image/angle/fact/hook gaps, enqueue fill work."""
        if self._autopilot_disabled("character_gap_audit"):
            return
        logger.info("running_character_gap_audit")
        try:
            from app.services.character_content_service import get_character_content_service
            svc = get_character_content_service()
            result = await svc.run_gap_audit_cycle(max_characters=20)
            logger.info("character_gap_audit_complete", **result)
        except Exception as e:
            logger.error("character_gap_audit_failed", error=str(e))

    async def _run_character_hook_audit(self):
        """Score + regenerate weak hooks across draft/review carousels."""
        if self._autopilot_disabled("character_hook_audit"):
            return
        logger.info("running_character_hook_audit")
        try:
            from app.services.character_hook_service import get_character_hook_service
            svc = get_character_hook_service()
            result = await svc.audit_weak_hooks(threshold=6.0, limit=20)
            logger.info("character_hook_audit_complete", **result)
        except Exception as e:
            logger.error("character_hook_audit_failed", error=str(e))

    async def _run_character_discovery_refvideos(self):
        """Promote proposed characters from analyzed TikTok reference videos."""
        if self._autopilot_disabled("character_discovery_refvideos"):
            return
        try:
            from app.services.character_discovery_service import get_character_discovery_service
            svc = get_character_discovery_service()
            result = await svc.discover_from_reference_videos(limit=5)
            if result.get("created", 0) > 0:
                logger.info("character_discovery_refvideos_tick", **result)
        except Exception as e:
            logger.error("character_discovery_refvideos_failed", error=str(e))

    # ============================================
    # ZERO BRAIN HANDLERS
    # ============================================

    async def _run_brain_benchmark(self):
        logger.info("running_brain_benchmark")
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            svc = get_zero_brain_service()
            result = await svc.run_benchmark()
            logger.info("brain_benchmark_complete", overall_score=result.overall_score)
        except Exception as e:
            logger.error("brain_benchmark_failed", error=str(e))

    async def _run_brain_learning_cycle(self):
        logger.info("running_brain_learning_cycle")
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            svc = get_zero_brain_service()
            result = await svc.run_learning_cycle()
            logger.info("brain_learning_cycle_complete", status=result.status)
        except Exception as e:
            logger.error("brain_learning_cycle_failed", error=str(e))

    async def _run_brain_content_learn(self):
        logger.info("running_brain_content_learn")
        try:
            from app.services.content_learning_engine import get_content_learning_engine
            svc = get_content_learning_engine()
            result = await svc.process_content_outcomes()
            logger.info("brain_content_learn_complete", processed=result.get("processed", 0))
        except Exception as e:
            logger.error("brain_content_learn_failed", error=str(e))

    async def _run_brain_experiment_monitor(self):
        logger.info("running_brain_experiment_monitor")
        try:
            from app.services.content_learning_engine import get_content_learning_engine
            svc = get_content_learning_engine()
            completed = await svc.check_experiments()
            logger.info("brain_experiment_monitor_complete", completed=len(completed))
        except Exception as e:
            logger.error("brain_experiment_monitor_failed", error=str(e))

    async def _run_brain_prompt_evolve(self):
        logger.info("running_brain_prompt_evolve")
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            svc = get_zero_brain_service()
            result = await svc.run_prompt_evolution()
            logger.info("brain_prompt_evolve_complete", evolved=len(result.get("evolved", [])))
        except Exception as e:
            logger.error("brain_prompt_evolve_failed", error=str(e))

    async def _run_brain_prompt_grade(self):
        logger.info("running_brain_prompt_grade")
        try:
            from app.services.prompt_grader_service import get_prompt_grader_service
            svc = get_prompt_grader_service()
            result = await svc.grade_pending(limit=20)
            logger.info(
                "brain_prompt_grade_complete",
                graded=result.get("graded", 0),
                failed=result.get("failed", 0),
            )
        except Exception as e:
            logger.error("brain_prompt_grade_failed", error=str(e))

    async def _run_brain_episodic_extract(self):
        logger.info("running_brain_episodic_extract")
        try:
            from app.services.episodic_memory_service import get_episodic_memory_service
            from app.db.models import LlmUsageModel
            from sqlalchemy import select
            from datetime import timedelta

            # Extract memories from recent LLM interactions
            svc = get_episodic_memory_service()
            since = datetime.now() - timedelta(minutes=35)
            async with get_session() as session:
                query = (
                    select(LlmUsageModel)
                    .where(LlmUsageModel.created_at >= since)
                    .where(LlmUsageModel.success == True)
                    .order_by(LlmUsageModel.created_at.desc())
                    .limit(20)
                )
                result = await session.execute(query)
                recent = result.scalars().all()

            extracted = 0
            for usage in recent:
                if usage.task_type and usage.response_preview:
                    await svc.extract_and_store(
                        text=f"Task: {usage.task_type}. Response: {usage.response_preview[:500]}",
                        source_type="llm_interaction",
                        source_id=usage.id,
                        namespace="general",
                    )
                    extracted += 1

            logger.info("brain_episodic_extract_complete", extracted=extracted)
        except Exception as e:
            logger.error("brain_episodic_extract_failed", error=str(e))

    async def _run_brain_improvement(self):
        logger.info("running_brain_improvement")
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            svc = get_zero_brain_service()
            result = await svc.run_improvement()
            logger.info("brain_improvement_complete",
                       target=result.get("target_dimension"),
                       score=result.get("current_score"))
        except Exception as e:
            logger.error("brain_improvement_failed", error=str(e))

    async def _run_brain_reflection(self):
        logger.info("running_brain_reflection")
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            svc = get_zero_brain_service()
            result = await svc.run_reflection()
            logger.info("brain_reflection_complete",
                       learnings=len(result.get("learnings", [])))
        except Exception as e:
            logger.error("brain_reflection_failed", error=str(e))

    async def _run_brain_memory_cleanup(self):
        logger.info("running_brain_memory_cleanup")
        try:
            from app.services.episodic_memory_service import get_episodic_memory_service
            svc = get_episodic_memory_service()
            deleted = await svc.cleanup_expired()
            logger.info("brain_memory_cleanup_complete", deleted=deleted)
        except Exception as e:
            logger.error("brain_memory_cleanup_failed", error=str(e))

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
