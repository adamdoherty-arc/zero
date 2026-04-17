"""
Operations Dashboard Service for ZERO.

Aggregates real-time operational data from all subsystems into a single
snapshot for the unified Operations Dashboard frontend page.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, func, desc, and_

from app.db.models import SchedulerAuditLogModel, OrchestratorConversationModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


class OperationsDashboardService:
    """Aggregates data from all subsystems for the operations dashboard."""

    async def get_snapshot(self) -> Dict[str, Any]:
        """Build a complete operational snapshot.

        Fetches data from all subsystems in parallel via asyncio.gather().
        Each subsystem call is wrapped in try/except so one failure
        doesn't break the whole dashboard.
        """
        errors: List[str] = []

        async def _safe(name: str, coro):
            try:
                return await asyncio.wait_for(coro, timeout=5.0)
            except Exception as e:
                errors.append(f"{name}: {str(e)[:120]}")
                logger.warning("ops_dashboard_subsystem_error", subsystem=name, error=str(e))
                return None

        # Fire all subsystem queries in parallel
        (
            job_stats,
            recent_failures,
            daily_grade,
            active_alerts,
            llm_info,
            provider_health,
            breaker_states,
            conversation_count,
            service_health,
            live_activity,
        ) = await asyncio.gather(
            _safe("job_stats", self._get_job_stats()),
            _safe("recent_failures", self._get_recent_failures()),
            _safe("daily_grade", self._get_daily_grade()),
            _safe("active_alerts", self._get_active_alerts()),
            _safe("llm_info", self._get_llm_info()),
            _safe("provider_health", self._get_provider_health()),
            _safe("breaker_states", self._get_circuit_breaker_states()),
            _safe("conversations", self._get_conversation_count()),
            _safe("service_health", self._get_service_health()),
            _safe("live_activity", self._get_live_activity()),
        )

        # Build KPIs
        kpis = {
            "daily_grade": daily_grade if daily_grade is not None else None,
            "success_rate_24h": job_stats["success_rate"] if job_stats else None,
            "total_runs_24h": job_stats["total"] if job_stats else 0,
            "active_alerts": len(active_alerts) if active_alerts else 0,
            "llm_spend_usd": llm_info["spend"] if llm_info else 0.0,
            "llm_budget_usd": llm_info["budget"] if llm_info else 0.0,
            "conversations_today": conversation_count or 0,
        }

        # Build provider list combining health + breaker states
        llm_providers = self._merge_provider_data(
            provider_health or {},
            breaker_states or {},
            llm_info.get("provider_spend", {}) if llm_info else {},
        )

        return {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "kpis": kpis,
            "service_health": service_health or {},
            "active_issues": active_alerts or [],
            "recent_failures": recent_failures or [],
            "live_activity": live_activity or [],
            "llm_providers": llm_providers,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Subsystem data fetchers
    # ------------------------------------------------------------------

    async def _get_job_stats(self) -> Dict[str, Any]:
        """Get 24h job execution stats from scheduler audit log."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        async with get_session() as session:
            result = await session.execute(
                select(
                    func.count(SchedulerAuditLogModel.id).label("total"),
                    func.count(
                        SchedulerAuditLogModel.id
                    ).filter(
                        SchedulerAuditLogModel.status == "completed"
                    ).label("success"),
                ).where(SchedulerAuditLogModel.started_at >= since)
            )
            row = result.one()
            total = row.total or 0
            success = row.success or 0
            rate = (success / total * 100) if total > 0 else 100.0
            return {"total": total, "success": success, "success_rate": round(rate, 1)}

    async def _get_recent_failures(self) -> List[Dict[str, Any]]:
        """Get last 10 failed jobs."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        async with get_session() as session:
            result = await session.execute(
                select(SchedulerAuditLogModel)
                .where(
                    and_(
                        SchedulerAuditLogModel.started_at >= since,
                        SchedulerAuditLogModel.status == "failed",
                    )
                )
                .order_by(desc(SchedulerAuditLogModel.started_at))
                .limit(10)
            )
            rows = result.scalars().all()
            return [
                {
                    "job_name": r.job_name,
                    "failed_at": r.started_at.isoformat() if r.started_at else None,
                    "error": (r.error or "")[:300],
                    "duration_s": round(r.duration_seconds, 1) if r.duration_seconds else 0,
                }
                for r in rows
            ]

    async def _get_daily_grade(self) -> Optional[int]:
        """Get the most recent daily report grade (cached on disk)."""
        try:
            from app.services.daily_report_service import get_daily_report_service
            reports = await get_daily_report_service().get_report_history(days=2)
            if reports:
                return reports[0].get("grade", None)
        except Exception:
            pass
        return None

    async def _get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get active alerts from the alerting service."""
        from app.services.alerting_service import get_alerting_service
        status = get_alerting_service().get_status()
        issues = []
        for key, active in status.get("active_issues", {}).items():
            if active:
                issues.append({
                    "type": "alert",
                    "name": key,
                    "message": f"Alert active: {key}",
                    "severity": "warning",
                    "since": status.get("recent_alerts", {}).get(key),
                })

        # Also check circuit breakers for OPEN state
        from app.infrastructure.circuit_breaker import all_circuit_breakers
        for name, cb in all_circuit_breakers().items():
            if cb.state.value != "closed":
                issues.append({
                    "type": "circuit_breaker",
                    "name": name,
                    "message": f"Circuit breaker {cb.state.value.upper()} ({cb.failure_count} failures)",
                    "severity": "error" if cb.state.value == "open" else "warning",
                    "since": None,
                })
        return issues

    async def _get_llm_info(self) -> Dict[str, Any]:
        """Get LLM spend and budget from router."""
        from app.infrastructure.llm_router import get_llm_router
        router = get_llm_router()
        return {
            "spend": round(router.config.current_spend_usd, 4),
            "budget": router.config.daily_budget_usd,
            "provider_spend": {},  # Could be extended later
        }

    async def _get_provider_health(self) -> Dict[str, bool]:
        """Check health of each LLM provider with timeout."""
        from app.infrastructure.llm_providers import get_provider_registry
        registry = get_provider_registry()
        health = {}
        for name, provider in registry.items():
            try:
                healthy = await asyncio.wait_for(
                    provider.is_healthy(), timeout=3.0
                )
                health[name] = healthy
            except Exception:
                health[name] = False
        return health

    async def _get_circuit_breaker_states(self) -> Dict[str, str]:
        """Get circuit breaker states for all registered breakers."""
        from app.infrastructure.circuit_breaker import all_circuit_breakers
        return {
            name: cb.state.value
            for name, cb in all_circuit_breakers().items()
        }

    async def _get_conversation_count(self) -> int:
        """Count orchestrator conversations from today."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        async with get_session() as session:
            result = await session.execute(
                select(func.count(OrchestratorConversationModel.id)).where(
                    OrchestratorConversationModel.created_at >= today_start
                )
            )
            return result.scalar() or 0

    async def _get_service_health(self) -> Dict[str, str]:
        """Quick health check for core services."""
        import httpx
        from app.infrastructure.config import get_settings

        settings = get_settings()
        checks: Dict[str, str] = {}

        # Storage
        from pathlib import Path
        workspace = Path(settings.workspace_dir).resolve()
        checks["storage"] = "ok" if workspace.exists() else "error"

        # Scheduler
        try:
            from app.services.scheduler_service import get_scheduler_service
            svc = get_scheduler_service()
            checks["scheduler"] = "ok" if svc._running else "error"
        except Exception:
            checks["scheduler"] = "error"

        # Ollama
        try:
            base = settings.ollama_base_url.replace("/v1", "")
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(f"{base}/api/tags")
                checks["ollama"] = "ok" if resp.status_code == 200 else "degraded"
        except Exception:
            checks["ollama"] = "error"

        # SearXNG
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                for path in ["/healthz", "/status"]:
                    try:
                        resp = await client.get(f"{settings.searxng_url}{path}")
                        if resp.status_code == 200:
                            checks["searxng"] = "ok"
                            break
                    except Exception:
                        continue
                else:
                    checks["searxng"] = "degraded"
        except Exception:
            checks["searxng"] = "error"

        # Database (we already queried it above, so if we got here it's fine)
        checks["database"] = "ok"

        return checks

    async def _get_live_activity(self) -> List[Dict[str, Any]]:
        """Merge last scheduler runs + orchestrator conversations into a timeline."""
        since = datetime.now(timezone.utc) - timedelta(hours=4)
        activity: List[Dict[str, Any]] = []

        async with get_session() as session:
            # Recent scheduler runs (last 15)
            sched_result = await session.execute(
                select(SchedulerAuditLogModel)
                .where(SchedulerAuditLogModel.started_at >= since)
                .order_by(desc(SchedulerAuditLogModel.started_at))
                .limit(15)
            )
            for r in sched_result.scalars().all():
                dur = f" in {r.duration_seconds:.1f}s" if r.duration_seconds else ""
                activity.append({
                    "timestamp": r.started_at.isoformat() if r.started_at else None,
                    "type": "job",
                    "summary": f"{r.job_name} {r.status}{dur}",
                    "status": r.status or "unknown",
                })

            # Recent conversations (last 10 inbound)
            conv_result = await session.execute(
                select(OrchestratorConversationModel)
                .where(
                    and_(
                        OrchestratorConversationModel.created_at >= since,
                        OrchestratorConversationModel.direction == "inbound",
                    )
                )
                .order_by(desc(OrchestratorConversationModel.created_at))
                .limit(10)
            )
            for c in conv_result.scalars().all():
                msg_preview = (c.message or "")[:60]
                route_info = f" -> {c.route}" if c.route else ""
                activity.append({
                    "timestamp": c.created_at.isoformat() if c.created_at else None,
                    "type": "conversation",
                    "summary": f"{c.channel}: '{msg_preview}'{route_info}",
                    "status": "error" if c.error else "completed",
                })

        # Sort combined by timestamp descending, take top 20
        activity.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        return activity[:20]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _merge_provider_data(
        self,
        health: Dict[str, bool],
        breakers: Dict[str, str],
        spend: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Combine provider health, breaker states, and spend into provider cards."""
        providers = []
        # Use health dict as source of provider names
        for name in health:
            # Find matching circuit breaker (breakers may have different naming)
            breaker_state = "closed"
            for bname, bstate in breakers.items():
                if name in bname.lower():
                    breaker_state = bstate
                    break

            entry: Dict[str, Any] = {
                "name": name,
                "healthy": health.get(name, False),
                "circuit_state": breaker_state,
                "spend_today_usd": round(spend.get(name, 0.0), 4),
            }
            if not health.get(name, False):
                entry["error"] = "Health check failed"
            providers.append(entry)
        return providers


@lru_cache()
def get_operations_dashboard_service() -> OperationsDashboardService:
    """Get the singleton operations dashboard service."""
    return OperationsDashboardService()
