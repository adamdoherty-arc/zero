"""Weekly Review — Friday PM, GTD-flavored. SecondBrain Phase 4 §6.

Writes `20_Calendar/Weekly/YYYY-Www.md`. Three sections:
  - Get Clear: stale tasks + unresolved drift alerts
  - Get Current: in-progress work + blocked work + research shipped this week
  - Get Creative: someday/maybe candidates mined from research findings

R-3 (supervise fc9c5829): this docstring used to promise "inbox bloat" in Get
Clear and "every active project's last_activity + next_action + blockers" in
Get Current. Neither was implemented — there is no inbox metric in this file,
and no query ever touched blocked work, so 19 live blocked tasks sat unflagged
while the docstring claimed the Friday review surfaced them. Blocked tasks are
now a real section; the per-project last_activity/next_action rollup and the
inbox metric are NOT implemented and are no longer claimed here.

Non-interactive for now. Phase 5 makes the Creative pass interactive through
the Ask Zero chat with the user reviewing + picking next week's top_3.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import and_, func, select

from app.db.models import (
    AgentAlertModel,
    DeepResearchReportModel,
    ResearchFindingModel,
    TaskModel,
)
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


def _iso_week() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}", now.strftime("%Y-%m-%d")


class WeeklyReviewService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._vault = Path(self._settings.vault_path)

    def available(self) -> bool:
        return self._vault.is_dir()

    async def generate_and_write(self) -> dict[str, Any]:
        # R-2 (supervise fc9c5829): Fix-141 F7 pushed the blocking `write_text`
        # off the event loop but left its siblings — `is_dir()` and `mkdir()` are
        # both synchronous syscalls running directly on the loop in this async
        # method, the exact class F7 closed. On a contended/network volume they
        # stall every concurrent coroutine for the syscall duration.
        if not await asyncio.to_thread(self.available):
            return {"status": "skipped", "reason": "vault_unavailable"}

        label, today = _iso_week()
        target_dir = self._vault / "20_Calendar" / "Weekly"
        await asyncio.to_thread(lambda: target_dir.mkdir(parents=True, exist_ok=True))
        target = target_dir / f"{label}.md"

        body = await self._render(label, today)
        # Fix-141 F7: blocking file write off the event loop.
        await asyncio.to_thread(target.write_text, body, encoding="utf-8")
        logger.info("weekly_review_written", path=str(target), bytes=len(body))
        return {
            "status": "ok",
            "path": str(target.relative_to(self._vault)),
            "bytes": len(body),
        }

    async def _render(self, label: str, today: str) -> str:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        # R-1 (supervise fc9c5829): every section header rendered
        # `len(<already-LIMITed list>)`, so the count silently saturated at the
        # page size. Live at the time of the fix: 87 stale open tasks reported as
        # "10", 23 open alerts reported as "10", 36 in-progress reported as "20".
        # Surfacing backlog bloat is the entire purpose of the GTD Get Clear pass,
        # and it was capped at exactly the number that hides bloat. Count in SQL,
        # list a bounded preview, and say so when the preview is partial.
        _stale_where = and_(
            TaskModel.status.notin_(("done", "archived")),
            TaskModel.created_at < week_ago,
        )
        _alerts_where = AgentAlertModel.status == "open"
        _active_where = TaskModel.status == "in_progress"
        _blocked_where = TaskModel.status == "blocked"
        _research_where = and_(
            DeepResearchReportModel.status == "completed",
            DeepResearchReportModel.completed_at >= week_ago,
        )

        async with get_session() as session:

            async def _count(model: Any, where: Any) -> int:
                return int(
                    (
                        await session.execute(
                            select(func.count()).select_from(model).where(where)
                        )
                    ).scalar()
                    or 0
                )

            stale_total = await _count(TaskModel, _stale_where)
            alerts_total = await _count(AgentAlertModel, _alerts_where)
            active_total = await _count(TaskModel, _active_where)
            blocked_total = await _count(TaskModel, _blocked_where)
            research_total = await _count(DeepResearchReportModel, _research_where)

            # Get Clear
            stale_tasks = list(
                (
                    await session.execute(
                        select(TaskModel)
                        .where(
                            and_(
                                # R1 (supervise ff278a1a): the GTD "Get Clear" stale
                                # sweep must include the DEFAULT status `backlog` (and
                                # on_hold/review/testing). The old todo/in_progress/
                                # blocked allowlist hid the most common forgotten-task
                                # bucket, so stale backlog items were invisible in the
                                # weekly review.
                                TaskModel.status.notin_(("done", "archived")),
                                TaskModel.created_at < week_ago,
                            )
                        )
                        .order_by(TaskModel.created_at.asc())
                        .limit(10)
                    )
                ).scalars().all()
            )
            open_alerts = list(
                (
                    await session.execute(
                        select(AgentAlertModel)
                        .where(AgentAlertModel.status == "open")
                        .order_by(AgentAlertModel.salience.desc())
                        .limit(10)
                    )
                ).scalars().all()
            )

            # Get Current
            active_tasks = list(
                (
                    await session.execute(
                        select(TaskModel)
                        .where(_active_where)
                        # Fix-141 F6: updated_at is nullable (onupdate only, no
                        # insert default) and Postgres DESC puts NULLS FIRST —
                        # never-touched rows sorted ABOVE genuinely recent work.
                        .order_by(func.coalesce(TaskModel.updated_at, TaskModel.created_at).desc())
                        .limit(20)
                    )
                ).scalars().all()
            )

            # R-3: blocked work. The module docstring promised blockers in Get
            # Current since the file was written; nothing ever queried them, so
            # 19 live blocked tasks were invisible to the weekly review. Oldest
            # first — a task blocked longest is the one most worth unblocking.
            blocked_tasks = list(
                (
                    await session.execute(
                        select(TaskModel)
                        .where(_blocked_where)
                        .order_by(TaskModel.created_at.asc())
                        .limit(20)
                    )
                ).scalars().all()
            )

            # Get Creative — RECENT high-novelty findings not yet turned into a task.
            # R4 (supervise ff278a1a): the old query had no recency and no promoted
            # filter, so the same all-time top-5 rendered every week regardless of the
            # section's own "recent … not promoted" label.
            findings = list(
                (
                    await session.execute(
                        select(ResearchFindingModel)
                        .where(
                            and_(
                                ResearchFindingModel.status != "archived",
                                ResearchFindingModel.discovered_at >= week_ago,
                                ResearchFindingModel.linked_task_id.is_(None),
                            )
                        )
                        .order_by(ResearchFindingModel.novelty_score.desc())
                        .limit(5)
                    )
                ).scalars().all()
            )

            # Research shipped this week
            research = list(
                (
                    await session.execute(
                        select(DeepResearchReportModel)
                        .where(_research_where)
                        .order_by(DeepResearchReportModel.completed_at.desc())
                        .limit(20)
                    )
                ).scalars().all()
            )

        def _more(total: int, shown: int) -> str:
            """R-1: never let a bounded preview masquerade as the whole set."""
            return f" _(showing {shown} of {total})_" if total > shown else ""

        lines: list[str] = [
            f"---\nid: {label}\ntype: weekly\npartition: personal\nweek: {label}\n"
            f"generated: {today}\ntags: [weekly, review, agent]\n---\n",
            f"# Weekly Review — {label}",
            "",
            "## Get Clear",
            "",
            f"**Stale open tasks (>7d):** {stale_total}{_more(stale_total, min(len(stale_tasks), 8))}",
        ]
        for t in stale_tasks[:8]:
            lines.append(f"- `[{t.priority}]` {t.title} (id: {t.id}, status: {t.status})")
        lines.append("")
        lines.append(f"**Open alerts:** {alerts_total}{_more(alerts_total, min(len(open_alerts), 8))}")
        for a in open_alerts[:8]:
            lines.append(f"- `[{a.severity}|sal={a.salience:.2f}]` {a.summary}")
        lines.append("")

        lines.extend(["## Get Current", ""])
        lines.append(f"**In-progress tasks:** {active_total}{_more(active_total, min(len(active_tasks), 12))}")
        for t in active_tasks[:12]:
            lines.append(f"- {t.title} (id: {t.id})")
        lines.append("")
        lines.append(f"**Blocked tasks:** {blocked_total}{_more(blocked_total, min(len(blocked_tasks), 12))}")
        for t in blocked_tasks[:12]:
            lines.append(f"- {t.title} (id: {t.id})")
        lines.append("")
        lines.append(f"**Research shipped this week:** {research_total}{_more(research_total, min(len(research), 8))}")
        for r in research[:8]:
            when = r.completed_at.strftime("%Y-%m-%d") if r.completed_at else ""
            lines.append(f"- {when} — {r.query}")
        lines.append("")

        lines.extend(["## Get Creative", "", "Candidate directions from recent findings:"])
        if findings:
            for f in findings:
                lines.append(f"- **{f.title}** (novelty {f.novelty_score:.0f}/100) — {(f.snippet or '')[:180]}")
        else:
            lines.append("_(no high-novelty findings queued)_")
        lines.append("")

        return "\n".join(lines) + "\n"


_singleton: Optional[WeeklyReviewService] = None


def get_weekly_review_service() -> WeeklyReviewService:
    global _singleton
    if _singleton is None:
        _singleton = WeeklyReviewService()
    return _singleton
