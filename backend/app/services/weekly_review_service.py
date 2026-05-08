"""Weekly Review — Friday PM, GTD-flavored. SecondBrain Phase 4 §6.

Writes `20_Calendar/Weekly/YYYY-Www.md`. Three sections:
  - Get Clear: inbox bloat + stale tasks + unresolved drift alerts
  - Get Current: every active project's last_activity + next_action + blockers
  - Get Creative: someday/maybe candidates mined from research findings

Non-interactive for now. Phase 5 makes the Creative pass interactive through
the Ask Zero chat with the user reviewing + picking next week's top_3.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import and_, select

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
        if not self.available():
            return {"status": "skipped", "reason": "vault_unavailable"}

        label, today = _iso_week()
        target_dir = self._vault / "20_Calendar" / "Weekly"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{label}.md"

        body = await self._render(label, today)
        target.write_text(body, encoding="utf-8")
        logger.info("weekly_review_written", path=str(target), bytes=len(body))
        return {
            "status": "ok",
            "path": str(target.relative_to(self._vault)),
            "bytes": len(body),
        }

    async def _render(self, label: str, today: str) -> str:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        async with get_session() as session:
            # Get Clear
            stale_tasks = list(
                (
                    await session.execute(
                        select(TaskModel)
                        .where(
                            and_(
                                TaskModel.status.in_(("todo", "in_progress", "blocked")),
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
                        .where(TaskModel.status == "in_progress")
                        .order_by(TaskModel.updated_at.desc() if hasattr(TaskModel, "updated_at") else TaskModel.created_at.desc())
                        .limit(20)
                    )
                ).scalars().all()
            )

            # Get Creative — high-novelty findings not promoted to a topic yet.
            findings = list(
                (
                    await session.execute(
                        select(ResearchFindingModel)
                        .where(ResearchFindingModel.status != "archived")
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
                        .where(
                            and_(
                                DeepResearchReportModel.status == "completed",
                                DeepResearchReportModel.completed_at >= week_ago,
                            )
                        )
                        .order_by(DeepResearchReportModel.completed_at.desc())
                        .limit(20)
                    )
                ).scalars().all()
            )

        lines: list[str] = [
            f"---\nid: {label}\ntype: weekly\npartition: personal\nweek: {label}\n"
            f"generated: {today}\ntags: [weekly, review, agent]\n---\n",
            f"# Weekly Review — {label}",
            "",
            "## Get Clear",
            "",
            f"**Stale open tasks (>7d):** {len(stale_tasks)}",
        ]
        for t in stale_tasks[:8]:
            lines.append(f"- `[{t.priority}]` {t.title} (id: {t.id}, status: {t.status})")
        lines.append("")
        lines.append(f"**Open alerts:** {len(open_alerts)}")
        for a in open_alerts[:8]:
            lines.append(f"- `[{a.severity}|sal={a.salience:.2f}]` {a.summary}")
        lines.append("")

        lines.extend(["## Get Current", ""])
        lines.append(f"**In-progress tasks:** {len(active_tasks)}")
        for t in active_tasks[:12]:
            lines.append(f"- {t.title} (id: {t.id})")
        lines.append("")
        lines.append(f"**Research shipped this week:** {len(research)}")
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
