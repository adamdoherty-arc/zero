"""
Autonomous Orchestration Service for ZERO.
Sprint 70 Phase 2: Full autopilot across all ecosystem projects.

This service decides WHEN and WHAT to execute across all projects:
- Daily orchestration: trigger Legion swarm for each project
- Continuous monitoring: detect failures and stuck executions
- Enhancement cycles: scan all codebases, create tasks from signals
- Auto sprint lifecycle: close completed sprints, plan next ones

Legion has the agent swarm (Coder + Tester + Reviewer + Committer).
Zero orchestrates when it runs and feeds it good tasks.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from functools import lru_cache
import structlog

from app.infrastructure.config import get_ecosystem_path, get_settings
from app.infrastructure.storage import JsonStorage

logger = structlog.get_logger(__name__)

# Max entries in orchestration log
ORCHESTRATION_LOG_LIMIT = 200

# Project IDs in Legion
PROJECT_IDS = {
    "zero": 8,
    "ada": 6,
    "fortressos": 7,
    "legion": 3,
}


class AutonomousOrchestrationService:
    """
    Core autopilot service that orchestrates Legion's agent swarm
    across all ecosystem projects.
    """

    def __init__(self):
        self._storage = JsonStorage(get_ecosystem_path())
        self._log_file = "orchestration_log.json"
        self._state_file = "orchestration_state.json"

    # ============================================
    # DAILY ORCHESTRATION (8:00 AM)
    # ============================================

    async def run_daily_orchestration(self) -> Dict[str, Any]:
        """
        Main daily loop: sync ecosystem, then for each project
        trigger swarm execution or plan next sprint.
        """
        logger.info("autonomous_daily_orchestration_start")
        actions = []
        errors = []

        from app.services.legion_client import get_legion_client, LegionConnectionError
        from app.services.ecosystem_sync_service import get_ecosystem_sync_service

        legion = get_legion_client()
        ecosystem = get_ecosystem_sync_service()

        # Step 1: Full ecosystem sync
        try:
            sync_result = await ecosystem.full_sync()
            actions.append({
                "action": "ecosystem_sync",
                "result": "completed",
                "projects": sync_result.get("projects_synced", 0),
            })
        except Exception as e:
            errors.append({"step": "ecosystem_sync", "error": str(e)})
            logger.error("orchestration_sync_failed", error=str(e))

        # Check Legion health
        try:
            if not await legion.health_check():
                error_msg = "Legion unreachable — aborting orchestration"
                errors.append({"step": "health_check", "error": error_msg})
                await self._log_action("daily_orchestration", "aborted", {"reason": error_msg})
                return {"status": "aborted", "reason": error_msg, "actions": actions, "errors": errors}
        except Exception as e:
            errors.append({"step": "health_check", "error": str(e)})
            await self._log_action("daily_orchestration", "aborted", {"reason": str(e)})
            return {"status": "aborted", "reason": str(e), "actions": actions, "errors": errors}

        # Step 2: Process each project
        for project_name, project_id in PROJECT_IDS.items():
            try:
                result = await self._orchestrate_project(legion, project_name, project_id)
                actions.append({
                    "action": f"orchestrate_{project_name}",
                    **result,
                })
            except Exception as e:
                errors.append({"step": f"orchestrate_{project_name}", "error": str(e)})
                logger.error("project_orchestration_failed", project=project_name, error=str(e))

        # Step 3: Log summary
        summary = {
            "actions_taken": len(actions),
            "errors": len(errors),
            "projects_processed": len(PROJECT_IDS),
        }
        await self._log_action("daily_orchestration", "completed", summary)

        # Step 4: Send notification
        await self._notify_orchestration_summary(actions, errors)

        logger.info("autonomous_daily_orchestration_complete", **summary)
        return {"status": "completed", "actions": actions, "errors": errors, **summary}

    async def _orchestrate_project(
        self, legion, project_name: str, project_id: int
    ) -> Dict[str, Any]:
        """Decide what to do for a single project and execute."""
        result = {"project": project_name, "project_id": project_id}

        # Get active sprint for this project
        try:
            current_sprint = await legion.get_current_sprint(project_id)
        except Exception:
            current_sprint = None

        if current_sprint:
            sprint_id = current_sprint["id"]
            total = current_sprint.get("total_tasks", 0)
            completed = current_sprint.get("completed_tasks", 0)
            failed = current_sprint.get("failed_tasks", 0)

            # Is sprint complete?
            if total > 0 and (completed + failed) >= total:
                # Sprint is done — plan next
                logger.info("sprint_complete_planning_next", project=project_name, sprint_id=sprint_id)
                try:
                    plan_result = await legion.plan_next_sprint(project_id)
                    result["action"] = "planned_next_sprint"
                    result["old_sprint_id"] = sprint_id
                    result["new_sprint"] = plan_result
                    await self._log_action(
                        f"plan_next_sprint_{project_name}",
                        "completed",
                        {"old_sprint": sprint_id, "new_sprint": plan_result.get("id") if plan_result else None},
                    )
                except Exception as e:
                    result["action"] = "plan_next_sprint_failed"
                    result["error"] = str(e)
                    logger.warning("plan_next_sprint_failed", project=project_name, error=str(e))
            else:
                # Sprint has pending tasks — trigger swarm execution
                pending = total - completed - failed
                if pending > 0:
                    logger.info(
                        "triggering_swarm_execute",
                        project=project_name,
                        sprint_id=sprint_id,
                        pending_tasks=pending,
                    )
                    try:
                        exec_result = await legion.trigger_swarm_lifecycle(
                            project_id, force_plan_next=False
                        )
                        result["action"] = "triggered_swarm_lifecycle"
                        result["sprint_id"] = sprint_id
                        result["pending_tasks"] = pending
                        result["exec_result"] = exec_result
                        await self._log_action(
                            f"swarm_lifecycle_{project_name}",
                            "triggered",
                            {"sprint_id": sprint_id, "pending": pending},
                        )
                    except Exception as e:
                        result["action"] = "swarm_lifecycle_failed"
                        result["error"] = str(e)
                        logger.warning("swarm_lifecycle_failed", project=project_name, error=str(e))
                else:
                    result["action"] = "no_pending_tasks"
        else:
            # No active sprint — plan one
            logger.info("no_active_sprint_planning", project=project_name)
            try:
                plan_result = await legion.plan_next_sprint(project_id)
                result["action"] = "planned_new_sprint"
                result["new_sprint"] = plan_result
                await self._log_action(
                    f"plan_new_sprint_{project_name}",
                    "completed",
                    {"new_sprint": plan_result.get("id") if plan_result else None},
                )
            except Exception as e:
                result["action"] = "plan_new_sprint_failed"
                result["error"] = str(e)
                logger.warning("plan_new_sprint_failed", project=project_name, error=str(e))

        return result

    # ============================================
    # CONTINUOUS MONITOR (every 30 min)
    # ============================================

    async def run_continuous_monitor(self) -> Dict[str, Any]:
        """
        Check for failed/stuck executions and new enhancement signals.
        """
        logger.info("autonomous_continuous_monitor_start")
        issues = []

        from app.services.legion_client import get_legion_client

        legion = get_legion_client()

        try:
            if not await legion.health_check():
                return {"status": "legion_unavailable"}
        except Exception:
            return {"status": "legion_unavailable"}

        # Check for failed executions
        try:
            recent = await legion.get_recent_executions(limit=20)
            failed = [e for e in recent if e.get("status") == "failed"]
            if failed:
                issues.append({
                    "type": "failed_executions",
                    "count": len(failed),
                    "tasks": [{"id": e.get("task_id"), "title": e.get("task_title", "Unknown")} for e in failed[:5]],
                })
                logger.warning("failed_executions_detected", count=len(failed))
        except Exception as e:
            logger.debug("execution_check_failed", error=str(e))

        # Check for active executions that might be stuck (running > 1 hour)
        try:
            active = await legion.get_active_executions()
            stuck = []
            now = datetime.utcnow()
            for exc in active:
                started = exc.get("started_at")
                if started:
                    try:
                        started_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00")).replace(tzinfo=None)
                        if (now - started_dt).total_seconds() > 3600:
                            stuck.append(exc)
                    except Exception:
                        pass
            if stuck:
                issues.append({
                    "type": "stuck_executions",
                    "count": len(stuck),
                    "tasks": [{"id": e.get("task_id"), "title": e.get("task_title", "Unknown")} for e in stuck],
                })
                logger.warning("stuck_executions_detected", count=len(stuck))
        except Exception as e:
            logger.debug("active_execution_check_failed", error=str(e))

        if issues:
            await self._log_action("continuous_monitor", "issues_found", {"issues": issues})
            await self._notify_issues(issues)

        return {"status": "completed", "issues": issues, "issue_count": len(issues)}

    # ============================================
    # ENHANCEMENT CYCLE (9:00 AM)
    # ============================================

    async def run_enhancement_cycle(self) -> Dict[str, Any]:
        """
        Multi-project enhancement scan + auto-create Legion tasks + daily improvement plan.
        Replaces the old separate enhancement_scan + legion_enhancement_sync jobs.
        """
        logger.info("autonomous_enhancement_cycle_start")

        from app.services.enhancement_service import get_enhancement_service
        from app.services.legion_integration_service import get_legion_integration_service

        enhancement_svc = get_enhancement_service()
        integration_svc = get_legion_integration_service()

        # Step 1: Multi-project scan
        try:
            scan_result = await enhancement_svc.scan_all_projects()
        except Exception as e:
            logger.error("enhancement_scan_failed", error=str(e))
            scan_result = {"status": "error", "error": str(e), "signals_found": 0}

        # Step 2: Create tasks in Legion from high-confidence signals
        try:
            task_result = await integration_svc.auto_create_enhancement_tasks(
                multi_project=True,
                confidence_threshold=0.75,
            )
        except Exception as e:
            logger.error("enhancement_task_creation_failed", error=str(e))
            task_result = {"status": "error", "error": str(e), "tasks_created": 0}

        # Step 3: Create daily improvement plan (new — select top 5 for auto-improvement)
        daily_plan_result = {}
        try:
            from app.services.daily_improvement_service import get_daily_improvement_service
            daily_svc = get_daily_improvement_service()
            daily_plan_result = await daily_svc.create_daily_plan()
            logger.info("daily_improvement_plan_created",
                        improvements=len(daily_plan_result.get("selected_improvements", [])))
        except Exception as e:
            logger.error("daily_improvement_plan_failed", error=str(e))
            daily_plan_result = {"status": "error", "error": str(e)}

        summary = {
            "signals_found": scan_result.get("signals_found", 0),
            "new_signals": scan_result.get("new_signals", 0),
            "per_project": scan_result.get("per_project", {}),
            "tasks_created": task_result.get("tasks_created", 0),
            "tasks_per_project": task_result.get("per_project", {}),
            "daily_improvements_planned": len(daily_plan_result.get("selected_improvements", [])),
        }

        await self._log_action("enhancement_cycle", "completed", summary)

        logger.info("autonomous_enhancement_cycle_complete", **summary)
        return {"status": "completed", **summary}

    # ============================================
    # STATUS & LOG
    # ============================================

    async def get_orchestration_status(self) -> Dict[str, Any]:
        """Get current orchestration status for API/frontend."""
        state = await self._storage.read(self._state_file)
        log = await self._storage.read(self._log_file)
        entries = log.get("entries", [])

        # Get last actions for each type
        last_daily = None
        last_monitor = None
        last_enhancement = None
        for entry in reversed(entries):
            action = entry.get("action", "")
            if "daily_orchestration" in action and not last_daily:
                last_daily = entry
            elif "continuous_monitor" in action and not last_monitor:
                last_monitor = entry
            elif "enhancement_cycle" in action and not last_enhancement:
                last_enhancement = entry
            if last_daily and last_monitor and last_enhancement:
                break

        return {
            "last_daily_orchestration": last_daily,
            "last_continuous_monitor": last_monitor,
            "last_enhancement_cycle": last_enhancement,
            "total_actions": len(entries),
            "recent_actions": entries[-10:] if entries else [],
        }

    async def get_orchestration_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent orchestration log entries."""
        data = await self._storage.read(self._log_file)
        entries = data.get("entries", [])
        return entries[-limit:]

    # ============================================
    # INTERNAL HELPERS
    # ============================================

    async def _log_action(self, action: str, result: str, details: Optional[Dict] = None):
        """Append an action to the orchestration log."""
        data = await self._storage.read(self._log_file)
        entries = data.get("entries", [])

        entries.append({
            "action": action,
            "result": result,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Keep bounded
        if len(entries) > ORCHESTRATION_LOG_LIMIT:
            entries = entries[-ORCHESTRATION_LOG_LIMIT:]

        data["entries"] = entries
        data["last_updated"] = datetime.utcnow().isoformat()
        await self._storage.write(self._log_file, data)

    async def _notify_orchestration_summary(self, actions: List[Dict], errors: List[Dict]):
        """Send orchestration summary via Discord notification."""
        try:
            from app.services.notification_service import get_notification_service

            action_lines = []
            for a in actions:
                project = a.get("project", a.get("action", "unknown"))
                action_type = a.get("action", "unknown")
                action_lines.append(f"- {project}: {action_type}")

            error_lines = []
            for e in errors:
                error_lines.append(f"- {e.get('step', 'unknown')}: {e.get('error', 'unknown')}")

            message = f"**Daily Orchestration Complete**\n\n"
            message += f"Actions: {len(actions)}\n"
            if action_lines:
                message += "\n".join(action_lines[:10]) + "\n"
            if errors:
                message += f"\nErrors: {len(errors)}\n"
                message += "\n".join(error_lines[:5])

            notification_svc = get_notification_service()
            await notification_svc.create_notification(
                title="Orchestration Summary",
                message=message,
                channel="discord",
                source="orchestration",
            )
        except Exception as e:
            logger.debug("orchestration_notification_failed", error=str(e))

    async def _notify_issues(self, issues: List[Dict]):
        """Send issue notification via Discord."""
        try:
            from app.services.notification_service import get_notification_service

            lines = ["**Orchestration Issues Detected**\n"]
            for issue in issues:
                issue_type = issue.get("type", "unknown")
                count = issue.get("count", 0)
                lines.append(f"- {issue_type}: {count} item(s)")
                for task in issue.get("tasks", [])[:3]:
                    lines.append(f"  - {task.get('title', 'Unknown')}")

            notification_svc = get_notification_service()
            await notification_svc.create_notification(
                title="Orchestration Issues",
                message="\n".join(lines),
                channel="discord",
                source="orchestration",
            )
        except Exception as e:
            logger.debug("issue_notification_failed", error=str(e))


# ============================================
# SINGLETON
# ============================================

_service: Optional[AutonomousOrchestrationService] = None


def get_orchestration_service() -> AutonomousOrchestrationService:
    """Get the singleton orchestration service."""
    global _service
    if _service is None:
        _service = AutonomousOrchestrationService()
    return _service
