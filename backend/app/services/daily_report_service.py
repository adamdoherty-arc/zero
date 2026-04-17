"""
Daily Autonomous Report Service for ZERO.

Aggregates results from all autonomous systems and generates a comprehensive
daily report delivered via Discord and stored in the database.

Reports cover:
- Scheduler job execution results (successes, failures, durations)
- LLM usage and budget
- Enhancement/improvement activity
- TikTok pipeline status
- System health (providers, services, disk)
- Investigation of failed/missing jobs
"""

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog

from app.infrastructure.config import get_workspace_path
from app.infrastructure.database import get_session
from app.infrastructure.storage import JsonStorage
from app.db.models import SchedulerAuditLogModel

from sqlalchemy import select, func as sa_func

logger = structlog.get_logger(__name__)

# All jobs that SHOULD run at least once per day
EXPECTED_DAILY_JOBS = {
    # Morning pipeline
    "morning_briefing": "Morning Briefing (7:00 AM)",
    "midday_check": "Midday Check (12:00 PM)",
    "evening_review": "Evening Review (6:00 PM)",
    # Autonomous orchestration
    "autonomous_daily_orchestration": "Autonomous Orchestration (8:00 AM)",
    "autonomous_enhancement_cycle": "Enhancement Cycle (9:00 AM)",
    "daily_improvement_plan": "Daily Improvement Plan (9:15 AM)",
    "daily_improvement_execute": "Daily Improvement Execute (9:30 AM)",
    "daily_improvement_verify": "Daily Improvement Verify (10:00 AM)",
    # Core daily jobs
    "money_maker_cycle": "Money Maker (8:00 AM)",
    "research_daily": "Research Cycle (11:00 AM)",
    "qa_verification": "QA Verification (6:00 AM)",
    "tiktok_shop_research": "TikTok Research (10:00 AM)",
    "tiktok_niche_deep_dive": "TikTok Niche Dive (2:00 PM)",
    "embedding_backfill": "Embedding Backfill (3:30 AM)",
    "llm_budget_reset": "LLM Budget Reset (midnight)",
    "prediction_bettor_discovery": "Prediction Bettor Discovery (10:00 AM)",
    "prediction_research": "Prediction Research (11:30 AM)",
    "prediction_quality_check": "Prediction Quality Check (9:00 AM)",
}

# High-frequency jobs — check they ran at all, not individual runs
HIGH_FREQ_JOBS = {
    "gmail_check": "Gmail Check (every 5m)",
    "email_automation_check": "Email Automation (every 5m)",
    "ecosystem_quick_sync": "Ecosystem Sync (every 15m)",
    "ecosystem_full_sync": "Ecosystem Full Sync (every 2h)",
    "continuous_enhancement_engine": "Enhancement Engine (every 10m)",
    "autonomous_continuous_monitor": "Autonomous Monitor (every 30m)",
    "tiktok_continuous_research": "TikTok Research (every 2h)",
    "tiktok_auto_content_pipeline": "TikTok Content (every 6h)",
    "tiktok_content_generation_check": "TikTok Video Check (every 15m)",
    "tiktok_performance_sync": "TikTok Perf Sync (every 3h)",
    "tiktok_pipeline_health": "TikTok Health (every 2h)",
    "prediction_market_sync": "Prediction Sync (every 30m)",
    "prediction_price_snapshot": "Price Snapshot (every 15m)",
    "prediction_push_to_ada": "Push to ADA (every 30m)",
    "task_worker": "Task Worker (every 2m)",
    "gpu_refresh": "GPU Refresh (every 1m)",
    "metrics_snapshot": "Metrics Snapshot (every 1h)",
    "alerting_check": "Alerting (every 5m)",
    "reminder_check": "Reminders (every 5m)",
}


class DailyReportService:
    """Generates comprehensive daily autonomous activity reports."""

    def __init__(self):
        self._storage = JsonStorage(get_workspace_path("reports"))

    async def generate_daily_report(self) -> Dict[str, Any]:
        """Generate the full daily report.

        Queries the scheduler audit log for the last 24 hours,
        aggregates results by job, identifies failures and missing jobs,
        and collects LLM/system metrics.
        """
        now = datetime.utcnow()
        since = now - timedelta(hours=24)

        report = {
            "generated_at": now.isoformat(),
            "period": {"from": since.isoformat(), "to": now.isoformat()},
            "sections": [],
            "grade": 0,
            "summary": "",
        }

        # 1. Scheduler job results
        job_results = await self._get_job_results(since)
        report["sections"].append(self._build_job_section(job_results, since))

        # 2. LLM usage
        llm_section = await self._build_llm_section()
        report["sections"].append(llm_section)

        # 3. System health
        health_section = await self._build_health_section()
        report["sections"].append(health_section)

        # 4. Failures investigation
        failures = await self._investigate_failures(job_results)
        report["sections"].append(failures)

        # 5. Missing jobs investigation
        missing = self._investigate_missing_jobs(job_results, since)
        report["sections"].append(missing)

        # Calculate grade
        report["grade"] = self._calculate_grade(job_results)
        report["summary"] = self._build_summary(report)

        # Persist
        date_key = now.strftime("%Y-%m-%d")
        await self._storage.write(f"daily_report_{date_key}.json", report)

        return report

    async def _get_job_results(self, since: datetime) -> Dict[str, List[Dict]]:
        """Get all scheduler audit logs grouped by job name."""
        results: Dict[str, List[Dict]] = {}
        try:
            async with get_session() as session:
                query = (
                    select(SchedulerAuditLogModel)
                    .where(SchedulerAuditLogModel.started_at >= since)
                    .order_by(SchedulerAuditLogModel.started_at.asc())
                )
                rows = await session.execute(query)
                for row in rows.scalars().all():
                    name = row.job_name
                    if name not in results:
                        results[name] = []
                    results[name].append({
                        "started_at": row.started_at.isoformat() if row.started_at else None,
                        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                        "status": row.status,
                        "duration": row.duration_seconds,
                        "error": row.error,
                    })
        except Exception as e:
            logger.error("daily_report_audit_query_failed", error=str(e))
        return results

    def _build_job_section(self, job_results: Dict, since: datetime) -> Dict:
        """Build the scheduler jobs summary section."""
        total_runs = sum(len(runs) for runs in job_results.values())
        total_success = sum(
            sum(1 for r in runs if r["status"] == "completed")
            for runs in job_results.values()
        )
        total_failed = sum(
            sum(1 for r in runs if r["status"] == "failed")
            for runs in job_results.values()
        )
        unique_jobs = len(job_results)

        # Top 5 slowest
        all_runs = []
        for name, runs in job_results.items():
            for r in runs:
                if r["duration"]:
                    all_runs.append({"job": name, "duration": r["duration"]})
        slowest = sorted(all_runs, key=lambda x: x["duration"], reverse=True)[:5]

        # Most failed
        fail_counts = {}
        for name, runs in job_results.items():
            fails = sum(1 for r in runs if r["status"] == "failed")
            if fails > 0:
                fail_counts[name] = fails
        worst_jobs = sorted(fail_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "title": "Scheduler Jobs (24h)",
            "icon": "⚡",
            "data": {
                "total_runs": total_runs,
                "successful": total_success,
                "failed": total_failed,
                "success_rate": round(total_success / max(total_runs, 1) * 100, 1),
                "unique_jobs_run": unique_jobs,
                "slowest_jobs": slowest,
                "most_failed": worst_jobs,
            },
        }

    async def _build_llm_section(self) -> Dict:
        """Build LLM usage section."""
        try:
            from app.infrastructure.llm_router import get_llm_router
            router = get_llm_router()
            remaining = router.get_remaining_budget()
            spent = router.config.current_spend_usd
            budget = router.config.daily_budget_usd

            return {
                "title": "LLM Usage",
                "icon": "🧠",
                "data": {
                    "daily_budget": budget,
                    "spent_today": round(spent, 4),
                    "remaining": round(remaining, 4),
                    "utilization_pct": round(spent / max(budget, 0.01) * 100, 1),
                    "default_model": router.default_model,
                },
            }
        except Exception as e:
            return {
                "title": "LLM Usage",
                "icon": "🧠",
                "data": {"error": str(e)},
            }

    async def _build_health_section(self) -> Dict:
        """Build system health section."""
        health = {}
        try:
            from app.infrastructure.llm_providers import get_provider_registry
            registry = get_provider_registry()
            providers = []
            for provider in registry.values():
                try:
                    healthy = await provider.is_healthy()
                except Exception:
                    healthy = False
                providers.append({
                    "name": provider.name,
                    "configured": provider.is_configured,
                    "healthy": healthy,
                })
            health["providers"] = providers
        except Exception as e:
            health["providers_error"] = str(e)

        try:
            from app.infrastructure.circuit_breaker import all_circuit_breakers
            breakers = all_circuit_breakers()
            health["circuit_breakers"] = {
                name: cb.state.value for name, cb in breakers.items()
            }
        except Exception:
            pass

        return {
            "title": "System Health",
            "icon": "🏥",
            "data": health,
        }

    async def _investigate_failures(self, job_results: Dict) -> Dict:
        """Investigate why jobs failed — extract error patterns."""
        investigations = []
        for name, runs in job_results.items():
            failed_runs = [r for r in runs if r["status"] == "failed"]
            if not failed_runs:
                continue

            # Group by error message
            error_groups = {}
            for r in failed_runs:
                err = r.get("error", "unknown")[:200]
                error_groups[err] = error_groups.get(err, 0) + 1

            investigations.append({
                "job": name,
                "failure_count": len(failed_runs),
                "total_runs": len(runs),
                "error_patterns": error_groups,
                "last_failure": failed_runs[-1].get("started_at"),
            })

        return {
            "title": "Failure Investigation",
            "icon": "🔍",
            "data": {
                "jobs_with_failures": len(investigations),
                "investigations": sorted(
                    investigations, key=lambda x: x["failure_count"], reverse=True
                ),
            },
        }

    def _investigate_missing_jobs(self, job_results: Dict, since: datetime) -> Dict:
        """Find expected daily jobs that didn't run at all."""
        missing = []
        for job_name, description in EXPECTED_DAILY_JOBS.items():
            if job_name not in job_results:
                missing.append({
                    "job": job_name,
                    "description": description,
                    "reason": "No execution recorded in the last 24 hours",
                })

        # Check high-frequency jobs that had ZERO runs
        hf_missing = []
        for job_name, description in HIGH_FREQ_JOBS.items():
            if job_name not in job_results:
                hf_missing.append({
                    "job": job_name,
                    "description": description,
                    "reason": "No execution recorded — job may not be registered",
                })

        return {
            "title": "Missing Jobs",
            "icon": "⚠️",
            "data": {
                "missing_daily_jobs": missing,
                "missing_daily_count": len(missing),
                "missing_high_freq_jobs": hf_missing,
                "missing_high_freq_count": len(hf_missing),
            },
        }

    def _calculate_grade(self, job_results: Dict) -> int:
        """Calculate an overall daily operations grade (0-100)."""
        score = 0

        # 1. Job success rate (40 points)
        total = sum(len(r) for r in job_results.values())
        successes = sum(
            sum(1 for r in runs if r["status"] == "completed")
            for runs in job_results.values()
        )
        if total > 0:
            score += int((successes / total) * 40)

        # 2. Expected daily jobs coverage (30 points)
        expected_that_ran = sum(
            1 for j in EXPECTED_DAILY_JOBS if j in job_results
        )
        score += int((expected_that_ran / max(len(EXPECTED_DAILY_JOBS), 1)) * 30)

        # 3. High-frequency jobs coverage (20 points)
        hf_that_ran = sum(
            1 for j in HIGH_FREQ_JOBS if j in job_results
        )
        score += int((hf_that_ran / max(len(HIGH_FREQ_JOBS), 1)) * 20)

        # 4. No critical failures (10 points)
        critical_jobs = [
            "morning_briefing", "autonomous_daily_orchestration",
            "gmail_check", "ecosystem_quick_sync",
        ]
        critical_ok = all(
            all(r["status"] == "completed" for r in job_results.get(j, [{"status": "completed"}]))
            for j in critical_jobs
        )
        if critical_ok:
            score += 10

        return min(score, 100)

    def _build_summary(self, report: Dict) -> str:
        """Build a human-readable summary."""
        grade = report["grade"]
        sections = report["sections"]

        lines = []
        lines.append(f"**Daily Autonomous Operations Report** — Grade: **{grade}/100**\n")

        # Jobs section
        jobs = sections[0]["data"]
        lines.append(f"⚡ **Jobs**: {jobs['total_runs']} runs, "
                     f"{jobs['success_rate']}% success rate "
                     f"({jobs['successful']} ok, {jobs['failed']} failed)")

        # LLM section
        llm = sections[1]["data"]
        if "error" not in llm:
            lines.append(f"🧠 **LLM**: ${llm['spent_today']:.4f} spent "
                        f"({llm['utilization_pct']}% of ${llm['daily_budget']} budget)")
        else:
            lines.append(f"🧠 **LLM**: Error retrieving usage")

        # Health section
        health = sections[2]["data"]
        if "providers" in health:
            healthy = sum(1 for p in health["providers"] if p.get("healthy"))
            total_p = len(health["providers"])
            lines.append(f"🏥 **Health**: {healthy}/{total_p} LLM providers healthy")

        # Failures
        failures = sections[3]["data"]
        if failures["jobs_with_failures"] > 0:
            lines.append(f"🔍 **Failures**: {failures['jobs_with_failures']} jobs had failures")
            for inv in failures["investigations"][:3]:
                top_error = list(inv["error_patterns"].keys())[0][:100] if inv["error_patterns"] else "unknown"
                lines.append(f"  - `{inv['job']}`: {inv['failure_count']}x — {top_error}")

        # Missing
        missing = sections[4]["data"]
        if missing["missing_daily_count"] > 0:
            lines.append(f"⚠️ **Missing**: {missing['missing_daily_count']} daily jobs didn't run")
            for m in missing["missing_daily_jobs"][:5]:
                lines.append(f"  - `{m['job']}`: {m['description']}")

        if grade >= 90:
            lines.append("\n✅ System operating well.")
        elif grade >= 70:
            lines.append("\n⚠️ System partially operational. Review failures above.")
        else:
            lines.append("\n🔴 System needs attention. Multiple jobs failing or missing.")

        return "\n".join(lines)

    def format_discord_message(self, report: Dict) -> str:
        """Format the report for Discord delivery (4096 char limit)."""
        summary = report.get("summary", "No summary available")
        # Truncate for Discord embed limit
        if len(summary) > 4000:
            summary = summary[:3997] + "..."
        return summary

    async def get_report_history(self, days: int = 7) -> List[Dict]:
        """Get report history for the last N days."""
        reports = []
        now = datetime.utcnow()
        for i in range(days):
            date = now - timedelta(days=i)
            date_key = date.strftime("%Y-%m-%d")
            data = await self._storage.read(f"daily_report_{date_key}.json")
            if data:
                reports.append({
                    "date": date_key,
                    "grade": data.get("grade", 0),
                    "summary_preview": data.get("summary", "")[:200],
                })
        return reports


@lru_cache()
def get_daily_report_service() -> DailyReportService:
    """Get the singleton daily report service."""
    return DailyReportService()
