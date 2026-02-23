"""
Alerting service for ZERO.

Monitors system health and sends Discord notifications when critical
thresholds are breached. Includes 30-minute deduplication to prevent
alert storms, and recovery alerts when issues resolve.
"""

import time
from datetime import datetime
from typing import Dict, Any, Optional
from functools import lru_cache
import structlog

logger = structlog.get_logger()

# Minimum seconds between duplicate alerts for the same issue
DEDUP_WINDOW = 1800  # 30 minutes


class AlertingService:
    """Monitors system health and sends alerts via notification service."""

    def __init__(self):
        self._last_alert_times: Dict[str, float] = {}
        self._active_issues: Dict[str, bool] = {}

    async def check_alerts(self):
        """Evaluate all alert rules and fire notifications as needed."""
        await self._check_circuit_breakers()
        await self._check_scheduler_health()
        await self._check_disk_space()
        await self._check_backup_recency()

    async def _check_circuit_breakers(self):
        """Alert when any circuit breaker opens, recovery when it closes."""
        try:
            from app.infrastructure.circuit_breaker import all_circuit_breakers

            for name, breaker in all_circuit_breakers().items():
                issue_key = f"circuit_breaker_{name}"
                is_open = breaker.state.value == "open"

                if is_open and not self._active_issues.get(issue_key):
                    await self._fire_alert(
                        issue_key,
                        title=f"Circuit Breaker OPEN: {name}",
                        message=(
                            f"The {name} circuit breaker has opened after "
                            f"{breaker.stats.consecutive_failures} consecutive failures. "
                            f"Service calls to {name} are being blocked."
                        ),
                    )
                    self._active_issues[issue_key] = True

                elif not is_open and self._active_issues.get(issue_key):
                    await self._fire_alert(
                        f"{issue_key}_recovery",
                        title=f"Circuit Breaker RECOVERED: {name}",
                        message=f"The {name} circuit breaker has closed. Service is back online.",
                    )
                    self._active_issues[issue_key] = False
        except Exception as e:
            logger.debug("alert_check_circuit_breakers_failed", error=str(e))

    async def _check_scheduler_health(self):
        """Alert when a job fails 3 times consecutively."""
        try:
            from app.infrastructure.database import get_session
            from sqlalchemy import text

            async with get_session() as session:
                result = await session.execute(
                    text(
                        "SELECT job_name, COUNT(*) as fail_count "
                        "FROM scheduler_audit_log "
                        "WHERE status = 'failed' "
                        "AND created_at > NOW() - INTERVAL '1 hour' "
                        "GROUP BY job_name "
                        "HAVING COUNT(*) >= 3"
                    )
                )
                failing_jobs = result.fetchall()

            for row in failing_jobs:
                job_name = row[0]
                fail_count = row[1]
                issue_key = f"scheduler_{job_name}"
                await self._fire_alert(
                    issue_key,
                    title=f"Scheduler Job Failing: {job_name}",
                    message=f"Job '{job_name}' has failed {fail_count} times in the last hour.",
                )
        except Exception as e:
            logger.debug("alert_check_scheduler_failed", error=str(e))

    async def _check_disk_space(self):
        """Alert when disk usage exceeds 85%."""
        import shutil
        try:
            usage = shutil.disk_usage("/")
            pct = (usage.used / usage.total) * 100
            if pct > 85:
                await self._fire_alert(
                    "disk_space",
                    title="Disk Space Warning",
                    message=f"Disk usage at {pct:.1f}%. Only {usage.free // (1024**3)}GB free.",
                )
        except Exception:
            pass

    async def _check_backup_recency(self):
        """Alert if no successful backup in the last 48 hours."""
        try:
            from app.infrastructure.database import get_session
            from sqlalchemy import text

            async with get_session() as session:
                result = await session.execute(
                    text(
                        "SELECT MAX(completed_at) FROM scheduler_audit_log "
                        "WHERE job_name IN ('backup_hourly', 'backup_daily') "
                        "AND status = 'success'"
                    )
                )
                row = result.fetchone()
                if row and row[0]:
                    last_backup = row[0]
                    if isinstance(last_backup, str):
                        last_backup = datetime.fromisoformat(last_backup)
                    age_hours = (datetime.utcnow() - last_backup.replace(tzinfo=None)).total_seconds() / 3600
                    if age_hours > 48:
                        await self._fire_alert(
                            "backup_stale",
                            title="Backup Warning",
                            message=f"No successful backup in {age_hours:.0f} hours.",
                        )
        except Exception as e:
            logger.debug("alert_check_backup_failed", error=str(e))

    async def _fire_alert(self, issue_key: str, title: str, message: str):
        """Send an alert, respecting deduplication window."""
        now = time.time()
        last_sent = self._last_alert_times.get(issue_key, 0)

        if (now - last_sent) < DEDUP_WINDOW:
            return  # Suppress duplicate

        self._last_alert_times[issue_key] = now

        try:
            from app.services.notification_service import get_notification_service
            svc = get_notification_service()
            await svc.create_notification(
                title=title,
                message=message,
                channel="discord",
                source="alerting",
            )
            logger.info("alert_fired", issue_key=issue_key, title=title)
        except Exception as e:
            logger.error("alert_delivery_failed", issue_key=issue_key, error=str(e))

    def get_status(self) -> Dict[str, Any]:
        """Get current alerting status."""
        return {
            "active_issues": {k: v for k, v in self._active_issues.items() if v},
            "recent_alerts": {
                k: datetime.utcfromtimestamp(v).isoformat()
                for k, v in self._last_alert_times.items()
                if time.time() - v < 3600  # Last hour
            },
        }


@lru_cache()
def get_alerting_service() -> AlertingService:
    """Get singleton AlertingService instance."""
    return AlertingService()
