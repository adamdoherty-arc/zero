"""Morning Digest — 7-section rollup written into today's daily note.

SecondBrain Phase 4 §6. Runs at 6:30am via scheduler_service.

Sections, in order:
  1. North Star            (single line, today's win condition — placeholder if none)
  2. Calendar              (next 12h events + conflicts)
  3. Carry-over            (yesterday's unfinished top_3 + open tasks)
  4. Attention queue       (agent_alerts open, salience >= threshold, outside DND)
  5. Market briefing       (placeholder — wired up later when Magnus is live)
  6. PKM surfacing         (1-2 older notes relevant to today's calendar)
  7. Agent log             (what Zero did overnight — research reports, drift fires)

Writes to `20_Calendar/Daily/YYYY-MM-DD.md` under `## Agent Summary`. If the
daily note doesn't exist yet, creates a stub from the template.

Phase 2 wiring replaces the whole-file write with cyanheads MCP patch-heading,
which is the safe default once the Local REST API plugin is installed. For
now, this uses a simple marker-based section replace.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import and_, select

from app.db.models import (
    AgentAlertModel,
    DeepResearchReportModel,
    EmployeeCheckinModel,
    TaskModel,
)
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)

_MARKER = "## Agent Summary"
_MARKER_END = re.compile(r"^## ", re.MULTILINE)


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MorningDigestService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._vault = Path(self._settings.vault_path)

    def available(self) -> bool:
        return self._vault.is_dir()

    async def generate_and_write(self) -> dict[str, Any]:
        if not self.available():
            return {"status": "skipped", "reason": "vault_unavailable"}

        today = _today_iso()
        daily_path = self._vault / self._settings.vault_daily_subdir / f"{today}.md"
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        if not daily_path.exists():
            daily_path.write_text(self._stub_daily_note(today), encoding="utf-8")

        sections = await self._gather()
        body = self._render(today, sections)

        # Replace the `## Agent Summary` section idempotently.
        existing = daily_path.read_text(encoding="utf-8")
        new = self._replace_section(existing, _MARKER, body)
        daily_path.write_text(new, encoding="utf-8")

        logger.info("morning_digest_written", path=str(daily_path), bytes=len(body))
        return {
            "status": "ok",
            "path": str(daily_path.relative_to(self._vault)),
            "sections": list(sections.keys()),
            "bytes": len(body),
        }

    def _stub_daily_note(self, today: str) -> str:
        return (
            f"---\nid: {today}\ntype: daily\ndate: {today}\npartition: personal\n"
            f"agent_writable: [agent_reviewed, commits, meetings_count]\n"
            f"agent_append_section: \"## Agent Summary\"\ntags: [daily, log]\n---\n\n"
            f"# {today}\n\n## Today\n\n## Inbox\n\n## Notes\n\n"
            f"## Agent Summary\n\n## Commits\n\n## Research\n\n## Mic\n"
        )

    def _replace_section(self, existing: str, marker: str, new_body: str) -> str:
        idx = existing.find(marker)
        if idx == -1:
            # Append a new section at the end.
            return existing.rstrip() + f"\n\n{new_body.rstrip()}\n"
        # Find the next `## ` heading after the marker to bound the section.
        after = existing[idx + len(marker):]
        m = _MARKER_END.search(after)
        if m:
            end_abs = idx + len(marker) + m.start()
            return existing[:idx] + new_body.rstrip() + "\n\n" + existing[end_abs:]
        return existing[:idx] + new_body.rstrip() + "\n"

    async def _gather(self) -> dict[str, list[str]]:
        async with get_session() as session:
            # Tasks still open, ordered by priority desc
            open_tasks = list(
                (
                    await session.execute(
                        select(TaskModel)
                        .where(TaskModel.status.in_(("todo", "in_progress", "blocked")))
                        .order_by(TaskModel.priority.asc(), TaskModel.created_at.asc())
                        .limit(5)
                    )
                ).scalars().all()
            )

            # Open alerts above threshold
            alerts = list(
                (
                    await session.execute(
                        select(AgentAlertModel)
                        .where(
                            and_(
                                AgentAlertModel.status == "open",
                                AgentAlertModel.salience >= self._settings.min_interrupt_salience,
                            )
                        )
                        .order_by(AgentAlertModel.salience.desc())
                        .limit(5)
                    )
                ).scalars().all()
            )

            # Last completed research since yesterday
            since = _now() - timedelta(hours=24)
            research = list(
                (
                    await session.execute(
                        select(DeepResearchReportModel)
                        .where(
                            and_(
                                DeepResearchReportModel.status == "completed",
                                DeepResearchReportModel.completed_at >= since,
                            )
                        )
                        .order_by(DeepResearchReportModel.completed_at.desc())
                        .limit(5)
                    )
                ).scalars().all()
            )

            # Last employee check-in
            last_checkin = (
                await session.execute(
                    select(EmployeeCheckinModel)
                    .order_by(EmployeeCheckinModel.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

        sections: dict[str, list[str]] = {
            "North Star": ["_(set manually above)_"],
            "Calendar": ["_(calendar integration: pending Phase 4 GCal MCP)_"],
            "Carry-over": (
                [f"- `[{t.priority}]` {t.title} (id: {t.id})" for t in open_tasks]
                if open_tasks
                else ["_(no open tasks)_"]
            ),
            "Attention queue": (
                [f"- `[{a.severity}|sal={a.salience:.2f}]` {a.summary}" for a in alerts]
                if alerts
                else ["_(no open alerts above salience threshold)_"]
            ),
            "Market briefing": ["_(Magnus integration pending — Tradier MCP + EOD poller)_"],
            "PKM surfacing": ["_(vault retrieval surfacing pending Phase 2.5)_"],
            "Agent log": [],
        }

        if last_checkin and last_checkin.overall_grade is not None:
            sections["Agent log"].append(
                f"- Last employee check-in: overall {last_checkin.overall_grade:.0f}/100"
            )
        for r in research:
            summary = (r.executive_summary or "").strip().splitlines()
            first = summary[0] if summary else (r.query or "")
            sections["Agent log"].append(f"- Research: {r.query} — {first[:160]}")
        if not sections["Agent log"]:
            sections["Agent log"] = ["_(no overnight activity)_"]
        return sections

    def _render(self, today: str, sections: dict[str, list[str]]) -> str:
        lines = [_MARKER, "", f"_Generated {today} by Zero._", ""]
        for title, items in sections.items():
            lines.append(f"### {title}")
            lines.extend(items)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


_singleton: Optional[MorningDigestService] = None


def get_morning_digest_service() -> MorningDigestService:
    global _singleton
    if _singleton is None:
        _singleton = MorningDigestService()
    return _singleton
