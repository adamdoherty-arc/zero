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
All job executions are logged to an audit file for observability.
"""
import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from functools import lru_cache
import structlog

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

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
}


# ============================================
# SCHEDULER SERVICE
# ============================================

class SchedulerService:
    """
    Manages scheduled automation tasks for Zero.

    Uses APScheduler for reliable cron-based execution.
    All job executions are logged to workspace/scheduler/audit_log.json.
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._jobs: Dict[str, str] = {}  # job_name -> job_id

        # Audit log
        self._audit_path = Path("workspace/scheduler")
        self._audit_path.mkdir(parents=True, exist_ok=True)
        self._audit_file = self._audit_path / "audit_log.json"
        if not self._audit_file.exists():
            self._audit_file.write_text(json.dumps({"executions": []}, indent=2))

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
            entry = {
                "job_name": job_name,
                "started_at": started.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
                "status": status,
                "duration_seconds": duration,
                "error": error_msg,
            }
            self._append_audit(entry)
            logger.info("job_audit", job=job_name, status=status, duration=duration)

    def _append_audit(self, entry: Dict[str, Any]):
        """Append an execution record to the audit log (keep last 500)."""
        try:
            data = json.loads(self._audit_file.read_text())
            data["executions"].append(entry)
            data["executions"] = data["executions"][-500:]
            self._audit_file.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.error("audit_log_write_failed", error=str(e))

    def get_audit_log(self, limit: int = 50) -> Dict[str, Any]:
        """Return recent audit log entries."""
        try:
            data = json.loads(self._audit_file.read_text())
            executions = data.get("executions", [])
            return {"executions": executions[-limit:], "total": len(executions)}
        except Exception:
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
        }
        return handlers.get(job_name)

    # ============================================
    # JOB HANDLERS
    # ============================================

    async def _run_morning_briefing(self):
        """
        Morning briefing automation.

        1. Generate comprehensive briefing with Legion data
        2. Send via WhatsApp/Discord
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

            # Send via notification service
            notification_service = get_notification_service()
            await notification_service.create_notification(
                title="Morning Briefing",
                message=message,
                channel="discord",  # Primary channel
                source="scheduler"
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

            notification_service = get_notification_service()
            await notification_service.create_notification(
                title="Weekly Money Maker Report",
                message="\n".join(lines),
                channel="discord",
                source="money_maker"
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

            if not gmail.is_connected():
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

            if not gmail.is_connected():
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

            notification_service = get_notification_service()
            await notification_service.create_notification(
                title="Daily Email Digest",
                message="\n".join(lines),
                channel="discord",
                source="scheduler"
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
            if not gmail.is_connected():
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
    # UTILITIES
    # ============================================

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
