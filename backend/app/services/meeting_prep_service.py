"""Pre-meeting prep brief.

Five minutes before a meeting fires, surface the context the user needs:
- attendees and what we know about them (past meetings, recent email)
- the meeting series history if this is a recurring event
- any open tasks / sprints that name the meeting topic
- a one-paragraph "what this is probably about" summary

The brief is a Markdown blob written to the dashboard's daily-brief tile
and (when companion proactive_enabled is on) spoken through Reachy.

This is a v1 stub — the heavy lifting (cross-source LLM summary) lives
in the existing memory_facade + reachy_email + sprint_service modules
which it composes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def build_prep_brief(*, meeting_id: str | None, calendar_event: Any) -> dict[str, Any]:
    """Compose a meeting-prep brief for ``calendar_event``.

    Returns ``{title, when, attendees, prior_meetings, related_tasks,
    summary, markdown}``. Each block is best-effort — missing data shows
    up as an empty list rather than raising.
    """
    title = getattr(calendar_event, "summary", None) or getattr(
        calendar_event, "title", None
    ) or "Untitled meeting"
    start = getattr(calendar_event, "start_time", None) or getattr(
        calendar_event, "start", None
    )
    attendees: list[str] = list(getattr(calendar_event, "attendees", None) or [])
    location = getattr(calendar_event, "location", None)

    prior_meetings: list[dict[str, Any]] = []
    related_tasks: list[dict[str, Any]] = []
    attendee_notes: list[dict[str, Any]] = []

    try:
        from app.services.meeting_search_service import search_meetings  # type: ignore

        # past meetings whose title matches this event's title (recurring series)
        hits = await search_meetings(query=title, limit=3, kind="exact")
        for hit in hits or []:
            prior_meetings.append({
                "id": hit.get("id"),
                "title": hit.get("title"),
                "ended_at": hit.get("ended_at"),
                "summary": (hit.get("summary") or "")[:240],
            })
    except Exception as exc:
        logger.debug("prep_brief_search_meetings_failed", error=str(exc))

    try:
        from app.services.memory_facade import retrieve  # type: ignore

        for attendee in attendees[:6]:
            try:
                hits = await retrieve(query=attendee, limit=2, partitions=["user", "blocks"])
                if hits:
                    attendee_notes.append({"attendee": attendee, "notes": hits})
            except Exception:
                continue
    except Exception as exc:
        logger.debug("prep_brief_memory_lookup_failed", error=str(exc))

    # F-40: surface meeting-followup tasks still open for these attendees
    open_from_prior: list[dict[str, Any]] = []
    try:
        from app.services.meeting_open_actions_service import (
            get_meeting_open_actions_service,
        )

        open_from_prior = await get_meeting_open_actions_service().open_for_attendees(
            attendees=attendees, limit=5
        )
    except Exception as exc:
        logger.debug("prep_brief_open_actions_lookup_failed", error=str(exc))
    if open_from_prior:
        related_tasks = open_from_prior  # surface in the markdown render

    # F-47: cross-project references in the title / description.
    xproject: dict[str, Any] = {}
    try:
        from app.services.meeting_xproject_resolver import (
            get_meeting_xproject_resolver,
        )

        xproject = await get_meeting_xproject_resolver().resolve(
            title=title,
            description=getattr(calendar_event, "description", None)
            or getattr(calendar_event, "details", None),
        )
    except Exception as exc:
        logger.debug("prep_brief_xproject_resolve_failed", error=str(exc))

    summary = _compose_summary(title, location, attendees, prior_meetings)

    markdown = _render_markdown(
        title=title,
        when=start,
        location=location,
        attendees=attendees,
        prior_meetings=prior_meetings,
        related_tasks=related_tasks,
        attendee_notes=attendee_notes,
        summary=summary,
    )
    xproject_md = _render_xproject_section(xproject)
    if xproject_md:
        markdown = markdown.rstrip() + "\n\n" + xproject_md.rstrip() + "\n"

    return {
        "meeting_id": meeting_id,
        "title": title,
        "when": start.isoformat() if isinstance(start, datetime) else start,
        "location": location,
        "attendees": attendees,
        "prior_meetings": prior_meetings,
        "attendee_notes": attendee_notes,
        "related_tasks": related_tasks,
        "xproject": xproject,
        "summary": summary,
        "markdown": markdown,
    }


def _compose_summary(
    title: str,
    location: str | None,
    attendees: list[str],
    prior_meetings: list[dict[str, Any]],
) -> str:
    bits: list[str] = []
    if attendees:
        attendees_display = ", ".join(attendees[:4])
        if len(attendees) > 4:
            attendees_display += f" (+{len(attendees) - 4} more)"
        bits.append(f"{attendees_display} are on the invite")
    if location:
        bits.append(f"location: {location}")
    if prior_meetings:
        bits.append(
            f"{len(prior_meetings)} prior recording{'s' if len(prior_meetings) != 1 else ''} matched this title"
        )
    base = "; ".join(bits) if bits else "no prior context yet"
    return f"{title} — {base}."


def _render_markdown(
    *,
    title: str,
    when: Any,
    location: str | None,
    attendees: list[str],
    prior_meetings: list[dict[str, Any]],
    related_tasks: list[dict[str, Any]],
    attendee_notes: list[dict[str, Any]],
    summary: str,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"**When:** {when}",
    ]
    if location:
        lines.append(f"**Location:** {location}")
    if attendees:
        lines.append(f"**Attendees:** {', '.join(attendees)}")
    lines.extend(["", "## Summary", summary, ""])
    if prior_meetings:
        lines.append("## Prior meetings in this series")
        for pm in prior_meetings:
            lines.append(f"- {pm.get('title')} ({pm.get('ended_at')}): {pm.get('summary')}")
        lines.append("")
    if attendee_notes:
        lines.append("## What we know about attendees")
        for entry in attendee_notes:
            lines.append(f"- **{entry.get('attendee')}**")
            for note in entry.get("notes", [])[:3]:
                snippet = (
                    note.get("text", "") if isinstance(note, dict) else str(note)
                )[:200]
                lines.append(f"  - {snippet}")
        lines.append("")
    if related_tasks:
        lines.append("## Related tasks / sprints")
        for t in related_tasks:
            lines.append(f"- {t.get('title')}")
    return "\n".join(lines).strip() + "\n"


def _render_xproject_section(xproject: dict[str, Any] | None) -> str:
    """Optional cross-project links block. Returns empty string when
    there's nothing to surface."""
    if not xproject:
        return ""
    lines: list[str] = []
    sprints = xproject.get("legion_sprints") or []
    if sprints:
        lines.append("## Related Legion sprints")
        for s in sprints:
            slug = s.get("slug") or "?"
            name = s.get("name") or ""
            status = s.get("status") or ""
            if s.get("found", True):
                lines.append(f"- [{slug}] {name} ({status})")
            else:
                lines.append(f"- {slug} (mentioned, not found)")
        lines.append("")
    personal = xproject.get("personal_board") or []
    if personal:
        lines.append("## Related personal-board items")
        for p in personal:
            domain = p.get("domain") or ""
            lines.append(f"- {p.get('title')}" + (f" ({domain})" if domain else ""))
        lines.append("")
    return "\n".join(lines)


def is_due_for_brief(*, start_dt: datetime, now: datetime | None = None, lead_min: int = 5) -> bool:
    """Return True when ``start_dt`` is between (now + lead_min - 1) and
    (now + lead_min + 1) minutes — i.e. the 2-minute window centered at
    T-5min. The scheduler calls this per-event each tick."""
    now = now or datetime.now(timezone.utc)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    delta = (start_dt - now).total_seconds() / 60.0
    return (lead_min - 1.0) <= delta <= (lead_min + 1.0)
