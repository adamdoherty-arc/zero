"""
Daily Automation Scheduler Service for ZERO.

Handles scheduled automation tasks including:
- Morning briefing generation and delivery
- Midday health checks
- Evening review and sprint updates
- Enhancement scans
- Notification routing

Uses APScheduler for cron-based scheduling.
All job executions are logged to PostgreSQL (scheduler_audit_log) for observability.
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Callable
from functools import lru_cache
import structlog

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, func as sa_func, case

from app.infrastructure.database import get_session
from app.db.models import SchedulerAuditLogModel, ServiceConfigModel

logger = structlog.get_logger(__name__)


SCHEDULER_CONFIG_KEY = "scheduler_jobs"
SCHEDULER_OVERRIDES_KEY = "enabled_overrides"
DEFAULT_DISABLED_JOB_IDS = {"reachy_email_nudge"}
DEFAULT_DISABLED_PREFIXES = ("tiktok_",)


JOB_CATEGORIES = {
    "Briefing": ["morning_briefing", "midday_check", "evening_review", "morning_digest_tick", "weekly_review_tick"],
    "Email": ["gmail_check", "gmail_digest", "reachy_email_nudge", "email_automation_check", "email_to_tasks"],
    "Calendar": ["calendar_check", "meeting_prep", "reachy_calendar_nudge", "reachy_meeting_auto_record", "reachy_meeting_auto_stop"],
    "TikTok": [
        "tiktok_shop_research",
        "tiktok_shop_deep_research",
        "tiktok_continuous_research",
        "tiktok_niche_deep_dive",
        "tiktok_niche_rotation",
        "tiktok_approval_reminder",
        "tiktok_auto_content_pipeline",
        "tiktok_content_generation_check",
        "tiktok_performance_sync",
        "tiktok_pipeline_health",
        "tiktok_reference_discovery",
        "tiktok_weekly_report",
        "tiktok_image_revalidation",
        "tiktok_article_cleanup",
    ],
    "Meals": [
        "meal_catalog_refresh",
        "meal_promo_hunt",
        "meal_shipment_scan",
        "meal_discovery",
        "meal_daily_digest",
        "meal_signup_sweep",
        "meal_vision_sweep",
    ],
    "Predictions": [
        "prediction_market_sync",
        "prediction_price_snapshot",
        "prediction_bettor_discovery",
        "prediction_research",
        "prediction_push_to_ada",
        "prediction_quality_check",
    ],
    "Autonomous": [
        "autonomous_daily_orchestration",
        "autonomous_continuous_monitor",
        "autonomous_enhancement_cycle",
        "autonomous_research_tick",
        "autonomous_content_loop",
    ],
    "Enhancement": [
        "continuous_enhancement_engine",
        "daily_improvement_plan",
        "daily_improvement_execute",
        "daily_improvement_verify",
        "enhancement_scan",
        "legion_enhancement_sync",
    ],
    "Monitoring": [
        "health_aggregation",
        "qa_verification",
        "disk_space_monitor",
        "embedding_backfill",
        "alerting_check",
        "metrics_snapshot",
        "approvals_expire_stale",
        "drift_scan_tick",
    ],
    "Tasks": ["task_worker", "task_progress_check", "blocked_task_escalation", "smart_suggestions", "reminder_check"],
    "Research": ["research_daily", "research_weekly_deep_dive", "rules_recalibration"],
    "Second Brain": ["vault_reindex_tick", "vault_task_sync_tick", "morning_digest_tick", "weekly_review_tick", "drift_scan_tick"],
    "Loops": ["loop_tick_5min", "loop_judge_15min", "loop_promote_hourly", "loop_crosspoll_30m", "loop_health_5min"],
    "Company": [
        "company_operator_monitor",
        "company_agent_work",
        "company_operator_overnight",
        "company_operator_morning_brief",
        "company_operator_evening_report",
        "company_operator_weekly_review",
        "company_prompt_eval_bridge",
    ],
    "Character Content": [
        "character_research_refresh",
        "character_research_retry",
        "character_content_generation",
        "character_content_gate",
        "carousel_watchdog",
        "character_performance_sync",
        "character_auto_publish",
        "character_content_learning",
        "carousel_banned_hook_backfill",
        "carousel_morning_briefing",
        "carousel_evening_recap",
        "character_reference_video_processor",
        "character_reference_video_learning",
        "character_reference_video_cleanup",
        "carousel_reaudit",
        "entity_research_deepen",
        "character_image_cleanup",
        "character_auto_approval",
        "character_publish_backlog",
        "character_discovery",
        "character_gap_audit",
        "character_hook_audit",
        "character_discovery_refvideos",
        "character_auto_research",
        "character_final_review_backfill",
    ],
    "Media Content": ["media_auto_research", "media_content_generation", "media_release_prep"],
    "Trend Intelligence": [
        "trend_release_calendar_sync",
        "trend_tvmaze_schedule",
        "trend_reddit_pulse",
        "trend_searxng_pulse",
        "trend_linker",
        "trend_scorer",
        "trend_signal_cleanup",
        "character_release_prep",
        "media_release_prep",
    ],
    "Zero Brain": [
        "brain_benchmark",
        "brain_learning_cycle",
        "brain_content_learn",
        "brain_experiment_monitor",
        "brain_prompt_evolve",
        "brain_prompt_grade",
        "brain_episodic_extract",
        "brain_improvement",
        "brain_reflection",
        "brain_memory_cleanup",
        "brain_prompt_breed",
        "competitor_scrape",
        "competitor_cleanup",
        "character_hook_style_report",
    ],
    "Resources": ["gpu_refresh", "notion_bidirectional_sync", "llm_budget_reset"],
    "Revenue": ["money_maker_cycle", "money_maker_weekly_report", "ai_company_idea_validation", "ai_company_daily_council", "ai_company_experiment_monitor"],
}

JOB_CATEGORY_PREFIXES = (
    ("tiktok_", "TikTok"),
    ("meal_", "Meals"),
    ("prediction_", "Predictions"),
    ("company_", "Company"),
    ("character_", "Character Content"),
    ("carousel_", "Character Content"),
    ("media_", "Media Content"),
    ("trend_", "Trend Intelligence"),
    ("brain_", "Zero Brain"),
    ("reachy_", "Reachy"),
    ("vault_", "Second Brain"),
    ("ai_company_", "Revenue"),
    ("autonomous_", "Autonomous"),
)


def get_job_category(job_name: str) -> str:
    for category, jobs in JOB_CATEGORIES.items():
        if job_name in jobs:
            return category
    for prefix, category in JOB_CATEGORY_PREFIXES:
        if job_name.startswith(prefix):
            return category
    return "Other"


def get_default_job_enabled(job_name: str, config: Optional[Dict[str, Any]] = None) -> bool:
    if job_name in DEFAULT_DISABLED_JOB_IDS:
        return False
    if any(job_name.startswith(prefix) for prefix in DEFAULT_DISABLED_PREFIXES):
        return False
    cfg = config if config is not None else DAILY_SCHEDULE.get(job_name, {})
    return bool(cfg.get("enabled", True))


def _is_account_quiet_now(account: dict) -> bool:
    """True if `account` is currently inside its configured quiet-hours window.

    quiet_hours shape: {enabled, start: "HH:MM", end: "HH:MM", weekdays_only}
    Empty / disabled = always announce. Wraps midnight when start > end.
    """
    qh = account.get("quiet_hours") or {}
    if not qh.get("enabled"):
        return False
    now = datetime.now()
    if qh.get("weekdays_only") and now.weekday() >= 5:
        return False  # weekends are not quiet when "weekdays_only" is set
    try:
        sh, sm = (int(p) for p in str(qh.get("start", "22:00")).split(":"))
        eh, em = (int(p) for p in str(qh.get("end", "07:00")).split(":"))
    except Exception:
        return False
    cur = (now.hour, now.minute)
    s = (sh, sm)
    e = (eh, em)
    if s <= e:
        return s <= cur < e
    # Window wraps midnight (e.g. 22:00 -> 07:00)
    return cur >= s or cur < e


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
    "calendar_check": {
        "cron": "*/10 * * * *",  # Every 10 minutes
        "description": "Sync calendar events across all connected accounts",
        "enabled": True
    },
    "reachy_calendar_nudge": {
        "cron": "* * * * *",  # Every minute
        "description": "Speak an upcoming-event warning through Reachy at 10/5/1 minute marks",
        "enabled": True
    },
    "reachy_email_nudge": {
        "cron": "*/5 * * * *",  # Every 5 minutes — aligned with gmail_check incremental sync
        "description": "Per-email voice triage: announce new arrivals through Reachy and drive read/ignore/delete/respond loop",
        "enabled": True
    },
    "reachy_meeting_auto_record": {
        "cron": "* * * * *",  # Every minute
        "description": "Auto-start a recording when a flagged calendar event begins",
        "enabled": True
    },
    "reachy_meeting_auto_stop": {
        "cron": "* * * * *",  # Every minute
        "description": "Auto-stop a recording when its calendar event ends",
        "enabled": True
    },
    "reachy_morning_briefing": {
        "cron": "0 8 * * *",  # 8:00 AM daily
        "description": "Speak the day's calendar + top tasks + inbox load through Reachy in the narrator persona",
        "enabled": True
    },
    "reachy_evening_journal": {
        "cron": "0 18 * * *",  # 6:00 PM daily
        "description": "Wellness persona prompts a 3-question end-of-day reflection through Reachy and writes it to the vault",
        "enabled": True
    },
    "reachy_ambient_heartbeat": {
        "cron": "*/2 * * * *",  # Every 2 minutes — frequent enough to feel alive without being annoying
        "description": "In ambient mode and only when idle, play a small low-key emotion (attentive/curious/thoughtful) so Reachy doesn't sit perfectly still",
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
    "research_daily": {
        "cron": "0 11 * * *",  # 11:00 AM daily
        "description": "Daily research cycle - scan topics and discover new findings",
        "enabled": False
    },
    "research_weekly_deep_dive": {
        "cron": "0 10 * * 6",  # Saturday 10:00 AM
        "description": "Weekly deep dive research with expanded search and trend report",
        "enabled": False
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
    # Disabled 2026-04-27: project migrated off Ollama to vLLM. The service
    # still polls Ollama's /api/ps and /api/tags, which now always fail.
    # Re-enable only after porting GpuManagerService to vLLM /metrics or nvidia-smi.
    "gpu_refresh": {
        "cron": "*/5 * * * *",
        "description": "Refresh GPU/Ollama resource status (loaded models, VRAM)",
        "enabled": False
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
    # Meal Manager
    "meal_catalog_refresh": {
        "cron": "0 6 * * *",  # 6:00 AM daily
        "description": "Refresh menu pages + pricing for every tracked meal service",
        "enabled": True
    },
    "meal_promo_hunt": {
        "cron": "0 */4 * * *",  # Every 4 hours
        "description": "Hunt fresh promo codes + portal cashback for tracked meal services",
        "enabled": True
    },
    "meal_shipment_scan": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Scan Gmail cache for meal shipment notifications + Chase/Amex offer emails",
        "enabled": True
    },
    "meal_discovery": {
        "cron": "0 11 * * 0",  # Sunday 11:00 AM
        "description": "Weekly discovery — search for new meal delivery services to track",
        "enabled": True
    },
    "meal_daily_digest": {
        "cron": "30 7 * * *",  # 7:30 AM daily
        "description": "Write daily meal digest to vault (cheapest, in-transit, hot promos)",
        "enabled": True
    },
    "meal_signup_sweep": {
        "cron": "0 3 * * 6",  # Saturday 3:00 AM
        "description": "Playwright-sign-up meal services + parse welcome-email codes from Gmail cache",
        "enabled": True
    },
    "meal_vision_sweep": {
        "cron": "0 4 * * 0",  # Sunday 4:00 AM
        "description": "Vision-LLM screenshot sweep across meal-service homepages (env-gated)",
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
        "enabled": False
    },
    # Autonomous Research Loop — 24/7 driver with concurrency + budget gates
    "autonomous_research_tick": {
        "cron": "*/15 * * * *",  # Every 15 minutes
        "description": "Drives continuous background research; picks eligible topic, dispatches deep research, writes results into the Obsidian vault",
        "enabled": False
    },
    # Ambient vision loop — Phase 5 of the Meta-glasses / Reachy-camera plan.
    # Pulls a frame from the active SightProvider, runs VLM, writes notable
    # observations to /vault/00_Meta/_agent/vision/. Skips when idle.
    "ambient_vision_tick": {
        "cron": "*/1 * * * *",  # every minute; the tick itself skips if <60s frame staleness, etc.
        "description": "Ambient vision — capture a frame from the active sight provider, VLM-describe it, log to vault, surface actionable events",
        "enabled": True
    },
    # Vault indexer — SecondBrain Phase 2
    "vault_reindex_tick": {
        "cron": "*/2 * * * *",  # Every 2 minutes
        "description": "Walk the Obsidian vault for changed markdown files, re-chunk and re-embed into vault_chunks",
        "enabled": True
    },
    # Vault task sync — SecondBrain Phase 3
    "vault_task_sync_tick": {
        "cron": "*/3 * * * *",  # Every 3 minutes
        "description": "Scan daily notes for checkbox tasks and bi-directionally sync with TaskModel",
        "enabled": True
    },
    "approvals_expire_stale": {
        "cron": "7 * * * *",  # Hourly at :07
        "description": "Mark pending approvals past their expiry as expired",
        "enabled": True
    },
    # SecondBrain Phase 4 — morning digest + weekly review + drift scan
    "morning_digest_tick": {
        "cron": "30 6 * * *",  # 6:30 AM daily
        "description": "Aggregate overnight events into a 7-section digest written into today's daily note",
        "enabled": True
    },
    "weekly_review_tick": {
        "cron": "0 17 * * 5",  # 5:00 PM Friday
        "description": "Emit weekly review markdown (reviews/YYYY-Www.md); drives Get Clear / Get Current / Get Creative",
        "enabled": True
    },
    "drift_scan_tick": {
        "cron": "15 2 * * *",  # 2:15 AM daily
        "description": "Run the 6 drift SQL rules (idle project, calendar-vs-actual, commit decay, intent drift, inbox bloat, trading skip); write agent_alerts",
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
    # Zero Company Operator: ADA AI LLC 24/7 company manager
    "company_operator_monitor": {
        "cron": "*/15 * * * *",
        "description": "Company Operator heartbeat only: blockers, approvals, and next steps snapshot",
        "enabled": True,
    },
    "company_agent_work": {
        "cron": "*/15 * * * *",
        "description": "Company Agent Work loop: execute bounded internal/staged work and create Adam questions",
        "enabled": True,
    },
    "company_operator_overnight": {
        "cron": "0 1 * * *",
        "description": "Company Operator overnight internal work block with approval gates",
        "enabled": True,
    },
    "company_operator_morning_brief": {
        "cron": "45 6 * * *",
        "description": "Company Operator morning brief: today, blockers, approvals, formation status",
        "enabled": True,
    },
    "company_operator_evening_report": {
        "cron": "30 20 * * *",
        "description": "Company Operator evening report: progress, stuck work, next approvals",
        "enabled": True,
    },
    "company_operator_weekly_review": {
        "cron": "30 16 * * 5",
        "description": "Company Operator weekly company review",
        "enabled": True,
    },
    "company_prompt_eval_bridge": {
        "cron": "15 2 * * *",
        "description": "Legion/Zero company prompt evaluation bridge",
        "enabled": True,
    },
    # Character Content
    "character_research_refresh": {
        "cron": "0 3 * * *",  # 3:00 AM daily
        "description": "Re-research characters with stale data (>7 days old)",
        "enabled": True
    },
    "character_research_retry": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "Drain pending/needs_retry research backlog (does not touch completed characters)",
        "enabled": True,
    },
    "character_content_generation": {
        "cron": "0 * * * *",  # Every 1 hour - Phase 4.1 throughput bump
        "description": "Auto-generate carousels for researched characters, priority-tier ordered",
        "enabled": True
    },
    "character_content_gate": {
        "cron": "*/15 * * * *",  # Every 15 minutes
        "description": "Demand-driven generation: fires extra carousels when approved backlog is low",
        "enabled": True
    },
    "carousel_watchdog": {
        "cron": "*/10 * * * *",  # Every 10 minutes
        "description": "Detect stuck carousel pipeline jobs and alert when cadence is missed",
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
    "carousel_morning_briefing": {
        "cron": "0 8 * * *",  # 8:00 AM daily
        "description": "Zero's morning check-in: last 12h carousel stats, top variants, issues, wins",
        "enabled": True,
    },
    "carousel_evening_recap": {
        "cron": "0 20 * * *",  # 8:00 PM daily
        "description": "Zero's evening recap: last 12h carousel stats, top variants, issues, wins",
        "enabled": True,
    },
    "character_reference_video_processor": {
        "cron": "* * * * *",  # Every 1 minute
        "description": "Download / transcribe / analyze newly ingested TikTok reference videos",
        "enabled": True
    },
    "character_reference_video_learning": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Auto-apply high-surprise facts + style exemplars from analyzed reference videos",
        "enabled": True,
    },
    "carousel_reaudit": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "Re-audit published/approved carousels and auto-fix bad images / duplicate text",
        "enabled": True,
    },
    "entity_research_deepen": {
        "cron": "0 2 * * *",  # 2:00 AM daily
        "description": "Run deep research on the lowest-depth characters/shows/movies",
        "enabled": True,
    },
    "employee_checkin": {
        "cron": "0 8 * * *",  # 8:00 AM daily
        "description": "Aggregate subsystem reports into an EmployeeCheckin and file regression tasks",
        "enabled": True,
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
    "character_auto_research": {
        "cron": "0 */2 * * *",  # Every 2 hours
        "description": "Auto-start research for pending characters if queue is idle",
        "enabled": True
    },
    "character_final_review_backfill": {
        "cron": "*/20 * * * *",  # Every 20 minutes
        "description": "Run Stage 2 final review on carousels with ai_review_score >= 7 AND final_review_score IS NULL",
        "enabled": True
    },
    # Media content automation (TV shows + movies)
    "media_auto_research": {
        "cron": "*/2 * * * *",  # Every 2 minutes — keep the queue flowing
        "description": "Auto-research pending TV/movie titles (up to 6 per run, ~180/hr throughput)",
        "enabled": True
    },
    "media_content_generation": {
        "cron": "30 */4 * * *",  # Every 4 hours at :30 past (offset from character_content_generation at :00)
        "description": "Auto-generate carousels for researched TV/movie titles, prioritizes underserved titles",
        "enabled": True
    },
    # Trend Intelligence (release-aware + viral pulse)
    "trend_release_calendar_sync": {
        "cron": "15 */6 * * *",  # Every 6 hours
        "description": "Pull TMDB upcoming movies + on_the_air TV into trending_signals",
        "enabled": True
    },
    "trend_tvmaze_schedule": {
        "cron": "45 */6 * * *",  # Every 6 hours offset
        "description": "Pull TVMaze 14-day schedule into trending_signals",
        "enabled": True
    },
    "trend_reddit_pulse": {
        "cron": "20 */2 * * *",  # Every 2 hours
        "description": "Pull r/movies + r/television rising posts",
        "enabled": True
    },
    "trend_searxng_pulse": {
        "cron": "50 */4 * * *",  # Every 4 hours
        "description": "SearXNG trend queries for viral / upcoming pulse",
        "enabled": True
    },
    "trend_linker": {
        "cron": "10 */2 * * *",  # Every 2 hours
        "description": "Link unprocessed trending_signals to characters + media_titles",
        "enabled": True
    },
    "trend_scorer": {
        "cron": "40 */3 * * *",  # Every 3 hours
        "description": "Kimi scores unscored viral/pulse signals",
        "enabled": True
    },
    "trend_signal_cleanup": {
        "cron": "15 3 * * *",  # Daily 3:15 AM
        "description": "Remove expired trending_signals (>30 day decay)",
        "enabled": True
    },
    "character_release_prep": {
        "cron": "0 5 * * *",  # Daily 5 AM
        "description": "Queue 3-carousel burst for characters linked to signals with release_date in next 14d",
        "enabled": True
    },
    "media_release_prep": {
        "cron": "15 5 * * *",  # Daily 5:15 AM
        "description": "Queue carousel generation for media_titles linked to signals with release_date in next 14d",
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
    # Content Brain v2 learning accelerators
    "brain_prompt_breed": {
        "cron": "30 2 * * *",  # Daily at 2:30 AM
        "description": "Prompt breeder: mutate top-3 variants, retire bottom-3",
        "enabled": True
    },
    "competitor_scrape": {
        "cron": "0 */12 * * *",  # Every 12 hours
        "description": "Scrape winning TikTok/YouTube/IG public hooks for active niches",
        "enabled": True
    },
    "competitor_cleanup": {
        "cron": "30 3 * * *",  # Daily at 3:30 AM
        "description": "Remove expired competitor_content_samples (>30 day decay)",
        "enabled": True
    },
    "character_hook_style_report": {
        "cron": "0 4 * * 0",  # Weekly Sunday 4 AM
        "description": "Compute per-hook-style engagement lift, store as episodic memory",
        "enabled": True
    },
    # Orchestration hardening (migration 035)
    "autonomous_content_loop": {
        "cron": "*/30 * * * *",  # Every 30 minutes
        "description": "Drive carousel generation off unprocessed TrendingSignalModel rows (gated by ZERO_AUTONOMOUS_CONTENT_ENABLED)",
        "enabled": True
    },
    "swarm_calibration": {
        "cron": "0 3 * * 0",  # Sunday 03:00
        "description": "Recompute swarm role weights from 30d of prediction outcomes (Brier + rank correlation)",
        "enabled": True
    },
    "lore_ingestion": {
        "cron": "0 2 * * *",  # Daily 02:00
        "description": "Chunk + embed CharacterModel.research_data into character_lore_chunks for retrieval",
        "enabled": True
    },
    "carousel_partition_maintenance": {
        "cron": "0 1 25 * *",  # 25th of each month at 01:00 (well before month rollover)
        "description": "Create next-month partitions for character_carousels (native Postgres partitioning)",
        "enabled": True
    },
    # ====== Cross-project self-improvement loops (autoresearch) ======
    "loop_tick_5min": {
        "cron": "*/5 * * * *",
        "description": "Cross-project loops: pick next-due loop and dispatch (Zero is orchestrator)",
        "enabled": True,
    },
    "loop_judge_15min": {
        "cron": "*/15 * * * *",
        "description": "Cross-project loops: score recent runs via local Qwen judge",
        "enabled": True,
    },
    "loop_promote_hourly": {
        "cron": "0 * * * *",
        "description": "Cross-project loops: canary -> active promotion (autoresearch policy)",
        "enabled": True,
    },
    "loop_crosspoll_30m": {
        "cron": "*/30 * * * *",
        "description": "Cross-project loops: fanout learnings ADA <-> Legion <-> Zero",
        "enabled": True,
    },
    "loop_health_5min": {
        "cron": "*/5 * * * *",
        "description": "Cross-project loops: replay buffer + Legion tripwire + circuit breaker telemetry",
        "enabled": True,
    },
    # Memory Tree daily global digest — rolls up yesterday's vault entries
    # into a single `global/{yyyymmdd}.md` chunk so the user has one place
    # to read what Zero saw across all sources that day.
    "memory_vault_daily_digest": {
        "cron": "0 4 * * *",  # 04:00 UTC daily
        "description": "Memory Tree: write daily global digest across all vault sources",
        "enabled": True,
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
        self._enabled_overrides: Dict[str, bool] = {}

    async def start(self):
        """Start the scheduler with all configured jobs."""
        if self._running:
            logger.warning("scheduler_already_running")
            return

        logger.info("scheduler_starting")
        self._enabled_overrides = await self._load_enabled_overrides()

        # Register every configured job. Disabled jobs are paused after the
        # scheduler starts so they remain visible and controllable in the UI.
        for job_name, config in DAILY_SCHEDULE.items():
            await self._register_job(job_name, config)

        self.scheduler.start()
        self._running = True
        for job_name in list(self._jobs):
            enabled = self._desired_enabled(job_name)
            self._apply_runtime_enabled(job_name, enabled)

        logger.info(
            "scheduler_started",
            jobs=list(self._jobs.keys()),
            disabled=[
                job_name
                for job_name in self._jobs
                if not self._desired_enabled(job_name)
            ],
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

    async def _load_enabled_overrides(self) -> Dict[str, bool]:
        """Load persisted job enable/disable overrides."""
        try:
            async with get_session() as session:
                row = await session.get(ServiceConfigModel, SCHEDULER_CONFIG_KEY)
                config = row.config if row else {}
                raw = (config or {}).get(SCHEDULER_OVERRIDES_KEY) or {}
                return {str(k): bool(v) for k, v in raw.items()}
        except Exception as e:
            logger.warning("scheduler_config_load_failed", error=str(e))
            return {}

    async def _save_enabled_overrides(self) -> None:
        """Persist the in-memory enabled-state overrides."""
        try:
            async with get_session() as session:
                row = await session.get(ServiceConfigModel, SCHEDULER_CONFIG_KEY)
                config = {SCHEDULER_OVERRIDES_KEY: dict(self._enabled_overrides)}
                if row is None:
                    session.add(ServiceConfigModel(service_name=SCHEDULER_CONFIG_KEY, config=config))
                else:
                    row.config = {**(row.config or {}), **config}
                    row.updated_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.error("scheduler_config_save_failed", error=str(e))
            raise

    def _desired_enabled(self, job_name: str) -> bool:
        """Return persisted override if present, otherwise the code default."""
        if job_name in self._enabled_overrides:
            return bool(self._enabled_overrides[job_name])
        if job_name in DAILY_SCHEDULE:
            return get_default_job_enabled(job_name, DAILY_SCHEDULE[job_name])
        return True

    def _apply_runtime_enabled(self, job_name: str, enabled: bool) -> bool:
        """Pause/resume a live APScheduler job. Returns False when not registered."""
        job = self.scheduler.get_job(job_name)
        if job is None:
            return False
        try:
            if enabled:
                self.scheduler.resume_job(job_name)
            else:
                self.scheduler.pause_job(job_name)
            return True
        except Exception as e:
            logger.warning(
                "scheduler_job_runtime_toggle_failed",
                job=job_name,
                enabled=enabled,
                error=str(e),
            )
            return False

    async def _after_disable_actions(self, job_name: str) -> None:
        """Run side effects that should happen immediately when a job is stopped."""
        if job_name != "reachy_email_nudge":
            return
        try:
            from app.services.email_voice_session_service import get_email_voice_session_service

            await get_email_voice_session_service().clear_silently(reason="scheduler_disabled")
        except Exception as e:
            logger.debug("email_voice_clear_on_disable_failed", error=str(e))

    def _known_job_names(self) -> set[str]:
        return set(DAILY_SCHEDULE) | {job.id for job in self.scheduler.get_jobs()}

    def _runtime_job_lookup(self) -> Dict[str, Any]:
        return {job.id: job for job in self.scheduler.get_jobs()}

    @staticmethod
    def _iso(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None

    def _serialize_job(
        self,
        job_name: str,
        job: Optional[Any],
        stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        config = DAILY_SCHEDULE.get(job_name, {})
        stats = stats or {}
        next_run = getattr(job, "next_run_time", None) if job is not None else None
        enabled = bool(job is not None and next_run is not None)
        default_enabled = get_default_job_enabled(job_name, config) if job_name in DAILY_SCHEDULE else True
        description = str(config.get("description") or (job.name if job is not None else job_name))
        success = int(stats.get("success_count") or 0)
        failures = int(stats.get("failure_count") or 0)
        total = success + failures
        health = "green"
        if failures > 0 and total > 0:
            health = "red" if (failures / total) > 0.3 else "yellow"
        elif total == 0:
            health = "gray"

        return {
            "id": job_name,
            "name": job_name,
            "display_name": description,
            "description": description,
            "category": get_job_category(job_name),
            "schedule": str(config.get("cron") or ""),
            "next_run": self._iso(next_run),
            "enabled": enabled,
            "default_enabled": default_enabled,
            "configured": job_name in DAILY_SCHEDULE,
            "registered": job is not None,
            "controllable": job is not None,
            "source": "configured" if job_name in DAILY_SCHEDULE else "runtime",
            "health": health,
            "total_runs": int(stats.get("total_runs") or 0),
            "success_count": success,
            "failure_count": failures,
            "avg_duration_s": round(float(stats.get("avg_duration_s") or 0), 2),
            "last_run": stats.get("last_run"),
        }

    async def get_recent_job_stats(self, hours: int = 24) -> Dict[str, Dict[str, Any]]:
        """Aggregate recent scheduler audit stats by job name."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        try:
            async with get_session() as session:
                stmt = (
                    select(
                        SchedulerAuditLogModel.job_name,
                        sa_func.count().label("total_runs"),
                        sa_func.sum(case((SchedulerAuditLogModel.status == "completed", 1), else_=0)).label("success_count"),
                        sa_func.sum(case((SchedulerAuditLogModel.status == "failed", 1), else_=0)).label("failure_count"),
                        sa_func.avg(SchedulerAuditLogModel.duration_seconds).label("avg_duration"),
                        sa_func.max(SchedulerAuditLogModel.started_at).label("last_run"),
                    )
                    .where(SchedulerAuditLogModel.started_at >= since)
                    .group_by(SchedulerAuditLogModel.job_name)
                )
                rows = (await session.execute(stmt)).all()
        except Exception as e:
            logger.warning("scheduler_recent_stats_failed", error=str(e))
            return {}

        return {
            row.job_name: {
                "total_runs": row.total_runs or 0,
                "success_count": row.success_count or 0,
                "failure_count": row.failure_count or 0,
                "avg_duration_s": round(row.avg_duration or 0, 2),
                "last_run": row.last_run.isoformat() if row.last_run else None,
            }
            for row in rows
        }

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
            "calendar_check": self._run_calendar_check,
            "gmail_digest": self._run_gmail_digest,
            "reachy_calendar_nudge": self._run_reachy_calendar_nudge,
            "reachy_email_nudge": self._run_reachy_email_nudge,
            "reachy_meeting_auto_record": self._run_reachy_meeting_auto_record,
            "reachy_meeting_auto_stop": self._run_reachy_meeting_auto_stop,
            "reachy_morning_briefing": self._run_reachy_morning_briefing,
            "reachy_evening_journal": self._run_reachy_evening_journal,
            "reachy_ambient_heartbeat": self._run_reachy_ambient_heartbeat,
            "email_automation_check": self._run_email_automation_check,
            "legion_enhancement_sync": self._run_legion_enhancement_sync,
            "email_to_tasks": self._run_email_to_tasks,
            "meeting_prep": self._run_meeting_prep,
            "blocked_task_escalation": self._run_blocked_task_escalation,
            "smart_suggestions": self._run_smart_suggestions,
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
            # Meal Manager
            "meal_catalog_refresh": self._run_meal_catalog_refresh,
            "meal_promo_hunt": self._run_meal_promo_hunt,
            "meal_shipment_scan": self._run_meal_shipment_scan,
            "meal_discovery": self._run_meal_discovery,
            "meal_daily_digest": self._run_meal_daily_digest,
            "meal_signup_sweep": self._run_meal_signup_sweep,
            "meal_vision_sweep": self._run_meal_vision_sweep,
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
            # Autonomous Research Loop
            "autonomous_research_tick": self._run_autonomous_research_tick,
            # Ambient vision (Phase 5 of Meta-glasses / Reachy-camera plan)
            "ambient_vision_tick": self._run_ambient_vision_tick,
            # SecondBrain phases 2 / 3 / 4 / 5
            "vault_reindex_tick": self._run_vault_reindex_tick,
            "vault_task_sync_tick": self._run_vault_task_sync_tick,
            "approvals_expire_stale": self._run_approvals_expire_stale,
            "morning_digest_tick": self._run_morning_digest_tick,
            "weekly_review_tick": self._run_weekly_review_tick,
            "drift_scan_tick": self._run_drift_scan_tick,
            "ai_company_idea_validation": self._run_ai_company_idea_validation,
            "ai_company_daily_council": self._run_ai_company_daily_council,
            "ai_company_experiment_monitor": self._run_ai_company_experiment_monitor,
            "company_operator_monitor": self._run_company_operator_monitor,
            "company_agent_work": self._run_company_agent_work,
            "company_operator_overnight": self._run_company_operator_overnight,
            "company_operator_morning_brief": self._run_company_operator_morning_brief,
            "company_operator_evening_report": self._run_company_operator_evening_report,
            "company_operator_weekly_review": self._run_company_operator_weekly_review,
            "company_prompt_eval_bridge": self._run_company_prompt_eval_bridge,
            # Character Content
            "character_research_refresh": self._run_character_research_refresh,
            "character_research_retry": self._run_character_research_retry,
            "character_content_generation": self._run_character_content_generation,
            "character_content_gate": self._run_character_content_gate,
            "carousel_watchdog": self._run_carousel_watchdog,
            "character_performance_sync": self._run_character_performance_sync,
            "character_auto_publish": self._run_character_auto_publish,
            "character_content_learning": self._run_character_content_learning,
            "carousel_banned_hook_backfill": self._run_carousel_banned_hook_backfill,
            "carousel_morning_briefing": self._run_carousel_morning_briefing,
            "carousel_evening_recap": self._run_carousel_evening_recap,
            "character_reference_video_processor": self._run_character_reference_video_processor,
            "character_reference_video_learning": self._run_character_reference_video_learning,
            "character_reference_video_cleanup": self._run_character_reference_video_cleanup,
            "carousel_reaudit": self._run_carousel_reaudit,
            "entity_research_deepen": self._run_entity_research_deepen,
            "employee_checkin": self._run_employee_checkin,
            "character_image_cleanup": self._run_character_image_cleanup,
            # Phase 024: Character Autopilot
            "character_auto_approval": self._run_character_auto_approval,
            "character_publish_backlog": self._run_character_publish_backlog,
            "character_discovery": self._run_character_discovery,
            "character_gap_audit": self._run_character_gap_audit,
            "character_hook_audit": self._run_character_hook_audit,
            "character_discovery_refvideos": self._run_character_discovery_refvideos,
            "character_auto_research": self._run_character_auto_research,
            "character_final_review_backfill": self._run_character_final_review_backfill,
            "media_auto_research": self._run_media_auto_research,
            "media_content_generation": self._run_media_content_generation,
            # Trend Intelligence
            "trend_release_calendar_sync": self._run_trend_release_calendar_sync,
            "trend_tvmaze_schedule": self._run_trend_tvmaze_schedule,
            "trend_reddit_pulse": self._run_trend_reddit_pulse,
            "trend_searxng_pulse": self._run_trend_searxng_pulse,
            "trend_linker": self._run_trend_linker,
            "trend_scorer": self._run_trend_scorer,
            "trend_signal_cleanup": self._run_trend_signal_cleanup,
            "character_release_prep": self._run_character_release_prep,
            "media_release_prep": self._run_media_release_prep,
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
            # Content Brain v2 accelerators
            "brain_prompt_breed": self._run_brain_prompt_breed,
            "competitor_scrape": self._run_competitor_scrape,
            "competitor_cleanup": self._run_competitor_cleanup,
            "character_hook_style_report": self._run_character_hook_style_report,
            # Orchestration hardening (migration 035)
            "autonomous_content_loop": self._run_autonomous_content_loop,
            "swarm_calibration": self._run_swarm_calibration,
            "lore_ingestion": self._run_lore_ingestion,
            "carousel_partition_maintenance": self._run_carousel_partition_maintenance,
            # Cross-project self-improvement loops (autoresearch)
            "loop_tick_5min": self._run_loop_tick,
            "loop_judge_15min": self._run_loop_judge,
            "loop_promote_hourly": self._run_loop_promote,
            "loop_crosspoll_30m": self._run_loop_crosspoll,
            "loop_health_5min": self._run_loop_health,
            "memory_vault_daily_digest": self._run_memory_vault_daily_digest,
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

    # ------------------------------------------------------------------
    # Reachy voice nudges (M2.3 / M2.4)
    # ------------------------------------------------------------------

    # State kept on the scheduler instance so each nudge doesn't repeat within
    # a single event's warning window. Maps (event_id, bucket) -> announced_at.
    _reachy_nudged_events: dict[tuple[str, int], float] = {}
    _reachy_last_email_nudge: float = 0.0
    _reachy_last_email_count: int = 0

    def _reachy_realtime_session_active(self) -> bool:
        """Avoid autonomous Reachy speech while the user has a live session."""
        try:
            from app.services.reachy_realtime.session import realtime_motion_snapshot
            snap = realtime_motion_snapshot()
            return int(snap.get("active_sessions") or 0) > 0
        except Exception:
            return False

    async def _run_reachy_calendar_nudge(self):
        """
        Every minute, look at the next hour of events. When an event is 10, 5, or
        1 minute away (and we haven't already announced that bucket), speak it
        through the Reachy speaker.
        """
        import time as _time
        if self._reachy_realtime_session_active():
            logger.debug("reachy_calendar_nudge_skipped", reason="realtime_session_active")
            return
        try:
            from app.services.reachy_service import get_reachy_service
            reachy = get_reachy_service()
            if not await reachy.is_connected():
                return
            from app.services.calendar_service import get_calendar_service
            svc = get_calendar_service()
            from datetime import datetime, timedelta, timezone
            now = datetime.now(tz=timezone.utc)
            events = await svc.list_events(
                start_date=now,
                end_date=now + timedelta(minutes=60),
                limit=10,
            )
        except Exception as e:
            logger.debug("reachy_calendar_nudge_skipped", error=str(e))
            return

        if not events:
            return

        now_s = _time.time()
        # Drop old nudges so the dict doesn't grow unbounded.
        self._reachy_nudged_events = {
            k: v for k, v in self._reachy_nudged_events.items() if now_s - v < 3600
        }

        for ev in events:
            event_id = str(getattr(ev, "id", None) or getattr(ev, "event_id", None) or "")
            title = str(getattr(ev, "summary", None) or getattr(ev, "title", None) or "an event")
            start = getattr(ev, "start_time", None) or getattr(ev, "start", None)
            if not start:
                continue
            try:
                if isinstance(start, str):
                    from datetime import datetime as _dt
                    start_dt = _dt.fromisoformat(start.replace("Z", "+00:00"))
                else:
                    start_dt = start
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            mins_until = (start_dt - datetime.now(tz=timezone.utc)).total_seconds() / 60.0
            bucket = None
            if 9.0 <= mins_until <= 10.5:
                bucket = 10
            elif 4.0 <= mins_until <= 5.5:
                bucket = 5
            elif 0.5 <= mins_until <= 1.5:
                bucket = 1
            if bucket is None:
                continue
            key = (event_id, bucket)
            if key in self._reachy_nudged_events:
                continue
            self._reachy_nudged_events[key] = now_s
            if bucket == 1:
                text = f"Heads up — {title} starts in one minute."
            elif bucket == 5:
                text = f"Reminder — {title} starts in five minutes."
            else:
                text = f"Coming up — {title} starts in ten minutes."
            try:
                import asyncio as _asyncio
                _asyncio.create_task(reachy.say(text))
                logger.info("reachy_calendar_nudge_spoken", event=title, bucket_min=bucket)
            except Exception as e:
                logger.debug("reachy_calendar_nudge_say_failed", error=str(e))

    async def _run_reachy_email_nudge(self):
        """Per-email voice triage across ALL connected accounts.

        Iterates accounts, skips ones currently in their configured quiet-hours
        window, and enqueues unread emails from the rest into the voice session.
        """
        if self._reachy_realtime_session_active():
            logger.debug("reachy_email_nudge_skipped", reason="realtime_session_active")
            return
        try:
            from app.services.reachy_service import get_reachy_service
            from app.services.gmail_service import get_gmail_service
            from app.services.gmail_oauth_service import get_gmail_oauth_service
            from app.services.email_voice_session_service import (
                get_email_voice_session_service,
            )
            from app.models.email import EmailStatus

            reachy = get_reachy_service()
            if not await reachy.is_connected():
                return

            oauth_svc = get_gmail_oauth_service()
            gmail = get_gmail_service()
            accounts = await oauth_svc.list_accounts()
        except Exception as e:
            logger.debug("reachy_email_nudge_skipped", error=str(e))
            return

        if not accounts:
            return

        new_ids: list[str] = []
        for acct in accounts:
            if _is_account_quiet_now(acct):
                logger.debug(
                    "reachy_email_nudge_account_quiet",
                    account_id=acct["id"],
                    label=acct.get("label"),
                )
                continue
            try:
                unread = await gmail.list_emails(
                    status=EmailStatus.UNREAD,
                    limit=20,
                    account_id=acct["id"],
                )
                new_ids.extend(e.id for e in unread)
            except Exception as e:
                logger.warning(
                    "reachy_email_nudge_account_failed",
                    account_id=acct["id"],
                    error=str(e),
                )

        if not new_ids:
            self._reachy_last_email_count = 0
            return

        session = get_email_voice_session_service()
        added = await session.enqueue(new_ids)
        if added:
            logger.info(
                "reachy_email_nudge_enqueued",
                added=added,
                total_unread=len(new_ids),
            )
        self._reachy_last_email_count = len(new_ids)

        # Kick off the first prompt if nothing is in flight.
        if not session.is_active():
            announced = await session.kickstart_if_idle()
            if announced:
                logger.info("reachy_email_nudge_announced", email_id=announced)

    async def _run_reachy_meeting_auto_record(self):
        """Start a recording for any flagged meeting whose start time just hit.

        Routes through the Zero Host Audio Agent when ZERO_HOST_AGENT_URL is
        configured (the common case — pyaudiowpatch isn't available inside
        zero-api's Linux container). Falls back to in-process capture only
        when the backend itself is running on a host with audio support.
        """
        try:
            from datetime import datetime, timezone
            from app.services.meeting_auto_recorder_service import (
                get_meeting_auto_recorder_service,
            )
            from app.services.reachy_service import get_reachy_service

            svc = get_meeting_auto_recorder_service()
            now = datetime.now(timezone.utc)
            due = await svc.due_starts(now, window_seconds=60)
            if not due:
                return

            reachy = get_reachy_service()
            reachy_up = await reachy.is_connected()

            from app.services.meeting_recording_service import (
                start_recording,
                start_recording_via_host_agent,
                _host_agent_base,
            )
            from app.infrastructure.database import get_session

            use_host_agent = _host_agent_base() is not None

            for entry in due:
                meeting_id = entry["meeting_id"]
                event_id = entry["calendar_event_id"]
                try:
                    if use_host_agent:
                        await start_recording_via_host_agent(
                            meeting_id=meeting_id, source="mixed"
                        )
                    else:
                        async with get_session() as db:
                            await start_recording(db, meeting_id=meeting_id, source="mixed")
                    await svc.mark_started(event_id)
                    logger.info(
                        "reachy_meeting_auto_record_started",
                        meeting_id=meeting_id,
                        event_id=event_id,
                        via="host_agent" if use_host_agent else "local",
                    )
                    if reachy_up:
                        import asyncio as _asyncio
                        _asyncio.create_task(
                            reachy.say(f"Recording {entry.get('title') or 'this meeting'} now.")
                        )
                except RuntimeError as e:
                    logger.info(
                        "reachy_meeting_auto_record_already_running",
                        meeting_id=meeting_id,
                        error=str(e),
                    )
                except Exception as e:
                    logger.warning(
                        "reachy_meeting_auto_record_failed",
                        meeting_id=meeting_id,
                        error=str(e),
                    )
        except Exception as e:
            logger.debug("reachy_meeting_auto_record_skipped", error=str(e))

    async def _run_reachy_meeting_auto_stop(self):
        """Stop the recording for any auto-record meeting whose end time has passed.

        Mirrors the routing in _run_reachy_meeting_auto_record — checks host_agent
        status when configured, local AudioCapture otherwise.
        """
        try:
            from datetime import datetime, timezone
            from app.services.meeting_auto_recorder_service import (
                get_meeting_auto_recorder_service,
            )

            svc = get_meeting_auto_recorder_service()
            now = datetime.now(timezone.utc)
            due = await svc.due_stops(now, grace_seconds=30)
            if not due:
                return

            from app.services.meeting_recording_service import (
                stop_recording,
                get_recording_status,
                stop_recording_via_host_agent,
                get_recording_status_via_host_agent,
                _host_agent_base,
            )
            from app.infrastructure.database import get_session

            use_host_agent = _host_agent_base() is not None

            # One status probe per tick — cheap and avoids stopping a recording
            # that wasn't ours (e.g. manual Quick Meeting still in progress).
            if use_host_agent:
                status = await get_recording_status_via_host_agent()
                is_recording = bool(status and status.get("is_recording"))
            else:
                is_recording = bool(get_recording_status().get("is_recording"))

            for entry in due:
                event_id = entry["calendar_event_id"]
                if not is_recording:
                    await svc.mark_stopped(event_id)
                    continue
                try:
                    if use_host_agent:
                        result = await stop_recording_via_host_agent()
                    else:
                        async with get_session() as db:
                            result = await stop_recording(db)
                    if result:
                        await svc.mark_stopped(event_id)
                        is_recording = False  # only one active recording at a time
                        logger.info(
                            "reachy_meeting_auto_record_stopped",
                            meeting_id=entry["meeting_id"],
                            event_id=event_id,
                            via="host_agent" if use_host_agent else "local",
                        )
                except Exception as e:
                    logger.warning(
                        "reachy_meeting_auto_stop_failed",
                        meeting_id=entry["meeting_id"],
                        error=str(e),
                    )
        except Exception as e:
            logger.debug("reachy_meeting_auto_stop_skipped", error=str(e))

    async def _run_reachy_morning_briefing(self):
        """Daily 8AM briefing through Reachy in the narrator persona.

        Reads the day's calendar, top tasks, and inbox load, condenses through
        the unified LLM as a 2-3 sentence brief, then speaks it via reachy.say.
        Skips silently if Reachy daemon is unavailable, an active realtime
        voice session is already running, or the user explicitly disabled
        proactive nudges via the companion policy.
        """
        if self._reachy_realtime_session_active():
            logger.debug("reachy_morning_briefing_skipped", reason="realtime_session_active")
            return
        try:
            from app.services.reachy_service import get_reachy_service
            from app.services.reachy_companion_service import get_reachy_companion_service
            from app.services.reachy_context_service import build_context_hint

            reachy = get_reachy_service()
            if not await reachy.is_connected():
                return
            policy = get_reachy_companion_service().get_policy()
            if not policy.proactive_enabled or policy.mode in {"focus", "meeting", "privacy", "sleep"}:
                logger.debug(
                    "reachy_morning_briefing_skipped",
                    reason="policy_disallows",
                    mode=policy.mode,
                    proactive=policy.proactive_enabled,
                )
                return
        except Exception as e:
            logger.debug("reachy_morning_briefing_skipped", error=str(e))
            return

        try:
            context = await build_context_hint("narrator")
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            llm = get_unified_llm_client()
            prompt = (
                "You are Zero speaking through Reachy as the narrator persona. "
                "Give the user a calm 2-3 sentence morning briefing based on the "
                "context below: the most important calendar event today, the most "
                "important task, and one note. Speak like a thoughtful friend, "
                "not a calendar bot. No greeting, no sign-off, just the brief.\n\n"
                f"{context}"
            )
            text = (await llm.chat(
                prompt=prompt,
                task_type="voice_reply",
                max_tokens=180,
                temperature=0.6,
            )).strip()
            if not text:
                return
            try:
                await reachy.play_emotion("curious1")
            except Exception as e:
                logger.debug("reachy_morning_briefing_emotion_failed", error=str(e))
            await reachy.say(text)
            logger.info("reachy_morning_briefing_spoken", chars=len(text))
        except Exception as e:
            logger.warning("reachy_morning_briefing_failed", error=str(e))

    async def _run_reachy_evening_journal(self):
        """6PM end-of-day reflection in the wellness persona.

        Speaks the first journaling question through Reachy and leaves the
        FloatingVoiceButton primed to capture the answer. Three questions
        cycle on subsequent ticks within the same evening window. Writes any
        captured answers to the vault under 00_Meta/_agent/journal/.
        """
        if self._reachy_realtime_session_active():
            return
        try:
            from app.services.reachy_service import get_reachy_service
            from app.services.reachy_companion_service import get_reachy_companion_service
            reachy = get_reachy_service()
            if not await reachy.is_connected():
                return
            policy = get_reachy_companion_service().get_policy()
            if not policy.proactive_enabled or policy.mode in {"focus", "meeting", "privacy", "sleep"}:
                return
        except Exception as e:
            logger.debug("reachy_evening_journal_skipped", error=str(e))
            return

        questions = [
            "How did today go for you?",
            "Was there anything that surprised you today?",
            "One thing you want to remember from today?",
        ]
        idx = getattr(self, "_evening_journal_idx", 0) % len(questions)
        self._evening_journal_idx = idx + 1
        text = questions[idx]
        try:
            await reachy.play_emotion("understanding1")
        except Exception as e:
            logger.debug("reachy_evening_journal_emotion_failed", error=str(e))
        try:
            await reachy.say(text)
            logger.info("reachy_evening_journal_prompt", question_idx=idx)
        except Exception as e:
            logger.debug("reachy_evening_journal_say_failed", error=str(e))

    async def _run_reachy_ambient_heartbeat(self):
        """Ambient idle gestures so Reachy doesn't sit perfectly still.

        Runs only in ambient mode when no motion is currently active and
        no realtime session is open. Picks a low-key emotion clip from a
        curated subset (attentive/curious/thoughtful/serenity/relief) and
        plays it through reachy.play_emotion. The 2-minute cadence is
        deliberately sparse so the robot feels alive without being noisy.
        """
        if self._reachy_realtime_session_active():
            return
        try:
            from app.services.reachy_service import get_reachy_service
            from app.services.reachy_companion_service import get_reachy_companion_service
            reachy = get_reachy_service()
            if not await reachy.is_connected():
                return
            policy = get_reachy_companion_service().get_policy()
            if policy.mode != "ambient" or not policy.body_motion_enabled:
                return
        except Exception as e:
            logger.debug("reachy_ambient_heartbeat_skipped", error=str(e))
            return

        try:
            moving_state = await reachy.is_moving()
            running_uuids = moving_state.get("running") if isinstance(moving_state, dict) else None
            if running_uuids:
                return
        except Exception as e:
            logger.debug("reachy_ambient_heartbeat_running_check_failed", error=str(e))
            return

        import random
        candidates = ["attentive1", "curious1", "thoughtful1", "serenity1", "relief1", "shy1"]
        emotion = random.choice(candidates)
        try:
            await reachy.play_emotion(emotion)
            logger.debug("reachy_ambient_heartbeat", emotion=emotion)
        except Exception as e:
            logger.debug("reachy_ambient_heartbeat_emotion_failed", error=str(e))

    async def _run_gmail_check(self):
        """Incremental Gmail sync — runs against EVERY connected account."""
        logger.info("running_gmail_check")
        try:
            from app.services.gmail_service import get_gmail_service
            from app.services.gmail_oauth_service import get_gmail_oauth_service

            gmail = get_gmail_service()
            accounts = await get_gmail_oauth_service().list_accounts()
            if not accounts:
                return  # No Google accounts connected, skip silently

            for acct in accounts:
                try:
                    result = await gmail.sync_incremental(account_id=acct["id"])
                    new_count = result.get("new_emails", 0)
                    if new_count > 0:
                        logger.info(
                            "gmail_check_new_emails",
                            account_id=acct["id"],
                            email=acct["email"],
                            count=new_count,
                        )
                except Exception as e:
                    logger.warning(
                        "gmail_check_account_failed",
                        account_id=acct["id"],
                        email=acct["email"],
                        error=str(e),
                    )
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

    async def _run_calendar_check(self):
        """Calendar sync — runs against EVERY connected account.

        Mirrors `_run_gmail_check`: iterate `oauth_accounts`, call
        `CalendarService.sync_events(account_id=...)` per row. Each event is
        cached with the source account_id so the UI's per-account view stays
        accurate without waiting on the user to open the Calendar page.
        """
        logger.info("running_calendar_check")
        try:
            from app.services.calendar_service import get_calendar_service
            from app.services.gmail_oauth_service import get_gmail_oauth_service

            calendar = get_calendar_service()
            accounts = await get_gmail_oauth_service().list_accounts()
            if not accounts:
                return

            for acct in accounts:
                try:
                    result = await calendar.sync_events(
                        days_ahead=30, account_id=acct["id"]
                    )
                    logger.info(
                        "calendar_check_synced",
                        account_id=acct["id"],
                        email=acct["email"],
                        events_count=result.get("events_count", 0),
                    )
                except Exception as e:
                    logger.warning(
                        "calendar_check_account_failed",
                        account_id=acct["id"],
                        email=acct["email"],
                        error=str(e),
                    )

            # Phase 6: auto-record-all — when the user has enabled it, every
            # newly-synced calendar event with attendees becomes a Meeting row
            # with auto_record=True. Per-event override stays usable.
            try:
                await self._apply_auto_record_all()
            except Exception as e:  # noqa: BLE001
                logger.warning("auto_record_all_failed", error=str(e))
        except Exception as e:
            logger.debug("calendar_check_skipped", error=str(e))

    async def _apply_auto_record_all(self) -> None:
        try:
            from app.routers.meeting_preferences import get_meeting_prefs
            prefs = get_meeting_prefs()
        except Exception:
            return
        if not prefs.get("auto_record_all"):
            return

        from datetime import datetime, timezone, timedelta
        import uuid as _uuid
        from sqlalchemy import select
        from app.db.models import CalendarEventCacheModel, MeetingModel
        from app.infrastructure.database import get_session
        from app.services.meeting_auto_recorder_service import (
            get_meeting_auto_recorder_service,
        )

        def _parse_jsonb_dt(payload: dict | None) -> datetime | None:
            if not payload:
                return None
            raw = payload.get("date_time") or payload.get("date")
            if not raw:
                return None
            try:
                if "T" in raw:
                    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(raw, "%Y-%m-%d")
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:  # noqa: BLE001
                return None

        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=2)
        auto_svc = get_meeting_auto_recorder_service()
        promoted = 0
        async with get_session() as session:
            events = (
                await session.execute(select(CalendarEventCacheModel))
            ).scalars().all()
            for ev in events:
                if not ev.attendees:
                    continue
                start = _parse_jsonb_dt(ev.start_dt)
                end = _parse_jsonb_dt(ev.end_dt)
                if start is None or start < now or start > horizon:
                    continue
                if await auto_svc.is_marked(ev.id):
                    continue

                # Ensure a Meeting row exists for this calendar event.
                meeting = (
                    await session.execute(
                        select(MeetingModel).where(MeetingModel.calendar_event_id == ev.id)
                    )
                ).scalar_one_or_none()
                if meeting is None:
                    meeting = MeetingModel(
                        id=_uuid.uuid4().hex,
                        title=ev.summary or "Meeting",
                        calendar_event_id=ev.id,
                        start_time=start,
                        end_time=end,
                        status="scheduled",
                    )
                    session.add(meeting)
                    await session.flush()

                await auto_svc.mark(
                    calendar_event_id=ev.id,
                    meeting_id=meeting.id,
                    start_time=start,
                    end_time=end,
                    title=meeting.title,
                )
                promoted += 1
            await session.commit()
        if promoted:
            logger.info("auto_record_all_promoted", count=promoted)

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

    # ------------------------------------------------------------------
    # Meal Manager jobs
    # ------------------------------------------------------------------

    async def _run_meal_catalog_refresh(self):
        """Refresh menu pages + pricing for every tracked meal service."""
        logger.info("running_meal_catalog_refresh")
        try:
            from app.services.meal_catalog_service import get_meal_catalog_service
            result = await get_meal_catalog_service().refresh_all_catalogs()
            logger.info("meal_catalog_refresh_complete", **result)
        except Exception as e:
            logger.error("meal_catalog_refresh_failed", error=str(e))

    async def _run_meal_promo_hunt(self):
        """Hunt fresh promo codes + portal cashback for tracked meal services."""
        logger.info("running_meal_promo_hunt")
        try:
            from app.services.meal_promo_hunter_service import get_meal_promo_hunter
            result = await get_meal_promo_hunter().hunt_all()
            logger.info("meal_promo_hunt_complete", **result)
        except Exception as e:
            logger.error("meal_promo_hunt_failed", error=str(e))

    async def _run_meal_shipment_scan(self):
        """Scan Gmail cache for meal shipment notifications + card offer emails."""
        logger.info("running_meal_shipment_scan")
        try:
            from app.services.meal_shipment_tracker_service import get_meal_shipment_tracker
            result = await get_meal_shipment_tracker().scan_recent(lookback_days=14)
            logger.info("meal_shipment_scan_complete", **result)
        except Exception as e:
            logger.error("meal_shipment_scan_failed", error=str(e))

    async def _run_meal_discovery(self):
        """Weekly discovery — search for new meal delivery services to track."""
        logger.info("running_meal_discovery")
        try:
            from app.services.meal_scraper_service import get_meal_scraper
            from app.db.models import MealServiceModel
            from app.infrastructure.database import get_session
            from sqlalchemy import select

            scraper = get_meal_scraper()
            queries = [
                "new meal delivery service 2026",
                "best prepared meal delivery US comparison",
                "cheap meal kit startup launch 2025 2026",
            ]
            known = set()
            async with get_session() as session:
                for s in (await session.execute(select(MealServiceModel))).scalars().all():
                    known.add(s.slug.lower())
                    known.add(s.name.lower())
            candidates: list[dict] = []
            for q in queries:
                hits = await scraper.search(q, max_results=15)
                for h in hits:
                    title = (h.get("title") or "").lower()
                    if any(k in title for k in known):
                        continue
                    candidates.append(h)
            logger.info("meal_discovery_complete", new_candidates=len(candidates))
            # Persist a vault note; user approves before we add to catalog.
            try:
                from app.services.vault_writer_service import get_vault_writer
                writer = get_vault_writer()
                if writer.available() and candidates:
                    md = "# New meal service candidates\n\n"
                    md += "Scheduler found these possible new services. Approve in /meals.\n\n"
                    for c in candidates[:40]:
                        md += f"- [{c.get('title','?')}]({c.get('url','')}) — {c.get('snippet','')[:160]}\n"
                    writer.write_agent_file(
                        "00_Meta/_agent/meals/discovery_candidates.md",
                        md,
                        source="meal_discovery",
                    )
            except Exception as e:
                logger.debug("meal_discovery_vault_write_failed", error=str(e))
        except Exception as e:
            logger.error("meal_discovery_failed", error=str(e))

    async def _run_meal_daily_digest(self):
        """Write daily meal digest to the vault."""
        logger.info("running_meal_daily_digest")
        try:
            from app.services.meal_price_stack_service import get_meal_price_stack_service
            from app.services.vault_writer_service import get_vault_writer
            from app.db.models import MealPromoCodeModel, MealShipmentModel
            from app.infrastructure.database import get_session
            from sqlalchemy import select

            quotes = await get_meal_price_stack_service().cheapest_across_services(
                meal_count=6, new_customer=False
            )
            async with get_session() as session:
                promos = (await session.execute(
                    select(MealPromoCodeModel)
                    .order_by(MealPromoCodeModel.last_seen_at.desc())
                    .limit(10)
                )).scalars().all()
                in_transit = (await session.execute(
                    select(MealShipmentModel).where(
                        MealShipmentModel.status.in_(["shipped", "out_for_delivery", "processing"])
                    )
                )).scalars().all()

            md_lines = [
                "# Meal digest — " + datetime.utcnow().strftime("%Y-%m-%d"),
                "",
                "## Cheapest per meal (stacked, 6 meals)",
                "",
            ]
            for q in quotes[:10]:
                md_lines.append(
                    f"- **{q.service_name}**: ${q.price_per_meal:.2f}/meal "
                    f"(subtotal ${q.base_subtotal:.2f} - ${q.total_discounts:.2f} discounts "
                    f"- ${q.total_cashback:.2f} cashback)"
                )
            md_lines += ["", "## Top promo codes", ""]
            for p in promos:
                md_lines.append(
                    f"- `{p.code or 'auto'}` ({p.source}) — {p.discount_type} {p.discount_value}"
                    + (f", expires {p.expires_at:%Y-%m-%d}" if p.expires_at else "")
                )
            md_lines += ["", "## In-transit shipments", ""]
            for s in in_transit:
                md_lines.append(
                    f"- service={s.service_id}, order={s.order_number or '—'}, "
                    f"carrier={s.carrier or '—'}, status={s.status}"
                )

            writer = get_vault_writer()
            if writer.available():
                writer.write_agent_file(
                    "00_Meta/_agent/meals/daily_digest.md",
                    "\n".join(md_lines),
                    source="meal_daily_digest",
                )
            logger.info("meal_daily_digest_complete", quotes=len(quotes), promos=len(promos), in_transit=len(in_transit))
        except Exception as e:
            logger.error("meal_daily_digest_failed", error=str(e))

    async def _run_meal_signup_sweep(self):
        """Weekly: sign up newsletters + parse any welcome emails already in cache."""
        logger.info("running_meal_signup_sweep")
        try:
            from app.services.meal_signup_sweeper_service import get_meal_signup_sweeper
            svc = get_meal_signup_sweeper()
            signup_result = await svc.sweep_signups()
            parse_result = await svc.parse_welcome_emails(lookback_days=30)
            logger.info(
                "meal_signup_sweep_complete",
                signup=signup_result.get("status"),
                signed_up=signup_result.get("signed_up", 0),
                parse=parse_result.get("status"),
                parsed=parse_result.get("processed", 0),
                welcome_codes_extracted=parse_result.get("extracted", 0),
            )
        except Exception as e:
            logger.error("meal_signup_sweep_failed", error=str(e))

    async def _run_meal_vision_sweep(self):
        """Weekly: Vision-LLM sweep of meal-service homepages (env-gated)."""
        logger.info("running_meal_vision_sweep")
        try:
            from app.services.meal_vision_extractor_service import get_meal_vision_extractor
            result = await get_meal_vision_extractor().sweep()
            logger.info("meal_vision_sweep_complete", **result)
        except Exception as e:
            logger.error("meal_vision_sweep_failed", error=str(e))

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

    async def _run_carousel_morning_briefing(self):
        await self._send_carousel_employee_digest(label="Morning", window_hours=12)

    async def _run_carousel_evening_recap(self):
        await self._send_carousel_employee_digest(label="Evening", window_hours=12)

    async def _send_carousel_employee_digest(self, *, label: str, window_hours: int):
        """Generate the carousel employee report and dispatch to Discord."""
        logger.info("running_carousel_employee_digest", label=label)
        try:
            from app.services.daily_report_service import get_daily_report_service
            from app.services.notification_service import get_notification_service

            service = get_daily_report_service()
            report = await service.generate_carousel_employee_report(window_hours=window_hours)
            message = service.format_carousel_discord_message(report)
            generated = int(report.get("carousels", {}).get("generated", 0))
            avg = report.get("carousels", {}).get("stage2_avg_score")
            color = 0x57F287 if (avg or 0) >= 80 else (0xFEE75C if generated > 0 else 0xED4245)
            title = f"Zero Carousel Employee — {label} Report"
            try:
                await self._send_to_discord(title=title, message=message, color=color)
            except Exception as exc:
                logger.warning("carousel_employee_discord_failed", error=str(exc))
            try:
                await get_notification_service().create_notification(
                    title=title,
                    message=message[:1800],
                    channel="discord",
                    source="carousel_employee_report",
                )
            except Exception as exc:
                logger.debug("carousel_employee_notification_failed", error=str(exc))
            logger.info(
                "carousel_employee_digest_sent",
                label=label,
                generated=generated,
                avg=avg,
                issue_count=len(report.get("issues", [])),
            )
        except Exception as e:
            logger.error("carousel_employee_digest_failed", label=label, error=str(e))

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

    async def _run_autonomous_research_tick(self):
        """24/7 research driver. Picks eligible topic, dispatches deep research, writes vault artifact on completion."""
        try:
            from app.services.autonomous_research_loop_service import get_autonomous_research_loop
            loop = get_autonomous_research_loop()
            result = await loop.tick()
            logger.info("autonomous_research_tick", **{k: v for k, v in result.items() if v is not None})
        except Exception as e:
            logger.error("autonomous_research_tick_failed", error=str(e))

    async def _run_ambient_vision_tick(self):
        """Phase 5: pull a frame from the active SightProvider, VLM-describe it, log to vault."""
        try:
            from app.services.ambient_vision_service import ambient_vision_tick
            result = await ambient_vision_tick()
            # Only log when something actually happened, to avoid spam.
            if result.get("status") == "ok":
                logger.info("ambient_vision_tick", **{k: v for k, v in result.items() if v is not None})
        except Exception as e:
            logger.error("ambient_vision_tick_failed", error=str(e))

    async def _run_vault_reindex_tick(self):
        """SecondBrain Phase 2: incremental reindex of the Obsidian vault."""
        try:
            from app.services.vault_indexer_service import get_vault_indexer
            indexer = get_vault_indexer()
            if not indexer.available():
                return
            result = await indexer.reindex(force=False, max_files=200)
            safe = {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in result.items() if v is not None}
            logger.info("vault_reindex_tick", **safe)
        except Exception as e:
            logger.error("vault_reindex_tick_failed", error=str(e))

    async def _run_vault_task_sync_tick(self):
        """SecondBrain Phase 3: checkbox <-> TaskModel bi-directional sync."""
        try:
            from app.services.vault_task_sync_service import get_vault_task_sync
            svc = get_vault_task_sync()
            if not svc.available():
                return
            result = await svc.sync_all()
            logger.info("vault_task_sync_tick", **{k: v for k, v in result.items() if v is not None})
        except Exception as e:
            logger.error("vault_task_sync_tick_failed", error=str(e))

    async def _run_approvals_expire_stale(self):
        """Hourly: mark expired agent-approvals. Keeps the queue tight."""
        try:
            from app.services.approval_queue_service import get_approval_queue
            n = await get_approval_queue().expire_stale()
            if n:
                logger.info("approvals_expire_stale", expired=n)
        except Exception as e:
            logger.error("approvals_expire_stale_failed", error=str(e))

    async def _run_morning_digest_tick(self):
        """SecondBrain Phase 4: assemble + write the 7-section morning digest."""
        try:
            from app.services.morning_digest_service import get_morning_digest_service
            svc = get_morning_digest_service()
            result = await svc.generate_and_write()
            logger.info("morning_digest_tick", **{k: v for k, v in result.items() if v is not None})
        except Exception as e:
            logger.error("morning_digest_tick_failed", error=str(e))

    async def _run_weekly_review_tick(self):
        """SecondBrain Phase 4: Friday PM weekly review."""
        try:
            from app.services.weekly_review_service import get_weekly_review_service
            svc = get_weekly_review_service()
            result = await svc.generate_and_write()
            logger.info("weekly_review_tick", **{k: v for k, v in result.items() if v is not None})
        except Exception as e:
            logger.error("weekly_review_tick_failed", error=str(e))

    async def _run_drift_scan_tick(self):
        """SecondBrain Phase 5: nightly drift detection."""
        try:
            from app.services.drift_scanner_service import get_drift_scanner
            scanner = get_drift_scanner()
            result = await scanner.scan_all()
            logger.info("drift_scan_tick", **{k: v for k, v in result.items() if v is not None})
        except Exception as e:
            logger.error("drift_scan_tick_failed", error=str(e))

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

    async def _run_company_operator_monitor(self):
        """Lightweight 24/7 company heartbeat and report snapshot."""
        try:
            from app.services.company_operator_service import get_company_operator_service
            result = await get_company_operator_service().run_tick(
                run_type="monitor",
                requested_by="scheduler",
            )
            logger.info("company_operator_monitor_done", run_id=result.get("id"), status=result.get("status"))
        except Exception as e:
            logger.error("company_operator_monitor_failed", error=str(e))

    async def _run_company_agent_work(self):
        """Steady 24/7 company agent work loop for safe/staged internal execution."""
        try:
            from app.services.company_operator_service import get_company_operator_service
            result = await get_company_operator_service().run_tick(
                run_type="agent_work",
                requested_by="scheduler",
            )
            logger.info(
                "company_agent_work_done",
                run_id=result.get("id"),
                status=result.get("status"),
                actions=len(result.get("actions") or []),
            )
        except Exception as e:
            logger.error("company_agent_work_failed", error=str(e))

    async def _run_company_operator_overnight(self):
        """Overnight internal work block for formation and company operations."""
        try:
            from app.services.company_operator_service import get_company_operator_service
            result = await get_company_operator_service().run_tick(
                run_type="overnight",
                requested_by="scheduler",
            )
            logger.info("company_operator_overnight_done", run_id=result.get("id"), status=result.get("status"))
        except Exception as e:
            logger.error("company_operator_overnight_failed", error=str(e))

    async def _run_company_operator_morning_brief(self):
        """Morning company brief for Zero, dashboard, and Reachy."""
        try:
            from app.services.company_operator_service import get_company_operator_service
            result = await get_company_operator_service().generate_report(
                report_type="morning_brief",
                requested_by="scheduler",
            )
            logger.info("company_operator_morning_brief_done", run_id=result.get("id"), status=result.get("status"))
        except Exception as e:
            logger.error("company_operator_morning_brief_failed", error=str(e))

    async def _run_company_operator_evening_report(self):
        """Evening company progress report."""
        try:
            from app.services.company_operator_service import get_company_operator_service
            result = await get_company_operator_service().generate_report(
                report_type="evening_report",
                requested_by="scheduler",
            )
            logger.info("company_operator_evening_report_done", run_id=result.get("id"), status=result.get("status"))
        except Exception as e:
            logger.error("company_operator_evening_report_failed", error=str(e))

    async def _run_company_operator_weekly_review(self):
        """Weekly company review: progress, drift, approvals, and next sprint."""
        try:
            from app.services.company_operator_service import get_company_operator_service
            result = await get_company_operator_service().generate_report(
                report_type="weekly_review",
                requested_by="scheduler",
            )
            logger.info("company_operator_weekly_review_done", run_id=result.get("id"), status=result.get("status"))
        except Exception as e:
            logger.error("company_operator_weekly_review_failed", error=str(e))

    async def _run_company_prompt_eval_bridge(self):
        """Company prompt grading bridge for Legion/Zero prompt experiments."""
        try:
            from app.services.company_operator_service import get_company_operator_service
            result = await get_company_operator_service().run_prompt_eval_bridge(limit=20)
            logger.info("company_prompt_eval_bridge_done", run_id=result.get("id"), status=result.get("status"))
        except Exception as e:
            logger.error("company_prompt_eval_bridge_failed", error=str(e))

    # ============================================
    # CHARACTER CONTENT AUTOMATION
    # ============================================

    async def _run_character_research_refresh(self):
        """Re-research characters with stale data — episode-aware.

        Characters linked to a recent or upcoming release signal (via
        TrendingSignalModel populated by trend_tvmaze_schedule) are treated
        as "in active shows" and refreshed on a 3-day window. Static/legacy
        characters stay on a 14-day window. This stops "From" / "The Boys"
        carousels from citing season-2 facts the week season 3 drops.
        """
        logger.info("running_character_research_refresh")
        try:
            from app.services.character_content_service import get_character_content_service
            from app.db.models import TrendingSignalModel
            from app.infrastructure.database import get_session
            from sqlalchemy import select
            from datetime import datetime, timedelta, timezone, date
            svc = get_character_content_service()

            # Build the set of character_ids tied to recent/upcoming release
            # signals (±14 days). Cheap single query.
            today = date.today()
            window_start = today - timedelta(days=14)
            window_end = today + timedelta(days=14)
            active_ids: set = set()
            async with get_session() as session:
                res = await session.execute(
                    select(TrendingSignalModel.linked_character_ids).where(
                        TrendingSignalModel.signal_type == "release",
                        TrendingSignalModel.release_date.is_not(None),
                        TrendingSignalModel.release_date >= window_start,
                        TrendingSignalModel.release_date <= window_end,
                    )
                )
                for (linked,) in res.all():
                    for cid in (linked or []):
                        if cid:
                            active_ids.add(cid)

            characters = await svc.list_characters(research_status="completed", limit=100)
            now = datetime.now(timezone.utc)
            active_cutoff = now - timedelta(days=3)
            static_cutoff = now - timedelta(days=14)

            refreshed = 0
            active_refreshed = 0
            for char in characters:
                if not char.last_researched:
                    continue
                is_active = char.id in active_ids
                cutoff = active_cutoff if is_active else static_cutoff
                if char.last_researched < cutoff:
                    await svc.research_character(char.id)
                    refreshed += 1
                    if is_active:
                        active_refreshed += 1
                    # Active shows get more throughput per run (6) than static (3).
                    cap = 6 if is_active else 3
                    if refreshed >= cap:
                        break
            logger.info(
                "character_research_refresh_done",
                refreshed=refreshed,
                active_refreshed=active_refreshed,
                active_pool=len(active_ids),
            )
        except Exception as e:
            logger.error("character_research_refresh_failed", error=str(e))

    async def _run_character_research_retry(self):
        """Drain pending + needs_retry characters every 2h. Daily refresh handles
        completed characters; this handler handles backlog so the queue doesn't
        sit for hours after a transient failure."""
        logger.info("running_character_research_retry")
        try:
            from app.services.character_content_service import get_character_content_service
            svc = get_character_content_service()
            attempted = 0
            for status in ("pending", "needs_retry"):
                chars = await svc.list_characters(research_status=status, limit=20)
                for ch in chars:
                    if attempted >= 10:
                        break
                    try:
                        await svc.research_character(ch.id)
                        attempted += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("character_research_retry_item_failed", character_id=ch.id, error=str(exc)[:200])
                if attempted >= 10:
                    break
            logger.info("character_research_retry_done", attempted=attempted)
        except Exception as e:
            logger.error("character_research_retry_failed", error=str(e))

    async def _safe_image_discovery(self, svc, character_id: str) -> None:
        """Background image discovery used by the generation loop.

        Fire-and-forget so the hourly generation job isn't blocked by
        slow SearxNG round-trips for characters with empty image pools.
        """
        try:
            await svc.discover_more_character_images(character_id, max_per_source=8)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "character_image_discovery_bg_failed",
                character_id=character_id,
                error=str(exc)[:200],
            )

    async def _run_character_content_generation(self):
        """Auto-generate carousels for researched characters.

        Phase 4.1 throughput bump:
          - 25 carousels per run (up from 10)
          - Prioritize under-served characters (posts_created asc) within each tier
          - Enforce hook_style variety: cycles through 7 styles, caps any single style at 3/run
        """
        logger.info("running_character_content_generation")
        try:
            from app.services.character_content_service import get_character_content_service
            from app.models.character_content import CarouselCreate, ContentAngle
            import random
            svc = get_character_content_service()

            characters = await svc.list_characters(research_status="completed", limit=200)
            angles = list(ContentAngle)
            # Sort by priority_tier, then by posts_created asc (prioritize under-served characters)
            tier_order = {"priority": 0, "standard": 1, "probation": 2}
            characters.sort(key=lambda c: (
                tier_order.get(getattr(c, "priority_tier", "standard"), 1),
                getattr(c, "posts_created", 0) or 0,
            ))

            # Phase 4.1: hook style variety enforcement
            hook_styles = [
                "numbered_list",
                "story_opener",
                "hot_take",
                "question",
                "comparison",
                "reveal",
                "superlative",
            ]
            hook_style_counts: Dict[str, int] = {s: 0 for s in hook_styles}
            template_counts: Dict[str, int] = {}
            HOOK_STYLE_CAP = 3
            TEMPLATE_CAP = 4

            generated = 0
            failed = 0
            max_per_run = 25
            # Cap how many characters we look at per run so one stuck
            # subsystem (e.g. image discovery) can't burn the whole hour.
            max_visits = max_per_run * 4
            # Cap synchronous image discoveries so the job still finishes even
            # when many characters have empty image pools.
            max_image_discoveries = 5
            image_discoveries = 0
            visits = 0
            for char in characters:
                if generated >= max_per_run:
                    break
                visits += 1
                if visits > max_visits:
                    logger.info(
                        "character_content_generation_visit_cap_reached",
                        visits=visits,
                        generated=generated,
                    )
                    break
                # Skip characters with empty image pool — generating their
                # carousels would just be blocked by CarouselImageMissingError.
                # Image bootstrap fires asynchronously; they'll be eligible on
                # a later tick.
                if not getattr(char, "image_urls", None):
                    logger.info(
                        "character_skipped_no_images",
                        character_id=char.id,
                        character_name=char.name,
                    )
                    if image_discoveries < max_image_discoveries:
                        image_discoveries += 1
                        # Fire-and-forget: don't block the generation loop on
                        # multi-second SearxNG round trips. The character
                        # becomes eligible on a later tick once images land.
                        asyncio.create_task(
                            self._safe_image_discovery(svc, char.id)
                        )
                    continue
                # Rotate angle based on character index for variety
                angle = angles[(generated + hash(char.id)) % len(angles)]

                # Thompson Sampling picks (hook_style, story_template) using
                # historical Stage 2 scores; falls back to rotation for
                # under-sampled pairs. Respect per-run variety caps.
                pick = await svc.pick_next_variant(
                    character_id=char.id, generation_index=generated
                )
                chosen_style = pick["hook_style"]
                chosen_template = pick["story_template"]
                if hook_style_counts.get(chosen_style, 0) >= HOOK_STYLE_CAP:
                    # Fall back to any under-cap style, keep template from picker
                    chosen_style = next(
                        (
                            hook_styles[(generated + offset) % len(hook_styles)]
                            for offset in range(len(hook_styles))
                            if hook_style_counts[hook_styles[(generated + offset) % len(hook_styles)]] < HOOK_STYLE_CAP
                        ),
                        None,
                    )
                if chosen_style is None:
                    logger.info("character_carousel_hook_style_saturated", generated=generated)
                    break
                if template_counts.get(chosen_template, 0) >= TEMPLATE_CAP:
                    # Rotate to next template if this one is saturated for the run
                    chosen_template = None

                try:
                    await svc.generate_carousel(CarouselCreate(
                        character_id=char.id,
                        angle=angle,
                        hook_style=chosen_style,
                        story_template=chosen_template,
                    ))
                    hook_style_counts[chosen_style] = hook_style_counts.get(chosen_style, 0) + 1
                    if chosen_template:
                        template_counts[chosen_template] = template_counts.get(chosen_template, 0) + 1
                    generated += 1
                    logger.info(
                        "character_carousel_generated",
                        character=char.name,
                        angle=angle.value if hasattr(angle, "value") else str(angle),
                        hook_style=chosen_style,
                        story_template=chosen_template,
                        pick_method=pick.get("method"),
                    )
                except Exception as e:
                    failed += 1
                    logger.warning(
                        "character_carousel_generation_item_failed",
                        character=char.name,
                        error=str(e)[:200],
                    )
                    continue
            logger.info(
                "character_content_generation_done",
                generated=generated,
                failed=failed,
                hook_style_distribution=hook_style_counts,
            )
        except Exception as e:
            logger.error("character_content_generation_failed", error=str(e))
            await self._alert_pipeline_failure("character_content_generation", e)

    async def _run_character_content_gate(self):
        """Demand-driven gate: fire an extra generation wave when backlog is low.

        The fixed hourly base cadence is kept; this runs every 15 minutes and
        only actually generates when approved backlog or research queue signals
        demand. Prevents silent drought between hourly runs.
        """
        logger.info("running_character_content_gate")
        try:
            from app.services.character_content_service import get_character_content_service
            svc = get_character_content_service()
            approved_backlog_target = 10
            research_pending_high = 30
            # approved + pending_review counts as "ready to publish" backlog
            approved = await svc.list_carousels(status="approved", limit=100)
            pending = await svc.list_carousels(status="pending_review", limit=100)
            backlog = len(approved) + len(pending)

            from app.db.models import CharacterModel
            from sqlalchemy import func as sa_func, or_
            async with get_session() as session:
                pending_research = await session.execute(
                    select(sa_func.count(CharacterModel.id)).where(
                        or_(
                            CharacterModel.research_status == "pending",
                            CharacterModel.research_status.is_(None),
                        )
                    )
                )
                research_pending = int(pending_research.scalar() or 0)

            should_fire = (
                backlog < approved_backlog_target
                or research_pending > research_pending_high
            )
            logger.info(
                "character_content_gate_eval",
                backlog=backlog,
                approved_backlog_target=approved_backlog_target,
                research_pending=research_pending,
                research_pending_high=research_pending_high,
                should_fire=should_fire,
            )
            if should_fire:
                await self._run_character_content_generation()
        except Exception as e:
            logger.error("character_content_gate_failed", error=str(e))

    async def _run_carousel_watchdog(self):
        """Detect stalled carousel-pipeline jobs and alert.

        A job is stalled if it hasn't completed in 2x its expected interval.
        Resets nothing (APScheduler already reschedules); it exists to surface
        silent failures through alerting + structured logs so the Employee
        Report picks them up.
        """
        logger.info("running_carousel_watchdog")
        try:
            from app.db.models import SchedulerAuditLogModel
            from sqlalchemy import func as sa_func
            watched = {
                "character_content_generation": 60,   # every 1h
                "character_auto_approval": 30,         # every 30m
                "character_final_review_backfill": 20, # every 20m
                "character_auto_research": 120,        # every 2h
                "character_publish_backlog": 120,      # every 2h
                "character_content_gate": 15,          # every 15m
                "media_content_generation": 240,       # every 4h
            }
            now = datetime.utcnow()
            stalled: List[Dict[str, Any]] = []
            async with get_session() as session:
                for job_name, interval_min in watched.items():
                    row = await session.execute(
                        select(sa_func.max(SchedulerAuditLogModel.completed_at)).where(
                            SchedulerAuditLogModel.job_name == job_name,
                            SchedulerAuditLogModel.status == "completed",
                        )
                    )
                    last_done = row.scalar()
                    if last_done is None:
                        stalled.append({
                            "job": job_name,
                            "reason": "never_completed",
                            "expected_interval_min": interval_min,
                        })
                        continue
                    age_min = (now - last_done.replace(tzinfo=None)).total_seconds() / 60.0
                    if age_min > interval_min * 2:
                        stalled.append({
                            "job": job_name,
                            "reason": "stalled",
                            "age_min": round(age_min, 1),
                            "expected_interval_min": interval_min,
                        })
            if stalled:
                logger.warning("carousel_watchdog_stalled", stalled=stalled)
                try:
                    from app.services.notification_service import get_notification_service
                    note_svc = get_notification_service()
                    await note_svc.create_notification(
                        title=f"Carousel watchdog: {len(stalled)} stalled job(s)",
                        message="\n".join(
                            f"- {s['job']}: {s['reason']}"
                            + (f" (age {s['age_min']}m, expected <{s['expected_interval_min']*2}m)" if s.get("age_min") else "")
                            for s in stalled
                        ),
                        channel="discord",
                        source="carousel_watchdog",
                    )
                except Exception as exc:
                    logger.debug("carousel_watchdog_alert_failed", error=str(exc))
            else:
                logger.info("carousel_watchdog_ok", jobs_checked=len(watched))

            # Active rescue passes
            await self._watchdog_rescue_stuck_carousels()
            await self._watchdog_rescue_unimaged_characters()
        except Exception as e:
            logger.error("carousel_watchdog_failed", error=str(e))

    async def _watchdog_rescue_stuck_carousels(self):
        """Re-trigger Stage-2 review for draft carousels older than 2h with
        no final_review_score. These are usually the result of a transient LLM
        failure during the original auto-review fire-and-forget task."""
        try:
            from datetime import timedelta
            from app.db.models import CharacterCarouselModel
            from app.services.character_content_service import get_character_content_service
            cutoff = datetime.utcnow() - timedelta(hours=2)
            async with get_session() as session:
                rows = (await session.execute(
                    select(CharacterCarouselModel.id)
                    .where(CharacterCarouselModel.status == "draft")
                    .where(CharacterCarouselModel.final_review_score.is_(None))
                    .where(CharacterCarouselModel.created_at < cutoff)
                    .limit(20)
                )).scalars().all()
            if not rows:
                return
            svc = get_character_content_service()
            rescued = 0
            for cid in rows:
                try:
                    await svc.ai_review_carousel(cid)
                    rescued += 1
                except Exception as exc:  # noqa: BLE001
                    logger.debug("watchdog_carousel_rescue_failed", carousel_id=cid, error=str(exc)[:200])
            logger.info("watchdog_carousels_rescued", count=rescued, candidates=len(rows))
        except Exception as exc:  # noqa: BLE001
            logger.warning("watchdog_carousel_rescue_pass_failed", error=str(exc)[:200])

    async def _watchdog_rescue_unimaged_characters(self):
        """Re-queue image discovery for any active character with empty image_urls."""
        try:
            from app.db.models import CharacterModel
            from app.services.character_content_service import get_character_content_service
            async with get_session() as session:
                rows = (await session.execute(
                    select(CharacterModel.id, CharacterModel.name)
                    .where(CharacterModel.status == "active")
                    .where((CharacterModel.image_urls.is_(None)) | (CharacterModel.image_urls == []))
                    .limit(10)
                )).all()
            if not rows:
                return
            svc = get_character_content_service()
            for cid, name in rows:
                try:
                    inserted = await svc.discover_more_character_images(cid, max_per_source=8)
                    logger.info("watchdog_character_reimaged", character_id=cid, name=name, inserted=inserted)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("watchdog_character_reimage_failed", character_id=cid, error=str(exc)[:200])
        except Exception as exc:  # noqa: BLE001
            logger.warning("watchdog_character_rescue_pass_failed", error=str(exc)[:200])

    async def _run_character_performance_sync(self):
        """Pull per-carousel TikTok analytics back into character_carousels.

        Was a stub that only logged totals. Now hits TikTok Display API v2 for
        each published carousel whose `publish_url` identifies a TikTok video,
        and writes view/like/comment/share counts + engagement_rate. This is
        the feedback signal PromptBreeder / variant-stats consume when ranking
        hook_style + story_template combinations.
        """
        import re
        logger.info("running_character_performance_sync")
        try:
            from app.services.character_content_service import get_character_content_service
            from app.db.models import CharacterCarouselModel
            from app.infrastructure.database import get_session
            from app.infrastructure.tiktok_api_client import get_tiktok_api_client
            from sqlalchemy import select
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td

            svc = get_character_content_service()
            stats = await svc.get_stats()

            client = get_tiktok_api_client()
            if not client.is_configured:
                logger.info(
                    "character_performance_sync_skipped_no_tiktok",
                    characters=stats.total_characters,
                    carousels=stats.total_carousels,
                    published=stats.total_published,
                )
                return
            await client.load_tokens_from_db()
            if not client.is_authorized:
                logger.info(
                    "character_performance_sync_skipped_no_auth",
                    published=stats.total_published,
                )
                return

            # Candidates: published carousels with a publish_url and either no
            # views yet OR last sync > 6h old (heuristic: use published_at as
            # proxy — we re-sync any row whose published_at is within 30 days
            # so recent content gets fresh numbers; older rows skip).
            cutoff = _dt.now(_tz.utc) - _td(days=30)
            async with get_session() as session:
                res = await session.execute(
                    select(CharacterCarouselModel)
                    .where(
                        CharacterCarouselModel.status == "published",
                        CharacterCarouselModel.publish_url.is_not(None),
                        CharacterCarouselModel.published_at.is_not(None),
                        CharacterCarouselModel.published_at >= cutoff,
                    )
                    .limit(200)
                )
                rows = list(res.scalars().all())

            # Extract TikTok video_id from publish_url like
            #   https://www.tiktok.com/@user/video/7123456789012345678
            pattern = re.compile(r"/video/(\d{15,25})")
            vid_to_row = {}
            for row in rows:
                m = pattern.search(row.publish_url or "")
                if m:
                    vid_to_row[m.group(1)] = row
            video_ids = list(vid_to_row.keys())
            synced = 0
            for start in range(0, len(video_ids), 20):
                batch = video_ids[start:start + 20]
                metrics = await client.query_video_metrics(batch)
                if not metrics:
                    continue
                async with get_session() as session:
                    for v in metrics:
                        row = vid_to_row.get(str(v.get("id")))
                        if row is None:
                            continue
                        fresh = await session.get(CharacterCarouselModel, row.id)
                        if fresh is None:
                            continue
                        fresh.views = int(v.get("view_count") or 0)
                        fresh.likes = int(v.get("like_count") or 0)
                        fresh.comments = int(v.get("comment_count") or 0)
                        fresh.shares = int(v.get("share_count") or 0)
                        total_actions = (fresh.likes or 0) + (fresh.comments or 0) + (fresh.shares or 0)
                        if fresh.views and fresh.views > 0:
                            fresh.engagement_rate = float(total_actions) / float(fresh.views)
                        synced += 1
                    await session.commit()

            logger.info(
                "character_performance_sync_done",
                characters=stats.total_characters,
                carousels=stats.total_carousels,
                published=stats.total_published,
                candidates=len(video_ids),
                synced=synced,
            )
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

    async def _run_character_reference_video_learning(self):
        """Auto-apply facts + style exemplars from analyzed reference videos."""
        try:
            from app.services.character_reference_video_service import (
                get_character_reference_video_service,
            )
            service = get_character_reference_video_service()
            stats = await service.apply_learnings(batch_size=20)
            if stats.get("scanned"):
                logger.info("character_reference_video_learning_tick", **stats)
        except Exception as e:
            logger.error("character_reference_video_learning_failed", error=str(e))

    async def _run_carousel_reaudit(self):
        """Re-audit a rolling batch of carousels and auto-remediate Tier 1/2 issues."""
        try:
            from app.services.carousel_audit_service import get_carousel_audit_service
            stats = await get_carousel_audit_service().run_batch(batch_size=20)
            if stats.get("scanned"):
                logger.info("carousel_reaudit_tick", **stats)
        except Exception as e:
            logger.error("carousel_reaudit_failed", error=str(e))

    async def _run_entity_research_deepen(self):
        """Deep-research the lowest-depth entities (characters/TV/movies)."""
        try:
            from app.services.entity_research_service import get_entity_research_service
            stats = await get_entity_research_service().deepen_lowest_depth(batch_size=3)
            if stats.get("scanned"):
                logger.info("entity_research_deepen_tick", **stats)
        except Exception as e:
            logger.error("entity_research_deepen_failed", error=str(e))

    async def _run_employee_checkin(self):
        """Aggregate subsystem reports into an EmployeeCheckin row + Legion tasks."""
        try:
            from app.services.employee_checkin_service import get_employee_checkin_service
            result = await get_employee_checkin_service().run_checkin()
            logger.info("employee_checkin_tick", overall=result.get("overall_grade"))
        except Exception as e:
            logger.error("employee_checkin_failed", error=str(e))

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

    async def _run_character_auto_research(self):
        """Auto-start research for pending characters if the queue is idle."""
        if self._autopilot_disabled("character_auto_research"):
            return
        try:
            from app.services.character_content_service import get_character_content_service, _research_queue
            if _research_queue.get("running"):
                logger.debug("character_auto_research_skipped_running")
                return
            svc = get_character_content_service()
            pending = await svc.list_characters(research_status="pending", limit=1)
            if not pending:
                logger.debug("character_auto_research_skipped_none_pending")
                return
            logger.info("character_auto_research_starting")
            await svc.start_batch_research_async(limit=24)
        except Exception as e:
            logger.error("character_auto_research_failed", error=str(e))

    # ============================================
    # MEDIA CONTENT AUTOMATION (TV shows + movies)
    # ============================================

    async def _run_media_auto_research(self):
        """Auto-research pending media titles (TV/movie), up to 3 per run.

        Resets any title stuck in 'researching' for >30 min to 'pending' first —
        `research_media_title` sets the status at the start of its run and
        leaves it there if the process is killed mid-pipeline (e.g. container
        restart), so without this reset orphaned titles stay stuck forever.
        """
        if self._autopilot_disabled("media_auto_research"):
            return
        logger.info("running_media_auto_research")
        try:
            from app.services.media_content_service import get_media_content_service
            from app.db.models import MediaTitleModel
            from app.infrastructure.database import get_session
            from datetime import datetime, timedelta, timezone
            from sqlalchemy import select, or_
            from sqlalchemy.exc import SQLAlchemyError
            svc = get_media_content_service()

            # Reset stuck 'researching' titles older than 30 min
            stuck_cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
            reset_count = 0
            async with get_session() as session:
                stuck_rows = await session.execute(
                    select(MediaTitleModel).where(
                        MediaTitleModel.research_status == "researching",
                        or_(
                            MediaTitleModel.last_researched == None,  # noqa: E711
                            MediaTitleModel.last_researched < stuck_cutoff,
                        ),
                    )
                )
                for row in stuck_rows.scalars().all():
                    row.research_status = "pending"
                    reset_count += 1
                if reset_count:
                    await session.commit()
                    logger.info("media_auto_research_reset_stuck", count=reset_count)

            pending = await svc.list_media_titles(research_status="pending", limit=6)
            if not pending:
                logger.debug("media_auto_research_skipped_none_pending")
                return

            async def _research_one(title):
                try:
                    await svc.research_media_title(title.id)
                    logger.info(
                        "media_auto_research_item_done",
                        title=title.title,
                        media_type=title.media_type,
                    )
                    return ("ok", title.id, None)
                except (ValueError, RuntimeError, KeyError, AttributeError, TypeError) as e:
                    try:
                        async with get_session() as session:
                            row = await session.get(MediaTitleModel, title.id)
                            if row and row.research_status == "researching":
                                row.research_status = "failed"
                                if not isinstance(row.research_data, dict):
                                    row.research_data = {}
                                row.research_data["error"] = str(e)[:300]
                                await session.commit()
                    except (RuntimeError, SQLAlchemyError):
                        pass
                    logger.warning(
                        "media_auto_research_item_failed",
                        title=title.title,
                        error=str(e)[:200],
                    )
                    return ("fail", title.id, str(e)[:200])

            # Run up to 3 concurrently so the batch doesn't slam Ollama; the
            # underlying research_media_title does a single LLM synthesis per
            # title, so 3 in flight is safe alongside any character jobs.
            sem = asyncio.Semaphore(3)
            async def _guarded(t):
                async with sem:
                    return await _research_one(t)

            results = await asyncio.gather(*(_guarded(t) for t in pending), return_exceptions=False)
            researched = sum(1 for r in results if r[0] == "ok")
            failed = sum(1 for r in results if r[0] == "fail")
            logger.info("media_auto_research_done", researched=researched, failed=failed)
        except Exception as e:
            logger.error("media_auto_research_failed", error=str(e))

    async def _run_media_content_generation(self):
        """Auto-generate carousels for researched media titles, up to 10 per run.

        Prioritizes titles with the fewest carousels (underserved-first).
        Rotates across all MediaContentAngle values for variety.
        """
        if self._autopilot_disabled("media_content_generation"):
            return
        logger.info("running_media_content_generation")
        try:
            from app.services.media_content_service import get_media_content_service
            from app.models.media_content import MediaCarouselCreate, MediaContentAngle
            svc = get_media_content_service()

            titles = await svc.list_media_titles(research_status="completed", limit=100)
            if not titles:
                logger.debug("media_content_generation_skipped_none_ready")
                return

            angles = list(MediaContentAngle)
            titles.sort(key=lambda t: getattr(t, "carousels_created", 0))

            generated = 0
            failed = 0
            max_per_run = 10
            # Rotate hook_style + story_template deterministically so the
            # media pipeline matches the character pipeline's variety instead
            # of leaving both NULL (which kills PromptBreeder evaluation and
            # defaults the LLM to a generic hook).
            from app.models.character_content import HookStyle
            hook_styles = [hs.value for hs in HookStyle]
            story_template_rotation = [
                "secrets_revealed", "dark_origin", "fan_theory_deep_dive",
                "hot_take", "timeline_tragedy", "hidden_connection",
                "actor_behind_role",
            ]
            for title in titles:
                if generated >= max_per_run:
                    break
                angle = angles[(generated + hash(title.id)) % len(angles)]
                chosen_style = hook_styles[(generated + hash(title.id)) % len(hook_styles)]
                chosen_template = story_template_rotation[
                    (generated + hash(title.id)) % len(story_template_rotation)
                ]
                try:
                    await svc.generate_carousel(MediaCarouselCreate(
                        media_title_id=title.id,
                        angle=angle,
                        hook_style=chosen_style,
                        story_template=chosen_template,
                    ))
                    generated += 1
                    logger.info(
                        "media_carousel_generated",
                        title=title.title,
                        angle=angle.value if hasattr(angle, "value") else str(angle),
                        hook_style=chosen_style,
                        story_template=chosen_template,
                    )
                except (ValueError, RuntimeError, KeyError, AttributeError, TypeError) as e:
                    failed += 1
                    logger.warning(
                        "media_carousel_generation_item_failed",
                        title=title.title,
                        error=str(e)[:200],
                    )
                    continue
            logger.info("media_content_generation_done", generated=generated, failed=failed)
        except Exception as e:
            logger.error("media_content_generation_failed", error=str(e))

    # ============================================
    # TREND INTELLIGENCE HANDLERS
    # ============================================

    async def _run_trend_release_calendar_sync(self):
        logger.info("running_trend_release_calendar_sync")
        try:
            from app.services.trend_intelligence_service import get_trend_intelligence_service
            svc = get_trend_intelligence_service()
            result = await svc.fetch_tmdb_upcoming()
            logger.info("trend_release_calendar_sync_done", result=result)
        except Exception as e:
            logger.error("trend_release_calendar_sync_failed", error=str(e))

    async def _run_trend_tvmaze_schedule(self):
        logger.info("running_trend_tvmaze_schedule")
        try:
            from app.services.trend_intelligence_service import get_trend_intelligence_service
            svc = get_trend_intelligence_service()
            result = await svc.fetch_tvmaze_schedule()
            logger.info("trend_tvmaze_schedule_done", result=result)
        except Exception as e:
            logger.error("trend_tvmaze_schedule_failed", error=str(e))

    async def _run_trend_reddit_pulse(self):
        logger.info("running_trend_reddit_pulse")
        try:
            from app.services.trend_intelligence_service import get_trend_intelligence_service
            svc = get_trend_intelligence_service()
            result = await svc.fetch_reddit_rising()
            logger.info("trend_reddit_pulse_done", result=result)
        except Exception as e:
            logger.error("trend_reddit_pulse_failed", error=str(e))

    async def _run_trend_searxng_pulse(self):
        logger.info("running_trend_searxng_pulse")
        try:
            from app.services.trend_intelligence_service import get_trend_intelligence_service
            svc = get_trend_intelligence_service()
            result = await svc.fetch_searxng_pulse()
            logger.info("trend_searxng_pulse_done", result=result)
        except Exception as e:
            logger.error("trend_searxng_pulse_failed", error=str(e))

    async def _run_trend_linker(self):
        logger.info("running_trend_linker")
        try:
            from app.services.trend_intelligence_service import get_trend_intelligence_service
            from app.services.character_discovery_service import get_character_discovery_service
            tsvc = get_trend_intelligence_service()
            result = await tsvc.link_unprocessed(limit=50)
            # For newly-linked signals, route release-type ones through character discovery
            # to elevate priority_tier for matched characters and propose from franchise when new.
            from app.db.models import TrendingSignalModel
            from app.infrastructure.database import get_session
            from sqlalchemy import select
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
            async with get_session() as session:
                sres = await session.execute(
                    select(TrendingSignalModel).where(
                        TrendingSignalModel.processed_at.is_not(None),
                        TrendingSignalModel.processed_at >= cutoff,
                        TrendingSignalModel.signal_type == "release",
                    ).limit(30)
                )
                recent = [row.id for row in sres.scalars().all()]
            dsvc = get_character_discovery_service()
            for sid in recent:
                try:
                    await dsvc.from_trend_signal(sid)
                except Exception as e:  # noqa: BLE001
                    logger.debug("trend_linker_discovery_skip", signal_id=sid, error=str(e))
            logger.info("trend_linker_done", linker=result, discovery_passes=len(recent))
        except Exception as e:
            logger.error("trend_linker_failed", error=str(e))

    async def _run_trend_scorer(self):
        logger.info("running_trend_scorer")
        try:
            from app.services.trend_intelligence_service import get_trend_intelligence_service
            svc = get_trend_intelligence_service()
            result = await svc.score_unscored_signals(limit=20)
            logger.info("trend_scorer_done", result=result)
        except Exception as e:
            logger.error("trend_scorer_failed", error=str(e))

    async def _run_trend_signal_cleanup(self):
        logger.info("running_trend_signal_cleanup")
        try:
            from app.services.trend_intelligence_service import get_trend_intelligence_service
            svc = get_trend_intelligence_service()
            result = await svc.cleanup_expired()
            logger.info("trend_signal_cleanup_done", deleted=result.get("deleted"))
        except Exception as e:
            logger.error("trend_signal_cleanup_failed", error=str(e))

    async def _run_character_release_prep(self):
        """For characters linked to release-bearing signals in [today+3, today+14],
        queue a 3-carousel generation burst with angle rotation."""
        logger.info("running_character_release_prep")
        if self._autopilot_disabled("character_release_prep"):
            return
        try:
            from app.db.models import TrendingSignalModel, CharacterModel, CharacterCarouselModel
            from app.infrastructure.database import get_session
            from app.services.character_content_service import get_character_content_service
            from app.models.character_content import CarouselCreate, ContentAngle
            from sqlalchemy import select
            from datetime import date, datetime, timedelta, timezone

            svc = get_character_content_service()
            today = date.today()
            window_end = today + timedelta(days=14)
            window_start = today + timedelta(days=3)

            burst_angles = [ContentAngle.BEHIND_SCENES, ContentAngle.HIDDEN_TRUTHS, ContentAngle.POWER_SECRETS]
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            generated = 0
            skipped = 0

            async with get_session() as session:
                sres = await session.execute(
                    select(TrendingSignalModel).where(
                        TrendingSignalModel.signal_type == "release",
                        TrendingSignalModel.release_date.is_not(None),
                        TrendingSignalModel.release_date >= window_start,
                        TrendingSignalModel.release_date <= window_end,
                    )
                )
                signals = list(sres.scalars().all())

            for signal in signals:
                for ch_id in (signal.linked_character_ids or []):
                    async with get_session() as session:
                        cres = await session.execute(
                            select(CharacterModel).where(
                                CharacterModel.id == ch_id,
                                CharacterModel.research_status == "completed",
                            )
                        )
                        ch = cres.scalars().first()
                        if ch is None:
                            continue
                        # Skip if already released-triggered content recently
                        rec = await session.execute(
                            select(CharacterCarouselModel).where(
                                CharacterCarouselModel.character_id == ch_id,
                                CharacterCarouselModel.created_at >= seven_days_ago,
                            )
                        )
                        if rec.scalars().first() is not None:
                            skipped += 1
                            continue

                    for angle in burst_angles:
                        try:
                            # Pull hook_style + story_template from the
                            # Thompson picker so release-prep bursts inherit
                            # the same variety/learning as the main generation
                            # loop (was previously skipping both → most of
                            # these rows had hook_style=NULL, which silently
                            # disables PromptBreeder evaluation).
                            variant_pick = {}
                            try:
                                variant_pick = await svc.pick_next_variant(
                                    character_id=ch_id,
                                    generation_index=generated,
                                )
                            except Exception:  # noqa: BLE001
                                pass
                            await svc.generate_carousel(CarouselCreate(
                                character_id=ch_id,
                                angle=angle,
                                hook_style=variant_pick.get("hook_style"),
                                story_template=variant_pick.get("story_template"),
                            ))
                            generated += 1
                        except Exception as e:  # noqa: BLE001
                            logger.warning(
                                "character_release_prep_item_failed",
                                character_id=ch_id,
                                signal_id=signal.id,
                                error=str(e)[:200],
                            )

                # Mark signal as having triggered content
                if (signal.linked_character_ids or []):
                    async with get_session() as session:
                        sr = await session.execute(
                            select(TrendingSignalModel).where(TrendingSignalModel.id == signal.id)
                        )
                        row = sr.scalars().first()
                        if row is not None:
                            row.triggered_content_at = datetime.now(timezone.utc)
                            await session.commit()

            logger.info("character_release_prep_done", generated=generated, skipped=skipped, signals=len(signals))
        except Exception as e:
            logger.error("character_release_prep_failed", error=str(e))

    async def _run_media_release_prep(self):
        """Queue carousel generation for media titles linked to near-release signals."""
        logger.info("running_media_release_prep")
        if self._autopilot_disabled("media_release_prep"):
            return
        try:
            from app.db.models import TrendingSignalModel, MediaTitleModel
            from app.infrastructure.database import get_session
            from app.services.media_content_service import get_media_content_service
            from app.models.media_content import MediaCarouselCreate, MediaContentAngle
            from sqlalchemy import select
            from datetime import date, timedelta

            svc = get_media_content_service()
            today = date.today()
            window_start = today + timedelta(days=3)
            window_end = today + timedelta(days=14)
            generated = 0
            failed = 0

            async with get_session() as session:
                sres = await session.execute(
                    select(TrendingSignalModel).where(
                        TrendingSignalModel.signal_type == "release",
                        TrendingSignalModel.release_date.is_not(None),
                        TrendingSignalModel.release_date >= window_start,
                        TrendingSignalModel.release_date <= window_end,
                    )
                )
                signals = list(sres.scalars().all())

            for signal in signals:
                for mt_id in (signal.linked_media_title_ids or []):
                    async with get_session() as session:
                        mres = await session.execute(
                            select(MediaTitleModel).where(
                                MediaTitleModel.id == mt_id,
                                MediaTitleModel.research_status == "completed",
                            )
                        )
                        mt = mres.scalars().first()
                        if mt is None:
                            continue

                    try:
                        # Rotate hook_style/template so release-prep media
                        # bursts also inherit variety (previously both NULL).
                        from app.models.character_content import HookStyle as _HS
                        _hs_list = [hs.value for hs in _HS]
                        _tpl_list = [
                            "secrets_revealed", "dark_origin", "timeline_tragedy",
                            "fan_theory_deep_dive", "hot_take",
                        ]
                        _idx = generated + hash(mt_id)
                        await svc.generate_carousel(MediaCarouselCreate(
                            media_title_id=mt_id,
                            angle=MediaContentAngle.CULTURAL_IMPACT,
                            hook_style=_hs_list[_idx % len(_hs_list)],
                            story_template=_tpl_list[_idx % len(_tpl_list)],
                        ))
                        generated += 1
                    except Exception as e:  # noqa: BLE001
                        failed += 1
                        logger.warning(
                            "media_release_prep_item_failed",
                            media_title_id=mt_id,
                            signal_id=signal.id,
                            error=str(e)[:200],
                        )

            logger.info("media_release_prep_done", generated=generated, failed=failed, signals=len(signals))
        except Exception as e:
            logger.error("media_release_prep_failed", error=str(e))

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
    # CONTENT BRAIN v2 ACCELERATORS
    # ============================================

    async def _run_brain_prompt_breed(self):
        logger.info("running_brain_prompt_breed")
        try:
            from app.services.prompt_breeder_service import get_prompt_breeder_service
            svc = get_prompt_breeder_service()
            # Focus on carousel generation + hook rewriting prompts where breeding matters most
            result = await svc.breed_all(task_types=[
                "carousel_generation",
                "character_research",
                "hook_rewrite",
                "fact_extraction",
            ])
            logger.info("brain_prompt_breed_done", result=result)
        except Exception as e:
            logger.error("brain_prompt_breed_failed", error=str(e))

    async def _run_competitor_scrape(self):
        logger.info("running_competitor_scrape")
        try:
            from app.services.competitor_content_service import get_competitor_content_service
            svc = get_competitor_content_service()
            result = await svc.scrape_all(per_niche=15)
            logger.info("competitor_scrape_done", result=result)
        except Exception as e:
            logger.error("competitor_scrape_failed", error=str(e))

    async def _run_competitor_cleanup(self):
        logger.info("running_competitor_cleanup")
        try:
            from app.services.competitor_content_service import get_competitor_content_service
            svc = get_competitor_content_service()
            result = await svc.cleanup_expired()
            logger.info("competitor_cleanup_done", deleted=result.get("deleted"))
        except Exception as e:
            logger.error("competitor_cleanup_failed", error=str(e))

    async def _run_character_hook_style_report(self):
        """Compute per-hook-style engagement and store as an episodic memory
        (so the Strategist role can query it during swarm votes)."""
        logger.info("running_character_hook_style_report")
        try:
            from app.db.models import CharacterCarouselModel, ContentPerformanceModel, EpisodicMemoryModel
            from app.infrastructure.database import get_session
            from sqlalchemy import select
            from datetime import datetime, timedelta, timezone
            import uuid as _uuid

            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            async with get_session() as session:
                res = await session.execute(
                    select(CharacterCarouselModel, ContentPerformanceModel)
                    .join(
                        ContentPerformanceModel,
                        ContentPerformanceModel.carousel_id == CharacterCarouselModel.id,
                        isouter=True,
                    )
                    .where(CharacterCarouselModel.created_at >= cutoff)
                )
                rows = list(res.all())

            buckets: Dict[str, Dict[str, Any]] = {}
            for carousel, perf in rows:
                meta = carousel.generation_metadata or {}
                style = (meta.get("hook_style") or carousel.hook_style or "unknown")
                bucket = buckets.setdefault(style, {"n": 0, "engagement_sum": 0.0, "views_sum": 0})
                bucket["n"] += 1
                if perf is not None:
                    eng = (perf.engagement_rate or 0.0)
                    bucket["engagement_sum"] += float(eng or 0.0)
                    bucket["views_sum"] += int(perf.views or 0)

            report_lines: List[str] = []
            for style, b in sorted(buckets.items(), key=lambda kv: kv[1]["engagement_sum"], reverse=True):
                avg_eng = (b["engagement_sum"] / b["n"]) if b["n"] else 0.0
                report_lines.append(
                    f"{style}: n={b['n']} avg_engagement={avg_eng:.4f} views={b['views_sum']}"
                )
            report = "Hook style engagement report (last 30d):\n" + "\n".join(report_lines)

            async with get_session() as session:
                session.add(EpisodicMemoryModel(
                    id=f"em-{_uuid.uuid4().hex[:12]}",
                    namespace="content",
                    content=report,
                    source_type="hook_style_report",
                    importance=70.0,
                    tags=["hook_style", "content_brain_v2"],
                    context={"buckets": buckets},
                ))
                await session.commit()

            logger.info("character_hook_style_report_done", styles=len(buckets))
        except Exception as e:
            logger.error("character_hook_style_report_failed", error=str(e))

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

    async def set_job_enabled(self, job_name: str, enabled: bool) -> Dict[str, Any]:
        """Persist and apply a single job's enabled state."""
        if job_name not in self._known_job_names():
            return {"success": False, "error": f"Unknown job: {job_name}"}

        self._enabled_overrides[job_name] = bool(enabled)
        await self._save_enabled_overrides()
        applied = self._apply_runtime_enabled(job_name, bool(enabled))
        if not enabled:
            await self._after_disable_actions(job_name)

        job = self.scheduler.get_job(job_name)
        return {
            "success": True,
            "job_name": job_name,
            "enabled": bool(enabled),
            "applied": applied,
            "job": self._serialize_job(job_name, job),
        }

    async def set_jobs_enabled(self, job_names: List[str], enabled: bool) -> Dict[str, Any]:
        """Persist and apply a bulk enabled-state update."""
        normalized = [str(name) for name in job_names if str(name).strip()]
        unknown = [name for name in normalized if name not in self._known_job_names()]
        if unknown:
            return {
                "success": False,
                "error": f"Unknown job(s): {', '.join(unknown)}",
                "unknown_jobs": unknown,
            }

        for job_name in normalized:
            self._enabled_overrides[job_name] = bool(enabled)
        await self._save_enabled_overrides()

        updated = []
        for job_name in normalized:
            applied = self._apply_runtime_enabled(job_name, bool(enabled))
            if not enabled:
                await self._after_disable_actions(job_name)
            updated.append({
                "job_name": job_name,
                "enabled": bool(enabled),
                "applied": applied,
                "job": self._serialize_job(job_name, self.scheduler.get_job(job_name)),
            })

        return {
            "success": True,
            "enabled": bool(enabled),
            "updated": updated,
            "count": len(updated),
        }

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
        """Get a lightweight scheduler status snapshot without DB access."""
        live = self._runtime_job_lookup()
        names = sorted(set(DAILY_SCHEDULE) | set(live), key=lambda n: (get_job_category(n), n))
        jobs = [self._serialize_job(name, live.get(name)) for name in names]

        return {
            "running": self._running,
            "jobs": jobs,
            "job_count": len(live),
            "total_jobs": len(jobs),
            "enabled_jobs": len([job for job in jobs if job["enabled"]]),
            "disabled_jobs": len([job for job in jobs if not job["enabled"]]),
        }

    async def get_status_detailed(self) -> Dict[str, Any]:
        """Get scheduler status with audit-derived health and last-run data."""
        live = self._runtime_job_lookup()
        names = sorted(set(DAILY_SCHEDULE) | set(live), key=lambda n: (get_job_category(n), n))
        stats = await self.get_recent_job_stats(hours=24)
        jobs = [self._serialize_job(name, live.get(name), stats.get(name)) for name in names]

        return {
            "running": self._running,
            "jobs": jobs,
            "job_count": len(live),
            "total_jobs": len(jobs),
            "enabled_jobs": len([job for job in jobs if job["enabled"]]),
            "disabled_jobs": len([job for job in jobs if not job["enabled"]]),
        }

    # ------------------------------------------------------------------
    # Orchestration hardening handlers (migration 035)
    # ------------------------------------------------------------------

    async def _run_autonomous_content_loop(self):
        """W2: pull trending signals and drive carousel generation."""
        from app.services.autonomous_content_loop_service import get_autonomous_content_loop_service
        svc = get_autonomous_content_loop_service()
        result = await svc.run_once()
        logger.info("scheduler_autonomous_content_loop", **result)

    async def _run_swarm_calibration(self):
        """W4: recompute swarm role weights from recent outcomes."""
        from app.services.content_swarm_service import get_content_swarm_service
        svc = get_content_swarm_service()
        result = await svc.run_calibration(lookback_days=30)
        logger.info(
            "scheduler_swarm_calibration",
            samples_total=result.get("samples_total"),
            weights=result.get("weights"),
        )

    async def _run_lore_ingestion(self):
        """W5: chunk + embed character research into character_lore_chunks."""
        from app.services.lore_ingestion_service import get_lore_ingestion_service
        svc = get_lore_ingestion_service()
        result = await svc.ingest_all(limit=50)  # cap per nightly run; scales up later
        logger.info("scheduler_lore_ingestion", **result)

    async def _run_carousel_partition_maintenance(self):
        """W6: create next-month partitions ahead of time on partitioned tables."""
        from app.services.partition_maintenance_service import get_partition_maintenance_service
        svc = get_partition_maintenance_service()
        result = await svc.ensure_future_partitions()
        logger.info("scheduler_partition_maintenance", **result)

    # ============================================
    # Cross-project loops (autoresearch pattern)
    # ============================================

    async def _run_loop_tick(self):
        """Pick the next-due enabled loop(s) and dispatch them serially.

        Per the master plan: Zero is the orchestrator. This tick is the
        heartbeat of the cross-project self-improvement substrate.
        """
        from app.services.loop_runner_service import get_loop_runner
        runner = get_loop_runner()
        results = await runner.run_due(max_runs=3)
        logger.info("scheduler_loop_tick", dispatched=len(results))

    async def _run_loop_judge(self):
        """Score recent unscored runs via local Qwen judge (P2 wires the service)."""
        try:
            from app.services.loop_judge_service import get_loop_judge  # noqa: F401
        except ImportError:
            logger.debug("loop_judge_service_not_yet_available")
            return
        from app.services.loop_judge_service import get_loop_judge
        judge = get_loop_judge()
        result = await judge.score_recent_runs(limit=10)
        logger.info("scheduler_loop_judge", **result)

    async def _run_loop_promote(self):
        """Evaluate canary -> active promotion (autoresearch policy). P2."""
        try:
            from app.services.loop_promotion_service import get_loop_promotion  # noqa: F401
        except ImportError:
            logger.debug("loop_promotion_service_not_yet_available")
            return
        from app.services.loop_promotion_service import get_loop_promotion
        promo = get_loop_promotion()
        result = await promo.evaluate_all()
        logger.info("scheduler_loop_promote", **result)

    async def _run_loop_crosspoll(self):
        """Fanout learnings ADA <-> Legion <-> Zero. P3."""
        try:
            from app.services.loop_crosspoll_service import get_loop_crosspoll  # noqa: F401
        except ImportError:
            logger.debug("loop_crosspoll_service_not_yet_available")
            return
        from app.services.loop_crosspoll_service import get_loop_crosspoll
        cp = get_loop_crosspoll()
        result = await cp.fanout_pending(min_confidence=0.6, limit=20)
        logger.info("scheduler_loop_crosspoll", **result)

    async def _run_loop_health(self):
        """Replay buffer flush + Legion fragility tripwire + stuck-run reaper."""
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import select, update as sa_update
        from app.db.models import LoopRunModel
        from app.infrastructure.database import get_session
        from app.services.loop_report_sink_client import get_loop_sink

        # Reap runs that have been stuck in 'running' for >1h. This catches
        # OpenCode daemon crashes mid-job, container restarts during a long
        # LLM call, and any other path where mark_run_completed never fires.
        async with get_session() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            stmt = sa_update(LoopRunModel).where(
                LoopRunModel.status == "running",
                LoopRunModel.started_at < cutoff,
            ).values(
                status="timeout",
                ended_at=datetime.now(timezone.utc),
                error="reaped: stuck in running > 1h",
            ).execution_options(synchronize_session=False)
            result = await session.execute(stmt)
            await session.commit()
            reaped = result.rowcount or 0
            if reaped:
                logger.warning("loop.reaped_stuck_runs", count=reaped)

        sink = get_loop_sink()
        replay = await sink.replay_buffer(max_batch=50)

        # Legion fragility tripwire: track consecutive deep-health failures so
        # we surface a vault alert if PromptEvaluatorAgent's global-on setting
        # is amplifying instability. Operator (Adam) reverts via .env edit.
        health = await sink.check_legion_health()
        state = getattr(self, "_legion_health_state", {"consecutive_failures": 0})
        if health.get("ok"):
            if state.get("consecutive_failures", 0) >= 3:
                logger.info("legion_health_recovered")
            state = {"consecutive_failures": 0}
        else:
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            if state["consecutive_failures"] == 3:
                logger.warning(
                    "legion_health_tripwire",
                    consecutive=state["consecutive_failures"],
                    last_response=health,
                )
                # Best-effort vault alert; ignore failures.
                try:
                    from datetime import datetime, timezone
                    from app.services.vault_writer_service import get_vault_writer
                    vault = get_vault_writer()
                    if vault.available():
                        vault.write_agent_file(
                            relative_path=f"00_Meta/_agent/loops/_alerts/{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-legion-tripwire.md",
                            content=(
                                "# Legion fragility tripwire\n\n"
                                f"Legion `/health` returned non-2xx 3 times consecutively.\n\n"
                                f"Last response: `{health}`\n\n"
                                "Action: consider setting `ENABLE_PROMPT_EVALUATOR=false` in "
                                "`C:\\code\\Legion\\.env` and restarting `legion-backend`. "
                                "The PromptEvaluatorAgent is currently global-on per the "
                                "user's Plan-mode decision.\n"
                            ),
                            source="loop_health_tripwire",
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("legion_tripwire_alert_write_failed", error=str(exc))

        self._legion_health_state = state

        logger.info(
            "scheduler_loop_health",
            breaker=sink.breaker_state,
            buffered=sink.buffer_count(),
            legion_ok=health.get("ok"),
            legion_consecutive_failures=state.get("consecutive_failures", 0),
            **replay,
        )

    async def _run_memory_vault_daily_digest(self):
        """Roll up yesterday's vault entries into one global digest file.

        Walks every Source-tree entry created in the last 24 h, formats a
        short markdown summary per source, and writes the combined text to
        ``vault/global/{yyyymmdd}.md`` via the Memory Tree service. This is
        the openhuman "Global tree" pattern — one place to read what the
        agent saw across all sources for the day.
        """
        from datetime import datetime, timedelta, timezone
        try:
            from app.services.memory_tree import get_memory_tree
            from app.services.memory_tree.vault import list_entries
        except Exception as e:
            logger.warning("memory_vault_digest_import_failed", error=str(e))
            return

        tree = get_memory_tree()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        cutoff_iso = cutoff.isoformat(timespec="seconds")

        entries = list_entries(tree.root, scope="source")
        recent_by_source: dict[str, list] = {}
        for entry in entries:
            created = entry.frontmatter.get("created", "")
            if not created or created.replace("Z", "") < cutoff_iso:
                continue
            src = entry.frontmatter.get("source", "unknown")
            recent_by_source.setdefault(src, []).append(entry)

        if not recent_by_source:
            logger.info("memory_vault_digest_skipped", reason="no_fresh_chunks")
            return

        sections: list[str] = []
        for src, items in sorted(recent_by_source.items()):
            lines = [f"## {src} ({len(items)} chunk(s))"]
            for e in items[:10]:
                title = e.frontmatter.get("title", e.path.stem)
                preview = e.body[:160].replace("\n", " ")
                lines.append(f"- **{title}** — {preview}…")
            sections.append("\n".join(lines))

        body = (
            f"Daily digest for {datetime.utcnow().strftime('%Y-%m-%d')} UTC.\n"
            f"Sources covered: {len(recent_by_source)}, chunks: "
            f"{sum(len(v) for v in recent_by_source.values())}.\n\n"
            + "\n\n".join(sections)
        )
        path = await tree.write_global_digest(
            body,
            title=f"Daily digest {datetime.utcnow().strftime('%Y-%m-%d')}",
            sources=sorted(recent_by_source.keys()),
        )
        logger.info("memory_vault_digest_written", path=str(path))


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
