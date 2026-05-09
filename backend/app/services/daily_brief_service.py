"""
Daily brief — composes the morning report Adam reads in the dashboard
and gets emailed.

Pulls inputs from existing services (each call is best-effort and degrades
to a "no data" line if its source is offline):

* unread / starred email summary per Gmail account
* today's calendar with conflicts
* ADA AI status (open work items, blockers, pending drafts, finance)
* yesterday's wins/learnings (zero_brain reflection)
* a single "what to work on first" recommendation

Output:

    BriefPayload(
        date="2026-05-09",
        sections=[BriefSection(title=..., body=..., bullets=...), ...],
        markdown="...",
        spoken_summary="Good morning Adam. Today you have ...",
    )

Surface:
* `routers/daily_brief.py` exposes ``GET /api/daily-brief/today``,
  ``GET /api/daily-brief/history``, ``POST /api/daily-brief/send-now``.
* `digest_email_service` formats the markdown for email and sends via
  the existing Gmail service.
* The scheduler in ``main.py`` registers a 7:00 local-time job that
  runs ``compose_today`` and dispatches both the dashboard cache and
  the email.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

CACHE_DIR = Path("workspace") / "daily_brief"
HISTORY_PATH = CACHE_DIR / "history.json"
TODAY_PATH = CACHE_DIR / "today.json"


@dataclass
class BriefSection:
    title: str
    body: str = ""
    bullets: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "bullets": list(self.bullets),
            "error": self.error,
        }


@dataclass
class BriefPayload:
    date: str
    sections: list[BriefSection] = field(default_factory=list)
    markdown: str = ""
    spoken_summary: str = ""
    generated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "sections": [s.to_dict() for s in self.sections],
            "markdown": self.markdown,
            "spoken_summary": self.spoken_summary,
            "generated_at": self.generated_at,
        }


class DailyBriefService:
    def __init__(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if not HISTORY_PATH.exists():
            HISTORY_PATH.write_text(json.dumps({"briefs": []}, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------
    async def compose_today(self) -> BriefPayload:
        today = date.today().isoformat()
        sections = await asyncio.gather(
            self._email_section(),
            self._calendar_section(),
            self._company_section(),
            self._finance_section(),
            self._reflection_section(),
            self._recommendation_section(),
            return_exceptions=False,
        )
        sections = [s for s in sections if s is not None]
        markdown = self._render_markdown(today, sections)
        spoken = self._render_spoken(today, sections)
        payload = BriefPayload(
            date=today,
            sections=sections,
            markdown=markdown,
            spoken_summary=spoken,
            generated_at=time.time(),
        )
        # Cache for the dashboard tile + history.
        try:
            TODAY_PATH.write_text(json.dumps(payload.to_dict(), indent=2), encoding="utf-8")
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            briefs = history.get("briefs") or []
            briefs.append(payload.to_dict())
            history["briefs"] = briefs[-90:]  # ~3 months
            HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("daily_brief_cache_write_failed", error=str(e))
        return payload

    async def latest(self) -> Optional[BriefPayload]:
        if not TODAY_PATH.exists():
            return None
        try:
            data = json.loads(TODAY_PATH.read_text(encoding="utf-8"))
            return BriefPayload(
                date=data.get("date") or "",
                sections=[BriefSection(**s) for s in data.get("sections") or []],
                markdown=data.get("markdown") or "",
                spoken_summary=data.get("spoken_summary") or "",
                generated_at=float(data.get("generated_at") or 0),
            )
        except Exception:
            return None

    async def history(self, *, limit: int = 14) -> list[BriefPayload]:
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        out: list[BriefPayload] = []
        for r in (data.get("briefs") or [])[-limit:]:
            out.append(BriefPayload(
                date=r.get("date") or "",
                sections=[BriefSection(**s) for s in r.get("sections") or []],
                markdown=r.get("markdown") or "",
                spoken_summary=r.get("spoken_summary") or "",
                generated_at=float(r.get("generated_at") or 0),
            ))
        return out

    # ------------------------------------------------------------------
    # Section composers
    # ------------------------------------------------------------------
    async def _email_section(self) -> BriefSection:
        try:
            from app.services.email_automation_service import (
                get_email_automation_service,
            )
            svc = get_email_automation_service()
            try:
                summary = await svc.morning_brief()  # type: ignore[attr-defined]
            except AttributeError:
                summary = None
            if summary:
                if isinstance(summary, dict):
                    return BriefSection(
                        title="Inbox",
                        body=str(summary.get("body") or "")[:1000],
                        bullets=list(summary.get("bullets") or []),
                    )
                return BriefSection(title="Inbox", body=str(summary)[:1000])
            return BriefSection(title="Inbox", body="No fresh email summary available.")
        except Exception as e:
            return BriefSection(title="Inbox", error=str(e))

    async def _calendar_section(self) -> BriefSection:
        try:
            from app.services.calendar_service import get_calendar_service
            svc = get_calendar_service()
            try:
                today = await svc.today_summary()  # type: ignore[attr-defined]
            except AttributeError:
                today = None
            if not today:
                return BriefSection(title="Today's calendar", body="Calendar summary unavailable.")
            if isinstance(today, dict):
                events = today.get("events") or []
                bullets = []
                for ev in events[:6]:
                    when = ev.get("start") or ev.get("when") or ""
                    title = ev.get("title") or ev.get("summary") or "Untitled"
                    bullets.append(f"{when} — {title}")
                return BriefSection(
                    title="Today's calendar",
                    body=str(today.get("summary") or "")[:400],
                    bullets=bullets,
                )
            return BriefSection(title="Today's calendar", body=str(today)[:1000])
        except Exception as e:
            return BriefSection(title="Today's calendar", error=str(e))

    async def _company_section(self) -> BriefSection:
        bullets: list[str] = []
        try:
            from app.services.company_work_item_service import (
                get_company_work_item_service,
            )
            try:
                items = await get_company_work_item_service().list_open()  # type: ignore[attr-defined]
            except AttributeError:
                items = []
            for it in (items or [])[:6]:
                title = (
                    getattr(it, "title", None)
                    or (it.get("title") if isinstance(it, dict) else "open item")
                )
                bullets.append(f"open: {title}")
        except Exception as e:
            return BriefSection(title="ADA AI", error=str(e))

        try:
            from app.services.llc_guidance_service import get_llc_guidance_service
            try:
                checklist = await get_llc_guidance_service().pending_today()  # type: ignore[attr-defined]
            except AttributeError:
                checklist = []
            for it in (checklist or [])[:4]:
                title = (
                    getattr(it, "title", None)
                    or (it.get("title") if isinstance(it, dict) else "checklist item")
                )
                bullets.append(f"LLC: {title}")
        except Exception:
            pass

        return BriefSection(
            title="ADA AI",
            body="Open work and LLC checklist items.",
            bullets=bullets or ["No open items right now."],
        )

    async def _finance_section(self) -> BriefSection:
        try:
            from app.services.bookkeeper_service import get_bookkeeper_service
            snap = await get_bookkeeper_service().snapshot()
            bullets = [
                f"YTD revenue: ${snap.revenue:,.0f}",
                f"YTD expenses: ${snap.expenses:,.0f}",
                f"Net: ${snap.net:,.0f}",
                f"Estimated quarterly tax: ${snap.estimated_tax:,.0f}",
                f"Pending drafts to review: {snap.pending_drafts}",
            ]
            return BriefSection(
                title="Finance",
                body=f"{snap.entity} {snap.period} (backend: {snap.backend})",
                bullets=bullets,
            )
        except Exception as e:
            return BriefSection(title="Finance", error=str(e))

    async def _reflection_section(self) -> BriefSection:
        try:
            from app.services.reflection_service import get_reflection_service
            svc = get_reflection_service()
            try:
                last = await svc.latest_summary()  # type: ignore[attr-defined]
            except AttributeError:
                last = None
            if not last:
                return BriefSection(
                    title="Yesterday",
                    body="No reflection summary yet — Reachy will start producing them as outcomes accumulate.",
                )
            if isinstance(last, dict):
                return BriefSection(
                    title="Yesterday",
                    body=str(last.get("summary") or "")[:600],
                    bullets=list(last.get("wins") or [])[:5],
                )
            return BriefSection(title="Yesterday", body=str(last)[:600])
        except Exception as e:
            return BriefSection(title="Yesterday", error=str(e))

    async def _recommendation_section(self) -> BriefSection:
        # Single "what to work on first" recommendation. Pulls from open
        # company items + LLC checklist; falls back to a sensible default
        # so the brief never lands empty.
        try:
            from app.services.company_work_item_service import (
                get_company_work_item_service,
            )
            items = []
            try:
                items = await get_company_work_item_service().list_top_priority(  # type: ignore[attr-defined]
                    limit=1,
                )
            except AttributeError:
                items = []
            if items:
                top = items[0]
                title = (
                    getattr(top, "title", None)
                    or (top.get("title") if isinstance(top, dict) else None)
                    or "your top open item"
                )
                return BriefSection(
                    title="Start with",
                    body=f"Begin the day on: {title}.",
                )
        except Exception:
            pass
        return BriefSection(
            title="Start with",
            body="Begin the day with the oldest pending email draft and your top calendar prep.",
        )

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------
    def _render_markdown(self, today: str, sections: list[BriefSection]) -> str:
        out = [f"# Daily brief — {today}", ""]
        for s in sections:
            out.append(f"## {s.title}")
            if s.error:
                out.append(f"_unavailable: {s.error}_")
            if s.body:
                out.append(s.body)
            for b in s.bullets:
                out.append(f"- {b}")
            out.append("")
        return "\n".join(out)

    def _render_spoken(self, today: str, sections: list[BriefSection]) -> str:
        # Short, voice-friendly. Avoid markdown, keep sentence cadence
        # natural for TTS.
        parts = [f"Good morning Adam. Today is {today}."]
        for s in sections:
            if s.error:
                continue
            if s.body:
                parts.append(f"{s.title}: {s.body}")
            for b in s.bullets[:3]:
                parts.append(b)
            if len(parts) > 14:
                break
        return " ".join(p.strip().rstrip(".") + "." for p in parts if p.strip())


@lru_cache(maxsize=1)
def get_daily_brief_service() -> DailyBriefService:
    return DailyBriefService()
