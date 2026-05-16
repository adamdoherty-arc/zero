"""Initial company setup progress tracking.

Counts how many of the launch-critical company-setup tasks are done versus
total, broken down by domain. Surfaces the same number the Overview tile
shows ("X% setup complete") and the "next unblocked task" the user should
work on right now.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from app.models.task import Task, TaskStatus
from app.services.company_walkthroughs import walkthrough_for
from app.services.company_work_item_service import get_company_work_item_service


SETUP_DOMAINS = {
    "Formation",
    "Finance",
    "Legal",
    "Operations",
    "Admin",
    "Marketing",
    "Agents",
}


SETUP_TITLE_PATTERN = re.compile(
    r"\b("
    r"sunbiz|articles of organization|file .*llc|verify .*name|ein|cp ?575|"
    r"registered agent|operating agreement|bank|credit card|bookkeeping|"
    r"receipt inbox|asset transfer|equipment transfer|fair market value|fmv|"
    r"home office|cpa|attorney|business email|domain|dns|password vault|"
    r"ip assignment|software/ip|robot purchase|robot transfer|"
    r"duval local business|annual report|trademark|disclaimer"
    r")\b",
    re.I,
)


def _enum(value: Any) -> str:
    return getattr(value, "value", value)


def _is_setup_task(task: Task) -> bool:
    if task.domain in SETUP_DOMAINS and (task.priority and _enum(task.priority) in {"critical", "high"}):
        return True
    haystack = f"{task.title} {task.description or ''}"
    if SETUP_TITLE_PATTERN.search(haystack):
        return True
    if walkthrough_for(task.title, task.description or ""):
        return True
    return False


def _is_done(task: Task) -> bool:
    return _enum(task.status) == TaskStatus.DONE.value


def _is_blocked(task: Task) -> bool:
    return _enum(task.status) == TaskStatus.BLOCKED.value


def _is_archived(task: Task) -> bool:
    return _enum(task.status) == TaskStatus.ARCHIVED.value


def _task_summary(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "domain": task.domain or "Operations",
        "status": _enum(task.status),
        "priority": _enum(task.priority),
        "blocked_reason": task.blocked_reason,
        "due_at": task.due_at.isoformat() if task.due_at else None,
    }


class CompanySetupProgressService:
    """Computes the setup-completion percentage and breakdown."""

    async def progress(self) -> dict[str, Any]:
        tasks = await get_company_work_item_service().list_work_items(limit=500)
        setup_tasks = [t for t in tasks if _is_setup_task(t) and not _is_archived(t)]

        total = len(setup_tasks)
        done_tasks = [t for t in setup_tasks if _is_done(t)]
        blocked_tasks = [t for t in setup_tasks if _is_blocked(t)]
        in_progress_tasks = [
            t for t in setup_tasks
            if _enum(t.status) in {"in_progress", "on_hold"}
        ]
        ready_tasks = [t for t in setup_tasks if not _is_done(t) and not _is_blocked(t)]

        percent = round(100 * len(done_tasks) / total) if total else 0

        # Per-domain breakdown
        by_domain: dict[str, dict[str, int]] = {}
        for task in setup_tasks:
            domain = task.domain or "Operations"
            entry = by_domain.setdefault(domain, {"total": 0, "done": 0, "blocked": 0, "in_progress": 0})
            entry["total"] += 1
            if _is_done(task):
                entry["done"] += 1
            elif _is_blocked(task):
                entry["blocked"] += 1
            else:
                entry["in_progress"] += 1
        for entry in by_domain.values():
            entry["percent"] = round(100 * entry["done"] / entry["total"]) if entry["total"] else 0

        # Next 5 unblocked tasks, prioritized by criticality then due date
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        next_unblocked = sorted(
            [t for t in setup_tasks if not _is_done(t) and not _is_blocked(t)],
            key=lambda t: (
                priority_rank.get(_enum(t.priority), 4),
                t.due_at.isoformat() if t.due_at else "9999",
                t.title,
            ),
        )[:5]

        # Blocked + critical = the things demanding Adam's attention
        critical_blocked = sorted(
            [
                t
                for t in blocked_tasks
                if _enum(t.priority) in {"critical", "high"}
            ],
            key=lambda t: (priority_rank.get(_enum(t.priority), 4), t.title),
        )[:5]

        return {
            "percent": percent,
            "total": total,
            "done": len(done_tasks),
            "blocked": len(blocked_tasks),
            "in_progress": len(in_progress_tasks),
            "ready": len(ready_tasks),
            "by_domain": by_domain,
            "next_unblocked": [_task_summary(t) for t in next_unblocked],
            "critical_blocked": [_task_summary(t) for t in critical_blocked],
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }


@lru_cache()
def get_company_setup_progress_service() -> CompanySetupProgressService:
    return CompanySetupProgressService()
