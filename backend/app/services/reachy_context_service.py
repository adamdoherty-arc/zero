"""
Reachy context service — environment-aware hints injected into the persona
prompt at voice-loop time.

Gives the LLM signal the user would expect Reachy to be aware of:
  * time of day ("it is 09:14 on Tuesday morning")
  * next calendar event within the lookahead window
  * whether Reachy is in meeting or pomodoro focus mode

The hints are appended to the persona prompt as a `### CURRENT CONTEXT`
block so every turn starts with fresh situational grounding. Cheap — the
calendar query hits the local cache, no external API.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()

LOOKAHEAD_MINUTES = 30
IMMINENT_MINUTES = 5


def _format_event(ev: "EventSummary") -> str:
    start = getattr(ev, "start_dt", None) or {}
    dt_raw = None
    if isinstance(start, dict):
        dt_raw = start.get("date_time") or start.get("date")
    elif isinstance(start, str):
        dt_raw = start
    if not dt_raw:
        return f'"{getattr(ev, "summary", "(untitled)")}"'
    try:
        when = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
    except Exception:
        when = None
    now = datetime.now(timezone.utc)
    if when and when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta_s = (when - now).total_seconds() if when else None
    label = getattr(ev, "summary", None) or "(untitled)"
    if delta_s is None:
        return f'"{label}"'
    if delta_s < 60:
        return f'"{label}" right now'
    if delta_s < 600:
        return f'"{label}" in {int(delta_s / 60)} min'
    if delta_s < 3600:
        return f'"{label}" in {int(delta_s / 60)} min'
    hrs = delta_s / 3600
    return f'"{label}" in {hrs:.1f} h'


async def build_context_hint(persona_id: str) -> Optional[str]:
    """
    Return a short `### CURRENT CONTEXT` block to append to the persona
    prompt, or None if there is nothing interesting to say.
    """
    try:
        lines: list[str] = []
        now_local = datetime.now().astimezone()
        greeting = _time_of_day_label(now_local.hour)
        lines.append(f"- Local time: {now_local.strftime('%A %H:%M')} ({greeting}).")

        # Pomodoro / meeting
        try:
            from app.services.reachy_presence_service import get_reachy_presence_service
            presence = get_reachy_presence_service()
            pom = presence.pomodoro_state()
            if pom.get("active"):
                phase = pom.get("phase")
                lines.append(f"- Pomodoro {phase} (cycle {pom.get('cycle_index')}). Do not interrupt focus.")
            meet = presence.meeting_state()
            if meet.get("active"):
                lines.append("- User is currently in a meeting. Keep replies short and whispered if asked.")
        except Exception:
            pass

        # Upcoming calendar
        try:
            from app.services.calendar_service import CalendarService
            cal = CalendarService()
            now_utc = datetime.now(timezone.utc)
            end_utc = now_utc + timedelta(minutes=LOOKAHEAD_MINUTES)
            events = await cal.list_events(start_date=now_utc, end_date=end_utc, limit=2)
            if events:
                ev = events[0]
                lines.append(f"- Upcoming: {_format_event(ev)}.")
                # If imminent, add a stronger hint
                start = getattr(ev, "start_dt", None) or {}
                dt_raw = start.get("date_time") if isinstance(start, dict) else None
                if dt_raw:
                    try:
                        when = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                        if when.tzinfo is None:
                            when = when.replace(tzinfo=timezone.utc)
                        delta_min = (when - now_utc).total_seconds() / 60.0
                        if 0 <= delta_min <= IMMINENT_MINUTES:
                            lines.append(
                                f"- That meeting starts in <{IMMINENT_MINUTES} min — "
                                "be proactive about reminding the user if it comes up."
                            )
                    except Exception:
                        pass
        except Exception:
            pass

        if len(lines) <= 1:
            # Time-of-day alone isn't interesting — skip to keep prompt tight.
            return None

        return "\n\n### CURRENT CONTEXT\n" + "\n".join(lines)
    except Exception as e:
        logger.debug("reachy_context_build_failed", error=str(e))
        return None


def _time_of_day_label(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"
