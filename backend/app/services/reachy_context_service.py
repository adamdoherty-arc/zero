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
        now_local = datetime.now(timezone.utc).astimezone()
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

        # Sight context — Phase 5 / Phase 7 of the Meta-glasses plan.
        # When a SightProvider is active with a fresh frame (<15 s old), run
        # a quick VLM describe and tell the LLM what the user can see. If
        # Reachy's own camera is ALSO live, add its DoA + face detection
        # summary so the persona understands who/where the user is looking.
        sight_line = await _build_sight_line()
        if sight_line:
            lines.append(sight_line)
        attention_line = await _build_attention_line()
        if attention_line:
            lines.append(attention_line)

        if len(lines) <= 1:
            # Time-of-day alone isn't interesting — skip to keep prompt tight.
            return None

        return "\n\n### CURRENT CONTEXT\n" + "\n".join(lines)
    except Exception as e:
        logger.debug("reachy_context_build_failed", error=str(e))
        return None


async def _build_sight_line() -> Optional[str]:
    """
    Return a "- You can see: X" line based on the active SightProvider's
    most recent frame, or None if nothing fresh is available. Runs the VLM
    but only if the frame is recent; results are cached for ~10 s so we
    don't VLM every single voice turn.
    """
    import time
    try:
        from app.services.sight import get_sight_registry
        from app.services.vision_vlm_service import get_vision_vlm_service
    except Exception:
        return None

    reg = get_sight_registry()
    prov = reg.get_active()
    if prov is None:
        return None
    try:
        status = await prov.status()
    except Exception:
        return None
    if not status.active or not status.last_frame_ts:
        return None
    if (time.time() - status.last_frame_ts) > 15.0:
        return None

    global _SIGHT_CACHE
    now = time.time()
    cache = _SIGHT_CACHE
    if cache and (now - cache.get("ts", 0)) < 10.0 and cache.get("provider") == prov.name:
        caption = cache.get("caption", "")
    else:
        jpeg = await prov.get_latest_frame()
        if not jpeg:
            return None
        scene = await get_vision_vlm_service().describe_scene(jpeg)
        caption = scene.get("caption", "").strip()
        _SIGHT_CACHE = {"ts": now, "caption": caption, "provider": prov.name}

    if not caption:
        return None
    # Trim to one sentence so the prompt stays tight.
    first = caption.split(". ")[0].strip().rstrip(".")
    if len(first) > 160:
        first = first[:160].rstrip() + "…"
    return f"- You can see (via {prov.name}): {first}."


# Sight VLM cache keyed by provider — Phase 5.
_SIGHT_CACHE: dict = {}


async def _build_attention_line() -> Optional[str]:
    """Phase 7: cross-reference Reachy presence with sight to describe user attention."""
    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        presence = get_reachy_presence_service()
        if not hasattr(presence, "user_attention_state"):
            return None
        state = await presence.user_attention_state()
    except Exception:
        return None
    if not state:
        return None
    label = state.get("label") if isinstance(state, dict) else str(state)
    if not label:
        return None
    mapping = {
        "with_reachy": "- User is directly engaged with you (Reachy) right now.",
        "at_screen": "- User is focused on a screen / laptop right now.",
        "moving": "- User is moving around; they might not be at their desk.",
        "away": "- User appears to be away from Reachy.",
    }
    return mapping.get(label)


async def build_context_debug(
    persona_id: str | None = None,
    *,
    include_sight: bool = True,
) -> dict:
    """
    Structured version of build_context_hint for UI display. Returns a dict
    with every knob Reachy is aware of right now, so the frontend can render
    chips like "🕒 Friday afternoon" or "📅 Team sync in 12m" without the
    user having to squint at the raw prompt string.
    """
    out: dict = {
        "local_time": None,
        "time_of_day": None,
        "pomodoro": None,
        "meeting": None,
        "upcoming": None,
        "sight": None,
        "attention": None,
    }

    try:
        now_local = datetime.now(timezone.utc).astimezone()
        out["local_time"] = now_local.strftime("%A %H:%M")
        out["time_of_day"] = _time_of_day_label(now_local.hour)
    except Exception:
        pass

    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        presence = get_reachy_presence_service()
        pom = presence.pomodoro_state()
        if pom.get("active"):
            out["pomodoro"] = {
                "phase": pom.get("phase"),
                "cycle_index": pom.get("cycle_index"),
                "elapsed_s": pom.get("elapsed_s"),
            }
        meet = presence.meeting_state()
        if meet.get("active"):
            out["meeting"] = {
                "elapsed_s": meet.get("elapsed_s"),
                "doa_available": meet.get("doa_available"),
            }
    except Exception:
        pass

    try:
        from app.services.calendar_service import CalendarService
        cal = CalendarService()
        now_utc = datetime.now(timezone.utc)
        end_utc = now_utc + timedelta(minutes=LOOKAHEAD_MINUTES)
        events = await cal.list_events(start_date=now_utc, end_date=end_utc, limit=2)
        if events:
            ev = events[0]
            start = getattr(ev, "start_dt", None) or {}
            dt_raw = start.get("date_time") if isinstance(start, dict) else None
            minutes = None
            if dt_raw:
                try:
                    when = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    minutes = (when - now_utc).total_seconds() / 60.0
                except Exception:
                    minutes = None
            out["upcoming"] = {
                "label": getattr(ev, "summary", None) or "(untitled)",
                "minutes": round(minutes, 1) if minutes is not None else None,
                "imminent": bool(minutes is not None and 0 <= minutes <= IMMINENT_MINUTES),
            }
    except Exception:
        pass

    try:
        sight = await _build_sight_line() if include_sight else None
        if sight:
            # Strip leading "- You can see (via X): " prefix for a compact chip.
            prefix = "- You can see (via "
            if sight.startswith(prefix) and "): " in sight:
                out["sight"] = sight.split("): ", 1)[1].rstrip(".")
            else:
                out["sight"] = sight.replace("- You can see", "").lstrip(" (").rstrip(".")
    except Exception:
        pass

    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        presence = get_reachy_presence_service()
        if hasattr(presence, "user_attention_state"):
            state = await presence.user_attention_state()
            if isinstance(state, dict):
                out["attention"] = state.get("label")
    except Exception:
        pass

    return out


def _time_of_day_label(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"
