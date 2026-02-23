"""
Ecosystem Sync Service for ZERO.
Sprint 70: Cross-project orchestration and monitoring.

Polls Legion for all project/sprint/task data, caches locally,
detects lifecycle events, computes health scores, and generates alerts.

Legion is the single source of truth — this service only READS from it.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from functools import lru_cache
import structlog

from app.infrastructure.config import get_ecosystem_path, get_settings
from app.infrastructure.storage import JsonStorage
from app.services.legion_client import get_legion_client, LegionClient

logger = structlog.get_logger(__name__)

# Lifecycle thresholds
STALE_SPRINT_DAYS = 14
VELOCITY_DROP_THRESHOLD = 0.3  # 30% drop triggers alert
BLOCKED_RATIO_THRESHOLD = 0.2  # >20% blocked tasks triggers alert
CHANGE_EVENT_LIMIT = 500


class EcosystemSyncService:
    """
    Syncs all ecosystem project data from Legion and provides
    cached reads, change detection, health scoring, and alerting.
    """

    def __init__(self):
        self._storage = JsonStorage(get_ecosystem_path())
        self._last_quick_sync: Optional[datetime] = None
        self._last_full_sync: Optional[datetime] = None

    # ============================================
    # SYNC OPERATIONS
    # ============================================

    async def quick_sync(self) -> Dict[str, Any]:
        """
        Lightweight sync — fetch daily summary from Legion, detect changes.
        Designed to run every 15 minutes.
        """
        legion = get_legion_client()
        try:
            summary = await legion.get_daily_summary()
        except Exception as e:
            logger.warning("ecosystem_quick_sync_failed", error=str(e))
            return {"status": "error", "error": str(e)}

        # Load previous state for change detection
        prev = await self._storage.read("quick_sync.json")
        prev_blocked = {t.get("id") for t in prev.get("blocked_tasks", [])}

        # Detect new blocked tasks
        new_blocked = [
            t for t in summary.get("blocked_tasks", [])
            if t.get("id") not in prev_blocked
        ]

        # Detect changes
        changes = []
        if prev:
            if summary.get("active_sprints", 0) != prev.get("active_sprints", 0):
                changes.append({
                    "type": "sprint_count_changed",
                    "old": prev.get("active_sprints", 0),
                    "new": summary.get("active_sprints", 0),
                })
            if summary.get("blocked_count", 0) > prev.get("blocked_count", 0):
                changes.append({
                    "type": "new_blocked_tasks",
                    "count": len(new_blocked),
                    "tasks": [{"id": t.get("id"), "title": t.get("title"), "project": t.get("project_name")} for t in new_blocked],
                })

        # Save
        summary["synced_at"] = datetime.utcnow().isoformat()
        await self._storage.write("quick_sync.json", summary)

        # Record change events
        if changes:
            await self._append_change_events(changes)

        self._last_quick_sync = datetime.utcnow()

        logger.info(
            "ecosystem_quick_sync_complete",
            projects=summary.get("total_projects", 0),
            active_sprints=summary.get("active_sprints", 0),
            blocked=summary.get("blocked_count", 0),
            changes=len(changes),
        )

        return {
            "status": "ok",
            "projects": summary.get("total_projects", 0),
            "active_sprints": summary.get("active_sprints", 0),
            "blocked_count": summary.get("blocked_count", 0),
            "changes_detected": len(changes),
            "synced_at": summary["synced_at"],
        }

    async def full_sync(self) -> Dict[str, Any]:
        """
        Deep sync — fetch all projects, active sprints, tasks, and metrics.
        Designed to run every 2 hours.
        """
        legion = get_legion_client()

        try:
            projects = await legion.list_projects(status="active")
        except Exception as e:
            logger.warning("ecosystem_full_sync_failed", error=str(e))
            return {"status": "error", "error": str(e)}

        # Load previous data for change detection
        prev_sprints_data = await self._storage.read("sprints.json")
        prev_sprint_map = {
            s["id"]: s for s in prev_sprints_data.get("sprints", [])
        }

        project_records = []
        sprint_records = []
        task_records = []
        changes = []

        for project in projects:
            pid = project["id"]
            pname = project.get("name", "Unknown")

            # Get active sprints for this project
            try:
                sprints = await legion.list_sprints(project_id=pid, status="active")
            except Exception as e:
                logger.warning("ecosystem_sync_sprints_error", project_id=pid, error=str(e))
                sprints = []

            # Also get recently completed sprints (last 5)
            try:
                completed = await legion.list_sprints(project_id=pid, status="completed", limit=5)
            except Exception:
                completed = []

            all_sprints = sprints + completed
            current_sprint = sprints[0] if sprints else None

            # Fetch tasks for active sprints
            project_tasks = []
            for sprint in sprints:
                sid = sprint["id"]
                try:
                    tasks = await legion.list_tasks(sid)
                except Exception as e:
                    logger.warning("ecosystem_sync_tasks_error", sprint_id=sid, error=str(e))
                    tasks = []

                for task in tasks:
                    task["project_id"] = pid
                    task["project_name"] = pname
                    task["sprint_name"] = sprint.get("name", "")
                    project_tasks.append(task)

                # Detect sprint status changes
                prev = prev_sprint_map.get(sid)
                if prev and prev.get("status") != sprint.get("status"):
                    changes.append({
                        "type": "sprint_status_changed",
                        "project": pname,
                        "sprint_id": sid,
                        "sprint_name": sprint.get("name"),
                        "old_status": prev.get("status"),
                        "new_status": sprint.get("status"),
                    })

            # Build project record
            total_tasks = len(project_tasks)
            completed_tasks = sum(1 for t in project_tasks if t.get("status") == "completed")
            blocked_tasks = sum(1 for t in project_tasks if t.get("status") in ("failed", "blocked"))
            in_progress_tasks = sum(1 for t in project_tasks if t.get("status") in ("running", "in_progress"))

            project_records.append({
                "id": pid,
                "name": pname,
                "status": project.get("status", "unknown"),
                "tech_stack": project.get("tech_stack", {}),
                "current_sprint": {
                    "id": current_sprint["id"],
                    "name": current_sprint.get("name", ""),
                    "status": current_sprint.get("status", ""),
                    "total_tasks": current_sprint.get("total_tasks", 0),
                    "completed_tasks": current_sprint.get("completed_tasks", 0),
                } if current_sprint else None,
                "task_summary": {
                    "total": total_tasks,
                    "completed": completed_tasks,
                    "in_progress": in_progress_tasks,
                    "blocked": blocked_tasks,
                },
            })

            for s in all_sprints:
                sprint_records.append({
                    "id": s["id"],
                    "project_id": pid,
                    "project_name": pname,
                    "name": s.get("name", ""),
                    "status": s.get("status", ""),
                    "total_tasks": s.get("total_tasks", 0),
                    "completed_tasks": s.get("completed_tasks", 0),
                    "failed_tasks": s.get("failed_tasks", 0),
                    "planned_start": s.get("planned_start"),
                    "planned_end": s.get("planned_end"),
                    "created_at": s.get("created_at"),
                })

            task_records.extend(project_tasks)

        now = datetime.utcnow().isoformat()

        # Write all caches
        await asyncio.gather(
            self._storage.write("projects.json", {
                "projects": project_records,
                "last_full_sync": now,
            }),
            self._storage.write("sprints.json", {
                "sprints": sprint_records,
                "last_full_sync": now,
            }),
            self._storage.write("tasks.json", {
                "tasks": task_records,
                "last_full_sync": now,
            }),
        )

        # Record changes
        if changes:
            await self._append_change_events(changes)

        self._last_full_sync = datetime.utcnow()

        logger.info(
            "ecosystem_full_sync_complete",
            projects=len(project_records),
            sprints=len(sprint_records),
            tasks=len(task_records),
            changes=len(changes),
        )

        return {
            "status": "ok",
            "projects": len(project_records),
            "sprints": len(sprint_records),
            "tasks": len(task_records),
            "changes_detected": len(changes),
            "synced_at": now,
        }

    # ============================================
    # EXECUTION MONITORING (Task 3)
    # ============================================

    async def sync_executions(self) -> Dict[str, Any]:
        """
        Fetch recent autonomous executions from Legion,
        detect state transitions, alert on failures.
        Runs every 30 minutes.
        """
        legion = get_legion_client()

        # Determine since window (last 2 hours or last check)
        since = datetime.utcnow() - timedelta(hours=2)

        try:
            executions = await legion.get_recent_executions(since=since, limit=50)
        except Exception as e:
            logger.warning("ecosystem_execution_sync_failed", error=str(e))
            return {"status": "error", "error": str(e)}

        # Load previous executions for change detection
        prev_data = await self._storage.read("executions.json")
        prev_map = {
            e.get("id", e.get("task_id")): e
            for e in prev_data.get("executions", [])
        }

        new_failures = []
        new_completions = []
        changes = []

        for exe in executions:
            exe_id = exe.get("id", exe.get("task_id"))
            status = exe.get("status", "")
            prev = prev_map.get(exe_id)

            if prev and prev.get("status") != status:
                if status == "failed":
                    new_failures.append(exe)
                    changes.append({
                        "type": "execution_failed",
                        "execution_id": exe_id,
                        "task_title": exe.get("title", exe.get("task_title", "")),
                        "error": exe.get("error", exe.get("error_message", "")),
                    })
                elif status == "completed":
                    new_completions.append(exe)
                    changes.append({
                        "type": "execution_completed",
                        "execution_id": exe_id,
                        "task_title": exe.get("title", exe.get("task_title", "")),
                    })
            elif not prev and status == "failed":
                new_failures.append(exe)
                changes.append({
                    "type": "execution_failed",
                    "execution_id": exe_id,
                    "task_title": exe.get("title", exe.get("task_title", "")),
                    "error": exe.get("error", exe.get("error_message", "")),
                })

        # Save
        now = datetime.utcnow().isoformat()
        await self._storage.write("executions.json", {
            "executions": executions,
            "last_sync": now,
            "recent_failures": len(new_failures),
            "recent_completions": len(new_completions),
        })

        if changes:
            await self._append_change_events(changes)

        logger.info(
            "ecosystem_execution_sync_complete",
            total=len(executions),
            new_failures=len(new_failures),
            new_completions=len(new_completions),
        )

        return {
            "status": "ok",
            "total_executions": len(executions),
            "new_failures": len(new_failures),
            "new_completions": len(new_completions),
            "synced_at": now,
        }

    # ============================================
    # SPRINT LIFECYCLE DETECTION (Task 3)
    # ============================================

    async def detect_lifecycle_events(self) -> List[Dict[str, Any]]:
        """
        Analyze synced sprint data for actionable lifecycle events:
        - Stale sprints (active > 14 days with no movement)
        - Sprint ready to close (all tasks done)
        - Overdue sprints (past planned_end)
        - Velocity drops
        Runs daily at 6:55 AM.
        """
        sprints_data = await self._storage.read("sprints.json")
        sprints = sprints_data.get("sprints", [])
        now = datetime.utcnow()

        events = []

        for sprint in sprints:
            if sprint.get("status") != "active":
                continue

            sid = sprint["id"]
            name = sprint.get("name", f"Sprint {sid}")
            project = sprint.get("project_name", "Unknown")
            total = sprint.get("total_tasks", 0)
            completed = sprint.get("completed_tasks", 0)
            failed = sprint.get("failed_tasks", 0)

            # Ready to close: all tasks done
            if total > 0 and completed == total:
                events.append({
                    "type": "sprint_ready_to_close",
                    "severity": "info",
                    "project": project,
                    "sprint_id": sid,
                    "sprint_name": name,
                    "message": f"{project}: '{name}' has all {total} tasks completed — ready to close",
                })

            # Stale sprint: active too long
            created = sprint.get("created_at")
            if created:
                try:
                    created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00")).replace(tzinfo=None)
                    age_days = (now - created_dt).days
                    if age_days > STALE_SPRINT_DAYS:
                        progress = round((completed / total * 100) if total > 0 else 0, 1)
                        events.append({
                            "type": "stale_sprint",
                            "severity": "warning",
                            "project": project,
                            "sprint_id": sid,
                            "sprint_name": name,
                            "age_days": age_days,
                            "message": f"{project}: '{name}' has been active for {age_days} days ({progress}% done)",
                        })
                except (ValueError, TypeError):
                    pass

            # Overdue: past planned end date
            planned_end = sprint.get("planned_end")
            if planned_end:
                try:
                    end_dt = datetime.fromisoformat(str(planned_end).replace("Z", "+00:00")).replace(tzinfo=None)
                    if now > end_dt:
                        days_overdue = (now - end_dt).days
                        events.append({
                            "type": "overdue_sprint",
                            "severity": "warning",
                            "project": project,
                            "sprint_id": sid,
                            "sprint_name": name,
                            "days_overdue": days_overdue,
                            "message": f"{project}: '{name}' is {days_overdue} days past planned end date",
                        })
                except (ValueError, TypeError):
                    pass

            # High blocked ratio
            if total > 0 and failed / total > BLOCKED_RATIO_THRESHOLD:
                blocked_pct = round(failed / total * 100, 1)
                events.append({
                    "type": "high_blocked_ratio",
                    "severity": "critical",
                    "project": project,
                    "sprint_id": sid,
                    "sprint_name": name,
                    "blocked_percentage": blocked_pct,
                    "message": f"{project}: '{name}' has {blocked_pct}% tasks blocked/failed ({failed}/{total})",
                })

        # Save lifecycle events
        await self._storage.write("lifecycle_events.json", {
            "events": events,
            "generated_at": datetime.utcnow().isoformat(),
        })

        if events:
            await self._append_change_events([
                {"type": "lifecycle_event", **e} for e in events
            ])

        logger.info("ecosystem_lifecycle_check_complete", events=len(events))
        return events

    async def generate_lifecycle_suggestions(self) -> List[str]:
        """Generate natural language suggestions from lifecycle events."""
        data = await self._storage.read("lifecycle_events.json")
        events = data.get("events", [])

        suggestions = []
        for event in events:
            etype = event.get("type")
            if etype == "sprint_ready_to_close":
                suggestions.append(f"Complete sprint '{event['sprint_name']}' in {event['project']} — all tasks are done.")
            elif etype == "stale_sprint":
                suggestions.append(f"Review '{event['sprint_name']}' in {event['project']} — it's been active {event['age_days']} days.")
            elif etype == "overdue_sprint":
                suggestions.append(f"'{event['sprint_name']}' in {event['project']} is {event['days_overdue']} days overdue — consider completing or extending.")
            elif etype == "high_blocked_ratio":
                suggestions.append(f"Unblock tasks in '{event['sprint_name']}' ({event['project']}) — {event['blocked_percentage']}% are stuck.")

        return suggestions

    # ============================================
    # CROSS-PROJECT INTELLIGENCE (Task 4)
    # ============================================

    async def compute_project_health_scores(self) -> Dict[int, Dict[str, Any]]:
        """
        Compute health score for each project (0-100).
        Formula: completion_rate * 60 - blocked_ratio * 30 + velocity_bonus (max 10)
        """
        projects_data = await self._storage.read("projects.json")
        projects = projects_data.get("projects", [])

        scores = {}
        for project in projects:
            pid = project["id"]
            ts = project.get("task_summary", {})
            total = ts.get("total", 0)
            completed = ts.get("completed", 0)
            blocked = ts.get("blocked", 0)
            in_progress = ts.get("in_progress", 0)

            if total == 0:
                scores[pid] = {
                    "project_name": project.get("name"),
                    "health_score": 100.0,
                    "completion_rate": 0,
                    "blocked_ratio": 0,
                    "detail": "No active tasks",
                }
                continue

            completion_rate = completed / total
            blocked_ratio = blocked / total

            # Base score from completion
            score = completion_rate * 60

            # Penalty for blocked tasks
            score -= blocked_ratio * 30

            # Bonus for having work in progress (active sprint momentum)
            if in_progress > 0:
                score += min(10, in_progress * 2)

            score = max(0, min(100, round(score, 1)))

            scores[pid] = {
                "project_name": project.get("name"),
                "health_score": score,
                "completion_rate": round(completion_rate * 100, 1),
                "blocked_ratio": round(blocked_ratio * 100, 1),
                "in_progress": in_progress,
            }

        return scores

    async def detect_risks(self) -> List[Dict[str, Any]]:
        """
        Detect high-risk sprints across all projects.
        Returns unified risk list sorted by severity.
        """
        risks = []

        # Sprint lifecycle events (stale, overdue, high blocked)
        lifecycle_data = await self._storage.read("lifecycle_events.json")
        for event in lifecycle_data.get("events", []):
            risks.append({
                "source": "lifecycle",
                "severity": event.get("severity", "info"),
                "project": event.get("project"),
                "sprint_id": event.get("sprint_id"),
                "message": event.get("message"),
            })

        # Execution failures
        exec_data = await self._storage.read("executions.json")
        failures = [
            e for e in exec_data.get("executions", [])
            if e.get("status") == "failed"
        ]
        for f in failures[:5]:  # Top 5 recent failures
            risks.append({
                "source": "execution",
                "severity": "critical",
                "project": f.get("project_name", "Unknown"),
                "message": f"Execution failed: {f.get('title', f.get('task_title', 'Unknown'))} — {f.get('error', f.get('error_message', 'No details'))}",
            })

        # Sort: critical first, then warning, then info
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        risks.sort(key=lambda r: severity_order.get(r.get("severity", "info"), 3))

        return risks

    async def get_alerts(self) -> List[Dict[str, Any]]:
        """
        Get all active alerts: lifecycle events + execution failures + risks.
        This is the unified alert feed for the frontend.
        """
        alerts = []

        # Lifecycle events
        lifecycle_data = await self._storage.read("lifecycle_events.json")
        for event in lifecycle_data.get("events", []):
            alerts.append({
                "id": f"lifecycle_{event.get('sprint_id')}_{event.get('type')}",
                "type": event.get("type"),
                "severity": event.get("severity", "info"),
                "project": event.get("project"),
                "sprint_id": event.get("sprint_id"),
                "sprint_name": event.get("sprint_name"),
                "message": event.get("message"),
                "generated_at": lifecycle_data.get("generated_at"),
            })

        # Execution failures
        exec_data = await self._storage.read("executions.json")
        for exe in exec_data.get("executions", []):
            if exe.get("status") == "failed":
                exe_id = exe.get("id", exe.get("task_id"))
                alerts.append({
                    "id": f"exec_{exe_id}",
                    "type": "execution_failed",
                    "severity": "critical",
                    "project": exe.get("project_name", "Unknown"),
                    "message": f"Execution failed: {exe.get('title', exe.get('task_title', ''))}",
                    "error": exe.get("error", exe.get("error_message", "")),
                    "generated_at": exec_data.get("last_sync"),
                })

        # Blocked tasks from quick sync
        quick_data = await self._storage.read("quick_sync.json")
        for task in quick_data.get("blocked_tasks", []):
            alerts.append({
                "id": f"blocked_{task.get('id')}",
                "type": "task_blocked",
                "severity": "warning",
                "project": task.get("project_name", "Unknown"),
                "sprint_name": task.get("sprint_name", ""),
                "message": f"Blocked: {task.get('title', 'Unknown task')}",
                "generated_at": quick_data.get("synced_at"),
            })

        # Sort by severity
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        alerts.sort(key=lambda a: severity_order.get(a.get("severity", "info"), 3))

        return alerts

    # ============================================
    # CACHED READS (for API / frontend)
    # ============================================

    async def get_cached_status(self) -> Dict[str, Any]:
        """
        Get full ecosystem status from cache.
        Used by GET /api/ecosystem/status — no Legion API calls.
        """
        projects_data = await self._storage.read("projects.json")
        projects = projects_data.get("projects", [])

        health_scores = await self.compute_project_health_scores()

        # Enrich projects with health scores
        for p in projects:
            h = health_scores.get(p["id"], {})
            p["health_score"] = h.get("health_score", 0)
            p["completion_rate"] = h.get("completion_rate", 0)
            p["blocked_ratio"] = h.get("blocked_ratio", 0)

        total_active = sum(1 for p in projects if p.get("current_sprint"))
        total_blocked = sum(p.get("task_summary", {}).get("blocked", 0) for p in projects)
        overall_health = (
            round(sum(h.get("health_score", 0) for h in health_scores.values()) / len(health_scores), 1)
            if health_scores else 0
        )

        alerts = await self.get_alerts()

        return {
            "projects": projects,
            "total_projects": len(projects),
            "total_active_sprints": total_active,
            "total_blocked_tasks": total_blocked,
            "overall_health": overall_health,
            "alert_count": len(alerts),
            "last_quick_sync": (await self._storage.read("quick_sync.json")).get("synced_at"),
            "last_full_sync": projects_data.get("last_full_sync"),
        }

    async def get_cached_project_sprint(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get current sprint + tasks for a specific project from cache."""
        projects_data = await self._storage.read("projects.json")
        project = next(
            (p for p in projects_data.get("projects", []) if p["id"] == project_id),
            None,
        )
        if not project:
            return None

        tasks_data = await self._storage.read("tasks.json")
        project_tasks = [
            t for t in tasks_data.get("tasks", [])
            if t.get("project_id") == project_id
        ]

        return {
            "project": project,
            "tasks": project_tasks,
        }

    async def get_cached_project_detail(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get enriched project detail from cache: project info + all sprints + tasks."""
        projects_data = await self._storage.read("projects.json")
        project = next(
            (p for p in projects_data.get("projects", []) if p["id"] == project_id),
            None,
        )
        if not project:
            return None

        # Enrich with health score
        health_scores = await self.compute_project_health_scores()
        h = health_scores.get(project_id, {})
        project["health_score"] = h.get("health_score", 0)
        project["completion_rate"] = h.get("completion_rate", 0)
        project["blocked_ratio"] = h.get("blocked_ratio", 0)

        # Get all sprints for this project
        sprints_data = await self._storage.read("sprints.json")
        project_sprints = [
            s for s in sprints_data.get("sprints", [])
            if s.get("project_id") == project_id
        ]
        for sprint in project_sprints:
            total = sprint.get("total_tasks", 0)
            completed = sprint.get("completed_tasks", 0)
            sprint["progress"] = round((completed / total * 100) if total > 0 else 0, 1)

        # Get tasks for this project
        tasks_data = await self._storage.read("tasks.json")
        project_tasks = [
            t for t in tasks_data.get("tasks", [])
            if t.get("project_id") == project_id
        ]

        return {
            "project": project,
            "sprints": project_sprints,
            "tasks": project_tasks,
        }

    async def get_cached_project_sprints(self, project_id: int) -> List[Dict[str, Any]]:
        """Get all cached sprints for a project with progress."""
        sprints_data = await self._storage.read("sprints.json")
        project_sprints = [
            s for s in sprints_data.get("sprints", [])
            if s.get("project_id") == project_id
        ]
        for sprint in project_sprints:
            total = sprint.get("total_tasks", 0)
            completed = sprint.get("completed_tasks", 0)
            sprint["progress"] = round((completed / total * 100) if total > 0 else 0, 1)
        return project_sprints

    async def get_cached_timeline(self) -> List[Dict[str, Any]]:
        """Get all active sprints for timeline view from cache."""
        sprints_data = await self._storage.read("sprints.json")
        active = [
            s for s in sprints_data.get("sprints", [])
            if s.get("status") == "active"
        ]

        # Compute progress for each
        for sprint in active:
            total = sprint.get("total_tasks", 0)
            completed = sprint.get("completed_tasks", 0)
            sprint["progress"] = round((completed / total * 100) if total > 0 else 0, 1)

        return active

    async def get_sync_status(self) -> Dict[str, Any]:
        """Get sync status and timing info."""
        quick = await self._storage.read("quick_sync.json")
        projects = await self._storage.read("projects.json")
        execs = await self._storage.read("executions.json")
        events = await self._storage.read("change_events.json")

        return {
            "last_quick_sync": quick.get("synced_at"),
            "last_full_sync": projects.get("last_full_sync"),
            "last_execution_sync": execs.get("last_sync"),
            "total_change_events": len(events.get("events", [])),
        }

    async def get_change_events(self, since: Optional[datetime] = None, limit: int = 50) -> List[Dict]:
        """Get recent change events, optionally filtered by time."""
        data = await self._storage.read("change_events.json")
        events = data.get("events", [])

        if since:
            since_str = since.isoformat()
            events = [e for e in events if e.get("timestamp", "") >= since_str]

        return events[-limit:]

    # ============================================
    # INTERNAL HELPERS
    # ============================================

    async def _append_change_events(self, new_events: List[Dict]):
        """Append change events to the bounded event log."""
        data = await self._storage.read("change_events.json")
        events = data.get("events", [])

        now = datetime.utcnow().isoformat()
        for event in new_events:
            event["timestamp"] = now
            events.append(event)

        # Bound to CHANGE_EVENT_LIMIT
        if len(events) > CHANGE_EVENT_LIMIT:
            events = events[-CHANGE_EVENT_LIMIT:]

        await self._storage.write("change_events.json", {"events": events})


# ============================================
# SINGLETON
# ============================================

_service: Optional[EcosystemSyncService] = None


def get_ecosystem_sync_service() -> EcosystemSyncService:
    """Get the singleton ecosystem sync service."""
    global _service
    if _service is None:
        _service = EcosystemSyncService()
    return _service
