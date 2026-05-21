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
            self._meeting_prep_section(),
            self._conflict_section(),
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

    async def _conflict_section(self) -> BriefSection:
        """F-72 — surface overlapping calendar events scheduled in the
        next 24 hours so the user can decline before T-0."""
        try:
            from datetime import datetime as _dt, timedelta as _td

            from app.services.calendar_service import get_calendar_service

            svc = get_calendar_service()
            now = _dt.now(tz=timezone.utc)
            events = await svc.list_events(
                start_date=now,
                end_date=now + _td(hours=24),
                limit=40,
            )
        except Exception as e:
            return BriefSection(title="Conflict alert", error=str(e))

        def _dt_from(val: Any) -> Optional[datetime]:
            if val is None:
                return None
            try:
                if isinstance(val, str):
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                if isinstance(val, datetime):
                    return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
            except Exception:
                return None
            return None

        items: list[dict[str, Any]] = []
        for ev in events:
            start = _dt_from(getattr(ev, "start_time", None) or getattr(ev, "start", None))
            end = _dt_from(getattr(ev, "end_time", None) or getattr(ev, "end", None))
            if start is None or end is None:
                continue
            items.append({
                "title": str(getattr(ev, "summary", None) or getattr(ev, "title", None) or "Untitled"),
                "start": start,
                "end": end,
            })
        items.sort(key=lambda e: e["start"])

        bullets: list[str] = []
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if b["start"] >= a["end"]:
                    continue
                bullets.append(
                    f"{a['start'].strftime('%H:%M')} {a['title']} ⟷ {b['start'].strftime('%H:%M')} {b['title']}"
                )
                if len(bullets) >= 5:
                    break
            if len(bullets) >= 5:
                break

        if not bullets:
            return BriefSection(
                title="Conflict alert",
                body="No overlapping meetings in the next 24 hours.",
            )
        return BriefSection(
            title="Conflict alert",
            body=f"{len(bullets)} overlap{'s' if len(bullets) != 1 else ''} in the next 24 hours — see the steward to decline one.",
            bullets=bullets,
        )

    async def _meeting_prep_section(self) -> BriefSection:
        """Per-meeting prep brief for events on today's calendar.

        For each event today, compose a one-paragraph "what this is
        probably about" via meeting_prep_service. The bullets stay short
        because the brief tile is dense already; full briefs are fetched
        on demand via POST /api/meetings/{id}/prep-brief.
        """
        try:
            from app.services.calendar_service import get_calendar_service
            from app.services.meeting_prep_service import build_prep_brief
            from datetime import datetime as _dt, timedelta as _td

            svc = get_calendar_service()
            now = _dt.now(timezone.utc)
            try:
                events = await svc.list_events(
                    start_date=now,
                    end_date=now + _td(hours=18),
                    limit=8,
                )
            except Exception:
                events = []
            if not events:
                return BriefSection(
                    title="Meeting prep",
                    body="No meetings scheduled in the next 18 hours.",
                )
            bullets: list[str] = []
            briefed = 0
            for ev in events:
                try:
                    brief = await build_prep_brief(
                        meeting_id=str(
                            getattr(ev, "id", None) or getattr(ev, "event_id", None) or ""
                        ),
                        calendar_event=ev,
                    )
                except Exception as exc:
                    logger.debug("daily_brief_prep_compose_failed", error=str(exc))
                    continue
                if not brief:
                    continue
                title = brief.get("title") or "Untitled meeting"
                summary = brief.get("summary") or ""
                bullets.append(f"{title} — {summary}")
                briefed += 1
                if briefed >= 5:
                    break
            return BriefSection(
                title="Meeting prep",
                body=(
                    f"{briefed} upcoming meeting{'s' if briefed != 1 else ''} have prep context."
                    if briefed
                    else "Couldn't compose prep briefs."
                ),
                bullets=bullets,
            )
        except Exception as e:
            return BriefSection(title="Meeting prep", error=str(e))

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
