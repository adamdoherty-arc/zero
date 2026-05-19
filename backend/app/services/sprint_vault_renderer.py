"""Render Zero sprints (sourced from Legion) into the Obsidian vault.

Sprint-Tracking policy (2026-05-17): Legion is the source of truth for
Zero sprints. This module renders a human-readable markdown file per
sprint into `/vault/legion/Sprints/<hub>/<NN>-<slug>.md`. The Obsidian
vault is mounted at `vault_path` (default `/vault`) per the config.

Idempotent: call `render_sprint(sprint_id)` any time and it overwrites
the file from current Legion state. There is no scanner — the vault
file IS the rendered view, and the DB lives in Legion at port 8005.

Wired into Zero's sprint flow at:
- sprint_service.create_sprint (TBD)
- sprint_service.add_task (TBD)
- sprint_service.complete_sprint (TBD)

Uses `aiohttp` to follow Zero's HTTP idiom (the rest of the project
uses aiohttp, not httpx).

Writes are atomic via temp-file + rename so concurrent renders of the
same sprint can't truncate one another.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import structlog

from app.infrastructure.config import get_settings
from app.services.legion_client import get_legion_client

_logger = structlog.get_logger(__name__)

_DEFAULT_HUB_BUCKET = "uncategorized"


def _vault_root() -> Path:
    return Path(get_settings().vault_path)


def _sprints_root() -> Path:
    return _vault_root() / "legion" / "Sprints"


def _slugify(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "untitled"


def _bucket_for(sprint: Dict[str, Any]) -> str:
    name = sprint.get("name") or ""
    m = re.match(r"^([A-Za-z]+)\b", name.strip())
    if m:
        return _slugify(m.group(1))
    return _DEFAULT_HUB_BUCKET


def _file_path_for(sprint: Dict[str, Any]) -> Path:
    sid = sprint.get("id")
    name = sprint.get("name") or "sprint"
    bucket = _bucket_for(sprint)
    fname = f"{int(sid):05d}-{_slugify(name)}.md" if sid else f"{_slugify(name)}.md"
    return _sprints_root() / bucket / fname


def _iso_date(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    if isinstance(dt, str):
        return dt[:10]
    return None


def _frontmatter(sprint: Dict[str, Any]) -> str:
    fm: List[str] = ["---"]
    fm.append(f"legion_sprint_id: {sprint.get('id')}")
    if sprint.get("source_id") is not None:
        fm.append(f"source_id: {sprint.get('source_id')}")
    fm.append(f"source_system: {sprint.get('source_system') or 'zero'}")
    goal = (sprint.get("goal") or "").replace('"', '\\"')
    fm.append(f'goal: "{goal}"')
    fm.append(f"hub: {_bucket_for(sprint)}")
    fm.append(f"status: {(sprint.get('status') or 'planned').lower()}")
    fm.append(f"planned_points: {sprint.get('planned_points') or 0}")
    fm.append(f"completed_points: {sprint.get('completed_points') or 0}")
    if sprint.get("health_score") is not None:
        fm.append(f"health_score: {sprint.get('health_score')}")
    if sprint.get("documentation_link"):
        fm.append(f"documentation_link: {sprint.get('documentation_link')}")
    created = _iso_date(sprint.get("created_at"))
    if created:
        fm.append(f"created: {created}")
    end = _iso_date(sprint.get("actual_end"))
    if end:
        fm.append(f"completed: {end}")
    fm.append("---")
    return "\n".join(fm)


_LEGION_TO_TASKS_PLUGIN = {
    "pending": "[ ]",
    "queued": "[ ]",
    "running": "[/]",
    "completed": "[x]",
    "failed": "[!]",
    "skipped": "[-]",
    "rate_limited": "[/]",
}


def _task_line(task: Dict[str, Any]) -> str:
    status = (task.get("status") or "pending").lower()
    check = _LEGION_TO_TASKS_PLUGIN.get(status, "[ ]")
    title = (task.get("title") or "").strip()
    priority = task.get("priority") or 0
    if priority and priority <= 2:
        prio = " ⏫"
    elif priority and priority <= 4:
        prio = " 🔼"
    else:
        prio = ""
    parts = [f"- {check}{prio} {title}"]
    files = task.get("files_affected") or []
    if files:
        parts.append(f" [files:: {', '.join(files[:6])}]")
    completed = _iso_date(task.get("completed_at"))
    if status == "completed" and completed:
        parts.append(f" ✅ {completed}")
    parts.append(f" (#legion-{task.get('sprint_id')}-T{task.get('id')})")
    return "".join(parts)


def _render_tasks(tasks: Iterable[Dict[str, Any]]) -> str:
    sorted_tasks = sorted(
        list(tasks),
        key=lambda t: (t.get("order") or 0, t.get("id") or 0),
    )
    return "\n".join(_task_line(t) for t in sorted_tasks) or "_(no tasks yet)_"


def _render_retrospective(retro: Optional[Dict[str, Any]]) -> str:
    if not isinstance(retro, dict) or not retro:
        return "_(populated when the sprint is completed via `POST /api/sprints/{id}/complete`)_"
    out: List[str] = []
    goal = retro.get("goal")
    if goal:
        out.append(f"**Goal achieved:** {goal}")
        out.append("")
    out.append("### Work Completed")
    work = retro.get("work_completed") or []
    if work:
        for item in work:
            if isinstance(item, dict):
                tid = item.get("task_id")
                title = item.get("title") or ""
                files = item.get("files") or []
                verified = " ✓" if item.get("verified") else ""
                line = f"- {title}{verified}"
                if tid:
                    line += f"  *(#legion-task-{tid})*"
                if files:
                    line += f"  `{', '.join(files[:6])}`"
                out.append(line)
            else:
                out.append(f"- {item}")
    else:
        out.append("_(none recorded)_")
    out.append("")
    out.append("### Testing")
    testing = retro.get("testing") or {}
    if testing:
        rs = testing.get("regression_status")
        if rs:
            out.append(f"- Regression: **{rs}**")
        tests_added = testing.get("tests_added") or []
        if tests_added:
            out.append(f"- Tests added: {', '.join(f'`{t}`' for t in tests_added)}")
        sv = testing.get("smoke_verified")
        if sv:
            out.append(f"- Smoke verified: {sv}")
    else:
        out.append("_(no testing summary)_")
    out.append("")
    out.append("### Improvements Found")
    improvements = retro.get("improvements_found") or []
    if improvements:
        for item in improvements:
            if isinstance(item, dict):
                desc = item.get("description") or ""
                tid = item.get("follow_up_task_id")
                line = f"- {desc}"
                if tid:
                    line += f"  *(follow-up: #legion-task-{tid})*"
                out.append(line)
            else:
                out.append(f"- {item}")
    else:
        out.append("_(none)_")
    out.append("")
    out.append("### Deferred")
    deferred = retro.get("deferred") or []
    if deferred:
        for item in deferred:
            if isinstance(item, dict):
                what = item.get("item") or ""
                reason = item.get("reason") or ""
                out.append(f"- **{what}** — {reason}")
            else:
                out.append(f"- {item}")
    else:
        out.append("_(nothing deferred — per Zero's NO DEFERRING policy)_")
    return "\n".join(out)


def _render_body(sprint: Dict[str, Any], tasks: Iterable[Dict[str, Any]]) -> str:
    name = sprint.get("name") or "Untitled Sprint"
    parts: List[str] = []
    parts.append(_frontmatter(sprint))
    parts.append("")
    parts.append(f"# {name}")
    parts.append("")
    goal = sprint.get("goal")
    if goal:
        parts.append("## Goal")
        parts.append(goal.strip())
        parts.append("")
    description = sprint.get("description")
    if description:
        parts.append("## Description")
        parts.append(description.strip())
        parts.append("")
    parts.append("## Tasks")
    parts.append(_render_tasks(tasks))
    parts.append("")
    parts.append("## Retrospective")
    parts.append(_render_retrospective(sprint.get("retrospective_data")))
    parts.append("")
    return "\n".join(parts)


def _atomic_write(path: Path, body: str) -> None:
    """Write body to path atomically via temp file + replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


async def render_sprint(sprint_id: int) -> Optional[Path]:
    """Re-render the vault markdown file for a Zero sprint.

    Pulls sprint + tasks from Legion (via Zero's legion_client) and writes
    `/vault/legion/Sprints/<hub>/<NN>-<slug>.md`. Returns the path written
    or None if Legion has no such sprint.
    """
    client = get_legion_client()
    try:
        legion_sprint = await client.get_sprint(sprint_id)
    except Exception as exc:  # noqa: BLE001
        _logger.error("vault_renderer_legion_fetch_failed", sprint_id=sprint_id, error=str(exc))
        return None
    if not legion_sprint:
        _logger.warning("vault_renderer_sprint_missing", sprint_id=sprint_id)
        return None
    # Legion's GET /api/sprints/{id} returns {sprint: {...}, tasks: [...]}.
    if "sprint" in legion_sprint and isinstance(legion_sprint["sprint"], dict):
        sprint_data = legion_sprint["sprint"]
        tasks = legion_sprint.get("tasks") or []
    else:
        sprint_data = legion_sprint
        try:
            tasks = await client.list_tasks(sprint_id=sprint_id)
        except Exception:  # noqa: BLE001
            tasks = []

    path = _file_path_for(sprint_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _render_body(sprint_data, tasks)
    _atomic_write(path, body)
    _logger.info("vault_renderer_wrote", sprint_id=sprint_id, path=str(path))
    return path


def fire_render(sprint_id: int) -> None:
    """Fire-and-forget render with done-callback so failures land in logs."""

    async def _run() -> None:
        try:
            await render_sprint(sprint_id)
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "vault_renderer_failed", sprint_id=sprint_id, error=str(exc), exc_info=True
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _logger.warning("fire_render_no_loop", sprint_id=sprint_id)
        return
    task = loop.create_task(_run())

    def _on_done(t: asyncio.Task) -> None:
        try:
            t.result()
        except Exception as exc:  # noqa: BLE001
            _logger.error("fire_render_callback_error", sprint_id=sprint_id, error=str(exc))

    task.add_done_callback(_on_done)
