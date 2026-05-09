"""
Reachy voice-intent router.

Takes a transcribed voice command (from the host_agent wake loop), classifies
it against a small set of built-in intents, and either handles it directly
(recording control, calendar peek, inbox peek) or forwards to the Claude Agent
SDK messaging bridge for open-ended queries.

All responses are TTS-friendly plain prose — the host_agent pipes them to the
Reachy speaker.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.reachy_motion_policy import body_motion_allowed, body_motion_locked_payload

router = APIRouter()
logger = structlog.get_logger()


HOST_AGENT_URL = os.getenv("ZERO_HOST_AGENT_URL", "http://host.docker.internal:18796").rstrip("/")

# Hard per-provider ceiling for voice chat. Without this a single stalled
# Kimi/Gemini/vLLM call blocks the whole fallback chain (each provider's own
# httpx client allows up to 180 s). Voice has to feel alive — 8 s per provider
# means even a full 3-provider fallback chain fits under the 30 s backend
# proxy ceiling, while still giving each healthy provider enough time for a
# short spoken reply (typical: 1-3 s).
_VOICE_CHAT_PROVIDER_TIMEOUT = 8.0
# Overall wall-clock deadline for the entire fallback walk. Once exceeded we
# stop trying new providers and return the canned "models unreachable" line.
_VOICE_CHAT_TOTAL_DEADLINE = 22.0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class IntentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(default="reachy_wake", description="Origin marker for logging")


class IntentResponse(BaseModel):
    response_text: str
    intent: str
    took_action: bool = False
    detail: Optional[dict] = None


class ProviderStatus(BaseModel):
    id: str
    label: str
    provider: str
    model: str
    ok: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    checked_at: float  # epoch seconds


class ProvidersStatusResponse(BaseModel):
    active_id: str
    checked_at: float
    providers: list[ProviderStatus]


# ---------------------------------------------------------------------------
# Intent classifier (keyword-first, LLM fallback)
# ---------------------------------------------------------------------------

_RECORD_START_PATTERNS = [
    r"\bstart\b.{0,20}\b(recording|record|meeting)\b",
    r"\brecord\b.{0,20}\b(this|meeting|me|our|the)\b",
    r"\bstart\s+a\s+meeting\b",
    r"\bget\s+ready\s+for\s+(a\s+)?meeting\b",
    r"\bbegin\s+(the\s+)?(meeting|recording)\b",
]
_RECORD_STOP_PATTERNS = [
    r"\bstop\b.{0,20}\b(recording|record|meeting)\b",
    r"\bend\s+(the\s+)?(meeting|recording)\b",
    r"\bfinish\s+(the\s+)?(meeting|recording)\b",
    r"\bthat'?s?\s+(it|all)\s+(for\s+)?(the\s+)?meeting\b",
]
_CALENDAR_PATTERNS = [
    r"\bwhat'?s\s+on\s+my\s+(calendar|schedule)\b",
    r"\b(my|the)\s+(calendar|schedule)\b",
    r"\bupcoming\s+(meetings|events|calls)\b",
    r"\bnext\s+(meeting|event|call)\b",
    r"\bwhat'?s\s+next\b",
    r"\bagenda\s+(for\s+)?today\b",
]
_EMAIL_PATTERNS = [
    r"\bread\s+(my\s+)?(emails?|inbox|mail)\b",
    r"\b(any|new)\s+(emails?|mail|messages)\b",
    r"\bcheck\s+(my\s+)?(email|inbox|mail)\b",
    r"\bwhat'?s?\s+in\s+my\s+inbox\b",
]
_COMPANY_PATTERNS = [
    r"\b(company|business)\s+(status|brief|report|dashboard)\b",
    r"\b(doherty\s+applied\s+ai|company\s+os|zero\s+company)\b",
    r"\bwhat\s+did\s+zero\s+do\s+overnight\b",
    r"\b(overnight|morning)\s+(company\s+)?report\b",
    r"\b(company|business)\s+(approvals?|blockers?|blocked|tasks?)\b",
    r"\b(llc|formation|sunbiz|ein|duval|cpa)\s+(status|tasks?|checklist)\b",
    r"\bwhat\s+should\s+i\s+work\s+on\s+today\b",
]
_ROBOT_WAKE_PATTERNS = [
    r"\b(wake|start|turn\s+on)\b.{0,20}\b(reachy|robot|your\s+body)\b",
    r"\b(reachy|robot)\b.{0,20}\b(wake\s+up|turn\s+on)\b",
]
_ROBOT_SLEEP_PATTERNS = [
    r"\b(sleep|rest|stand\s+down|turn\s+off)\b.{0,20}\b(reachy|robot|your\s+body)\b",
    r"\b(reachy|robot)\b.{0,20}\b(go\s+to\s+sleep|rest|turn\s+off)\b",
]
_FOCUS_START_PATTERNS = [
    r"\b(start|begin)\b.{0,20}\b(focus|pomodoro|deep\s+work)\b",
    r"\b(focus|pomodoro)\b.{0,20}\b(timer|block|session)\b",
]
_FOCUS_STOP_PATTERNS = [
    r"\b(stop|end|cancel)\b.{0,20}\b(focus|pomodoro|deep\s+work)\b",
]
_AMBIENT_ON_PATTERNS = [
    r"\b(turn|switch|set)\b.{0,20}\b(ambient|presence)\b.{0,20}\b(on|enable|start)\b",
    r"\bbe\s+present\b",
]
_AMBIENT_OFF_PATTERNS = [
    r"\b(turn|switch|set)\b.{0,20}\b(ambient|presence)\b.{0,20}\b(off|disable|stop)\b",
    r"\bstay\s+still\b",
]
_ASSISTANT_ORCHESTRATION_HINTS = (
    "task", "todo", "project", "schedule", "calendar", "email", "inbox",
    "meeting", "recording", "note", "remember", "system", "health", "docker",
    "company", "business", "llc", "formation",
)


def _match_any(text: str, patterns: list[str]) -> bool:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def classify_intent(text: str) -> str:
    """Return one of the built-in Reachy command intents, or chat."""
    t = text.strip().lower()
    if _match_any(t, _RECORD_START_PATTERNS):
        return "record_start"
    if _match_any(t, _RECORD_STOP_PATTERNS):
        return "record_stop"
    if _match_any(t, _CALENDAR_PATTERNS):
        return "calendar"
    if _match_any(t, _EMAIL_PATTERNS):
        return "email"
    if _match_any(t, _COMPANY_PATTERNS):
        return "company"
    if _match_any(t, _ROBOT_WAKE_PATTERNS):
        return "robot_wake"
    if _match_any(t, _ROBOT_SLEEP_PATTERNS):
        return "robot_sleep"
    if _match_any(t, _FOCUS_START_PATTERNS):
        return "focus_start"
    if _match_any(t, _FOCUS_STOP_PATTERNS):
        return "focus_stop"
    if _match_any(t, _AMBIENT_ON_PATTERNS):
        return "ambient_on"
    if _match_any(t, _AMBIENT_OFF_PATTERNS):
        return "ambient_off"
    return "chat"


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------

async def _handle_record_start(text: str) -> IntentResponse:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.post(
                f"{HOST_AGENT_URL}/record/start",
                json={"title": f"Voice meeting {datetime.now().strftime('%Y-%m-%d %H:%M')}", "source": "mic"},
            )
            if resp.status_code == 409:
                return IntentResponse(
                    response_text="We're already recording.",
                    intent="record_start",
                    took_action=False,
                )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("reachy_intent_record_start_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't start the recording.",
            intent="record_start",
            took_action=False,
        )
    return IntentResponse(
        response_text="Recording started.",
        intent="record_start",
        took_action=True,
        detail={"meeting_id": data.get("meeting_id")},
    )


async def _handle_record_stop(text: str) -> IntentResponse:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.post(f"{HOST_AGENT_URL}/record/stop")
            if resp.status_code == 400:
                return IntentResponse(
                    response_text="There's no recording to stop.",
                    intent="record_stop",
                    took_action=False,
                )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("reachy_intent_record_stop_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't stop the recording.",
            intent="record_stop",
            took_action=False,
        )
    dur = float(data.get("duration_seconds") or 0)
    dur_phrase = _spoken_duration(dur)
    return IntentResponse(
        response_text=f"Recording stopped after {dur_phrase}. Summary will be ready shortly.",
        intent="record_stop",
        took_action=True,
        detail=data,
    )


async def _handle_calendar(text: str) -> IntentResponse:
    try:
        from app.services.calendar_service import get_calendar_service
        svc = get_calendar_service()
        now = datetime.now(tz=timezone.utc)
        events = await svc.list_events(
            start_date=now,
            end_date=now + timedelta(hours=24),
            limit=5,
        )
    except Exception as e:
        logger.warning("reachy_intent_calendar_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't reach your calendar. You may need to reconnect Google.",
            intent="calendar",
            took_action=False,
        )
    if not events:
        return IntentResponse(
            response_text="Your calendar is clear for the next twenty-four hours.",
            intent="calendar",
            took_action=True,
            detail={"count": 0},
        )
    phrases = []
    for ev in events[:3]:
        # EventSummary is a pydantic model — support dict-like and attr-like.
        title = _attr_or_key(ev, "summary", "title", default="an event")
        start = _attr_or_key(ev, "start_time", "start")
        phrase = _spoken_event(str(title).strip(), start)
        if phrase:
            phrases.append(phrase)
    summary = _natural_join(phrases)
    return IntentResponse(
        response_text=f"You have {summary}.",
        intent="calendar",
        took_action=True,
        detail={"count": len(events)},
    )


async def _handle_email(text: str) -> IntentResponse:
    try:
        from app.services.gmail_service import get_gmail_service
        from app.models.email import EmailStatus
        svc = get_gmail_service()
        emails = await svc.list_emails(status=EmailStatus.UNREAD, limit=3)
    except Exception as e:
        logger.warning("reachy_intent_email_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't reach Gmail. You may need to reconnect it.",
            intent="email",
            took_action=False,
        )
    if not emails:
        return IntentResponse(
            response_text="You have no unread emails right now.",
            intent="email",
            took_action=True,
            detail={"count": 0},
        )
    lead = f"You have {len(emails)} unread email" + ("s" if len(emails) > 1 else "") + ". "
    snippets = []
    for m in emails[:3]:
        raw_from = str(_attr_or_key(m, "sender", "from_name", "from_address", default="an unknown sender"))
        frm = raw_from.split("<")[0].strip() or "an unknown sender"
        subj = str(_attr_or_key(m, "subject", default="no subject")).strip() or "no subject"
        snippets.append(f"From {frm}: {subj}")
    body = ". ".join(snippets) + "."
    return IntentResponse(
        response_text=lead + body,
        intent="email",
        took_action=True,
        detail={"count": len(emails)},
    )


async def _handle_company(text: str) -> IntentResponse:
    try:
        from app.services.company_operator_service import get_company_operator_service
        result = await get_company_operator_service().spoken_company_summary(text)
    except Exception as e:
        logger.warning("reachy_intent_company_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't reach the company operator right now.",
            intent="company",
            took_action=False,
        )
    return IntentResponse(
        response_text=str(result.get("response_text") or "Company status is unavailable."),
        intent="company",
        took_action=False,
        detail=result,
    )


async def _handle_robot_wake(text: str) -> IntentResponse:
    if not body_motion_allowed(surface="intent:robot_wake").get("allowed"):
        return IntentResponse(
            response_text="Reachy's body motion is locked off for safety.",
            intent="robot_wake",
            took_action=False,
            detail=body_motion_locked_payload(surface="intent:robot_wake"),
        )
    try:
        from app.services.reachy_service import get_reachy_service
        result = await get_reachy_service().wake_up()
    except Exception as e:
        logger.warning("reachy_intent_robot_wake_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't wake the robot body.",
            intent="robot_wake",
            took_action=False,
        )
    if result.get("error"):
        return IntentResponse(
            response_text="Reachy's body is not available right now.",
            intent="robot_wake",
            took_action=False,
            detail=result,
        )
    return IntentResponse(
        response_text="Reachy is awake.",
        intent="robot_wake",
        took_action=True,
        detail=result,
    )


async def _handle_robot_sleep(text: str) -> IntentResponse:
    if not body_motion_allowed(surface="intent:robot_sleep").get("allowed"):
        return IntentResponse(
            response_text="Reachy's body motion is locked off for safety.",
            intent="robot_sleep",
            took_action=False,
            detail=body_motion_locked_payload(surface="intent:robot_sleep"),
        )
    try:
        from app.services.reachy_service import get_reachy_service
        result = await get_reachy_service().goto_sleep()
    except Exception as e:
        logger.warning("reachy_intent_robot_sleep_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't put Reachy to sleep.",
            intent="robot_sleep",
            took_action=False,
        )
    if result.get("error"):
        return IntentResponse(
            response_text="Reachy's body is not available right now.",
            intent="robot_sleep",
            took_action=False,
            detail=result,
        )
    return IntentResponse(
        response_text="Reachy is resting.",
        intent="robot_sleep",
        took_action=True,
        detail=result,
    )


def _extract_minutes(text: str, default: int = 25) -> int:
    m = re.search(r"\b(\d{1,3})\s*(minutes?|mins?)\b", text, re.IGNORECASE)
    if not m:
        return default
    return max(5, min(90, int(m.group(1))))


async def _handle_focus_start(text: str) -> IntentResponse:
    focus_minutes = _extract_minutes(text)
    if not body_motion_allowed(surface="intent:focus_start").get("allowed"):
        return IntentResponse(
            response_text="Focus mode needs body motion, and Reachy's body motion is locked off for safety.",
            intent="focus_start",
            took_action=False,
            detail=body_motion_locked_payload(surface="intent:focus_start"),
        )
    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        state = await get_reachy_presence_service().pomodoro_start(
            focus_minutes=focus_minutes,
            break_minutes=5,
        )
    except Exception as e:
        logger.warning("reachy_intent_focus_start_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't start the focus timer.",
            intent="focus_start",
            took_action=False,
        )
    return IntentResponse(
        response_text=f"Focus timer started for {focus_minutes} minutes.",
        intent="focus_start",
        took_action=True,
        detail=state,
    )


async def _handle_focus_stop(text: str) -> IntentResponse:
    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        state = await get_reachy_presence_service().pomodoro_stop()
    except Exception as e:
        logger.warning("reachy_intent_focus_stop_failed", error=str(e))
        return IntentResponse(
            response_text="I couldn't stop the focus timer.",
            intent="focus_stop",
            took_action=False,
        )
    return IntentResponse(
        response_text="Focus timer stopped.",
        intent="focus_stop",
        took_action=True,
        detail=state,
    )


async def _handle_ambient(enabled: bool) -> IntentResponse:
    if enabled and not body_motion_allowed(surface="intent:ambient_on").get("allowed"):
        return IntentResponse(
            response_text="Ambient presence needs body motion, and Reachy's body motion is locked off for safety.",
            intent="ambient_on",
            took_action=False,
            detail=body_motion_locked_payload(surface="intent:ambient_on"),
        )
    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        svc = get_reachy_presence_service()
        state = svc.ambient_start() if enabled else svc.ambient_stop()
    except Exception as e:
        logger.warning("reachy_intent_ambient_failed", enabled=enabled, error=str(e))
        return IntentResponse(
            response_text="I couldn't change ambient presence.",
            intent="ambient_on" if enabled else "ambient_off",
            took_action=False,
        )
    return IntentResponse(
        response_text="Ambient presence is on." if enabled else "Ambient presence is off.",
        intent="ambient_on" if enabled else "ambient_off",
        took_action=True,
        detail=state,
    )


def _attr_or_key(obj, *names, default=None):
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None:
                return v
        if isinstance(obj, dict) and obj.get(n) is not None:
            return obj[n]
    return default


REACHY_CHAT_SYSTEM = (
    "You are Zero, speaking through a Reachy Mini robot's speaker. "
    "Your reply will be synthesized by TTS and played aloud, so: "
    "respond in 1-3 short natural-spoken sentences, under 200 characters, "
    "no markdown, no bullets, no URLs, no emoji. "
    "Numbers and times in spoken form ('three p.m.', 'two emails'). "
    "Prefer direct useful answers over filler."
)


_NONSENSE_HINTS = ("microphone check", "mic check", "test test", "one two", "testing testing")


def _looks_like_nonsense(text: str) -> bool:
    """Audio-level artifacts that shouldn't hit the LLM."""
    low = text.lower().strip()
    if len(low) < 3:
        return True
    return any(h in low for h in _NONSENSE_HINTS)


async def _handle_zero_orchestration(text: str) -> IntentResponse | None:
    try:
        from app.services.orchestration_graph import invoke_orchestration
        result = await asyncio.wait_for(
            invoke_orchestration(
                message=text,
                thread_id="reachy_voice",
                channel="reachy_voice",
            ),
            timeout=10.0,
        )
    except Exception as e:
        logger.debug("reachy_zero_orchestration_fallback", error=str(e)[:200])
        return None

    spoken = str(result.get("result") or "").strip()
    if not spoken:
        return None
    spoken = spoken.replace("**", "").replace("`", "").replace("\n", " ").strip()
    if len(spoken) > 420:
        spoken = spoken[:420].rsplit(". ", 1)[0].strip() + "."
    return IntentResponse(
        response_text=spoken,
        intent="zero_assistant",
        took_action=True,
        detail={
            "route": result.get("route"),
            "thread_id": result.get("thread_id"),
            "conversation_id": result.get("conversation_id"),
        },
    )


async def _handle_chat(text: str) -> IntentResponse:
    """
    Fallback: open-ended chat.

    Uses whichever provider the user has selected via
    /api/reachy-intent/provider (vLLM local / Gemini / Kimi). If the active
    provider fails, walks through the other available ones in order so a flaky
    local vLLM doesn't block voice replies.
    """
    if _looks_like_nonsense(text):
        return IntentResponse(
            response_text="Mic is working. What would you like?",
            intent="chat",
            took_action=False,
        )

    if any(hint in text.lower() for hint in _ASSISTANT_ORCHESTRATION_HINTS):
        routed = await _handle_zero_orchestration(text)
        if routed is not None:
            return routed

    from time import monotonic

    from app.services.reachy_chat_provider import (
        AVAILABLE_PROVIDERS,
        get_active_provider,
    )
    from app.infrastructure.unified_llm_client import get_unified_llm_client

    active = get_active_provider()
    # Try active first, then the remaining ones in declared order.
    seen: set[str] = set()
    chain = [active] + [p for p in AVAILABLE_PROVIDERS if p.id != active.id]
    client = get_unified_llm_client()

    started = monotonic()
    last_error: Optional[str] = None
    # Structured audit trail — which providers we tried and how they fared.
    # Surfaced in IntentResponse.detail.tried_providers so the UI can render
    # "Tried vLLM (timeout), Gemini Flash (down). Switch to Kimi?".
    tried_providers: list[dict] = []
    for p in chain:
        key = f"{p.provider}:{p.model}"
        if key in seen:
            continue
        seen.add(key)
        # Bail once we've burned the whole voice-turn deadline. Better to
        # return a canned error than string the user along while every remaining
        # provider also times out.
        if monotonic() - started > _VOICE_CHAT_TOTAL_DEADLINE:
            logger.warning(
                "reachy_intent_chat_deadline_exceeded",
                elapsed_s=round(monotonic() - started, 1),
                deadline_s=_VOICE_CHAT_TOTAL_DEADLINE,
                remaining_providers=[r.id for r in chain if f"{r.provider}:{r.model}" not in seen],
            )
            last_error = f"voice deadline exceeded after {monotonic() - started:.0f}s"
            break
        try:
            reply = await asyncio.wait_for(
                client.chat(
                    prompt=text,
                    system=REACHY_CHAT_SYSTEM,
                    temperature=0.5,
                    max_tokens=200,
                    model=f"{p.provider}/{p.model}",
                ),
                timeout=_VOICE_CHAT_PROVIDER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            last_error = f"{p.id}: timed out after {_VOICE_CHAT_PROVIDER_TIMEOUT:.0f}s"
            logger.warning(
                "reachy_intent_chat_provider_timeout",
                provider_id=p.id,
                seconds=_VOICE_CHAT_PROVIDER_TIMEOUT,
            )
            tried_providers.append({
                "id": p.id, "status": "timeout",
                "error": f"no response in {int(_VOICE_CHAT_PROVIDER_TIMEOUT)}s",
            })
            continue
        except Exception as e:
            last_error = f"{p.id}: {e}"
            logger.warning(
                "reachy_intent_chat_provider_failed",
                provider_id=p.id,
                error=str(e)[:200],
            )
            tried_providers.append({
                "id": p.id, "status": "failed", "error": str(e)[:160],
            })
            continue
        reply = (reply or "").strip().replace("**", "").replace("`", "").strip()
        if not reply:
            last_error = f"{p.id}: empty response"
            continue
        if len(reply) > 400:
            reply = reply[:400].rsplit(". ", 1)[0] + "."
        tried_providers.append({"id": p.id, "status": "succeeded"})
        return IntentResponse(
            response_text=reply,
            intent="chat",
            took_action=False,
            detail={
                "provider_id": p.id,
                "provider": p.provider,
                "model": p.model,
                "tried_providers": tried_providers,
            },
        )

    logger.warning("reachy_intent_chat_all_failed", last_error=last_error)
    # Suggest the first healthy alternative so the toast can offer a one-click
    # switch. "Healthy" here means "we haven't already tried and failed" — a
    # cheap heuristic until the status endpoint is wired in.
    tried_ids = {t["id"] for t in tried_providers}
    suggest = next((p.id for p in AVAILABLE_PROVIDERS if p.id not in tried_ids), None)
    return IntentResponse(
        response_text=(
            "I can't reach any chat model right now. Try switching providers — "
            "use the LLM badge next to the voice button."
        ),
        intent="chat",
        took_action=False,
        detail={
            "last_error": last_error,
            "tried_providers": tried_providers,
            "suggested_provider": suggest,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spoken_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(round(seconds))} seconds"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if secs == 0:
        return f"{mins} minute" + ("s" if mins != 1 else "")
    return f"{mins} minute{'s' if mins != 1 else ''} and {secs} seconds"


def _spoken_event(title: str, start) -> Optional[str]:
    if not start:
        return None
    try:
        if isinstance(start, str):
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        else:
            dt = start
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=dt.tzinfo)
        delta = dt - now
        mins = int(delta.total_seconds() // 60)
        if -2 <= mins <= 2:
            when = "right now"
        elif 0 < mins < 60:
            when = f"in {mins} minute{'s' if mins != 1 else ''}"
        elif 60 <= mins < 180:
            hrs = mins // 60
            rem = mins % 60
            when = f"in {hrs} hour{'s' if hrs != 1 else ''}"
            if rem >= 15:
                when += f" and {rem} minutes"
        else:
            when = dt.strftime("at %I:%M %p").lstrip("0").lower()
        return f"{title} {when}"
    except Exception:
        return title


def _natural_join(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return "no events"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Push-to-talk proxy: frontend -> zero-api -> host_agent
# ---------------------------------------------------------------------------

async def _host_agent(method: str, path: str) -> dict:
    url = f"{HOST_AGENT_URL}{path}"
    # Voice /stop now has to return within ~30s or the user is staring at a
    # spinner. host_agent itself does STT+intent+TTS, so 30s is enough headroom
    # for the short-reply path while being well under the frontend's 35s abort.
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=3.0)) as client:
            resp = await client.request(method, url)
            if resp.status_code >= 400:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text[:500]
                raise HTTPException(resp.status_code, detail)
            return resp.json() if resp.content else {}
    except httpx.RequestError as e:
        logger.warning("host_agent_unreachable_from_intent", url=url, error=str(e))
        raise HTTPException(502, f"Host agent unreachable: {e}")


@router.post("/voice/start")
async def voice_start():
    """Begin a push-to-talk capture on the host agent (click to start)."""
    return await _host_agent("POST", "/voice/start")


@router.post("/voice/stop")
async def voice_stop():
    """Stop the capture, transcribe, run intent, and speak Reachy's reply."""
    return await _host_agent("POST", "/voice/stop")


@router.get("/voice/status")
async def voice_status():
    return await _host_agent("GET", "/voice/status")


@router.post("/handle", response_model=IntentResponse)
async def handle_intent(request: IntentRequest):
    """
    Classify and handle a single wake-triggered voice command.
    Called by the host_agent after the wake-word + command-capture pipeline.
    """
    text = request.text.strip()
    intent = classify_intent(text)
    logger.info("reachy_intent_received", text=text, intent=intent, source=request.source)

    response: IntentResponse
    if intent == "record_start":
        response = await _handle_record_start(text)
    elif intent == "record_stop":
        response = await _handle_record_stop(text)
    elif intent == "calendar":
        response = await _handle_calendar(text)
    elif intent == "email":
        response = await _handle_email(text)
    elif intent == "company":
        response = await _handle_company(text)
    elif intent == "robot_wake":
        response = await _handle_robot_wake(text)
    elif intent == "robot_sleep":
        response = await _handle_robot_sleep(text)
    elif intent == "focus_start":
        response = await _handle_focus_start(text)
    elif intent == "focus_stop":
        response = await _handle_focus_stop(text)
    elif intent == "ambient_on":
        response = await _handle_ambient(True)
    elif intent == "ambient_off":
        response = await _handle_ambient(False)
    else:
        response = await _handle_chat(text)

    try:
        from app.models.reachy_companion import CompanionEventCreate
        from app.services.reachy_companion_service import get_reachy_companion_service

        companion = get_reachy_companion_service()
        companion.record_event(
            CompanionEventCreate(
                type="voice_heard",
                source=request.source,
                summary=f"Voice command: {intent}",
                payload={
                    "text": text,
                    "intent": intent,
                    "took_action": response.took_action,
                },
                importance=0.65 if response.took_action else 0.45,
            )
        )
        if intent == "record_start" and response.took_action:
            companion.record_event(
                CompanionEventCreate(
                    type="meeting_started",
                    source=request.source,
                    summary="Meeting recording started by voice.",
                    payload=response.detail or {},
                    importance=0.8,
                )
            )
    except Exception as exc:
        logger.debug("reachy_companion_voice_event_skipped", error=str(exc))

    return response


@router.get("/classify")
async def classify_only(text: str):
    """Debug helper — see what intent a phrase would resolve to without acting."""
    return {"text": text, "intent": classify_intent(text)}


# ---------------------------------------------------------------------------
# Chat provider selector (vLLM vs Gemini vs Kimi)
# ---------------------------------------------------------------------------

class ProviderSetRequest(BaseModel):
    provider_id: str = Field(..., description="One of the ids from GET /providers")


@router.get("/providers")
async def list_providers_endpoint():
    """Available chat providers for the voice fallback + the active one."""
    from app.services.reachy_chat_provider import (
        AVAILABLE_PROVIDERS,
        DEFAULT_PROVIDER_ID,
        get_active_provider_id,
    )
    return {
        "active_id": get_active_provider_id(),
        "providers": [
            {
                "id": p.id,
                "label": p.label,
                "provider": p.provider,
                "model": p.model,
                "description": p.description,
            }
            for p in AVAILABLE_PROVIDERS
        ],
    }


@router.post("/providers")
async def set_provider_endpoint(request: ProviderSetRequest):
    """Switch the chat provider. Persists to workspace/settings/reachy_chat.json."""
    from app.services.reachy_chat_provider import set_active_provider_id
    try:
        provider = set_active_provider_id(request.provider_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "active_id": provider.id,
        "provider": provider.provider,
        "model": provider.model,
        "label": provider.label,
    }


# ---------------------------------------------------------------------------
# Health probe: are the classic chat providers actually reachable right now?
# ---------------------------------------------------------------------------

# Cache a single status snapshot for this many seconds so rapid UI polls don't
# hammer every provider with probe prompts.
_PROVIDERS_STATUS_CACHE_TTL = 15.0
# Per-provider hard ceiling. The probe sends a 1-token "say ok" prompt; most
# healthy cloud providers respond in 500 ms - 2 s once warm, but cold-start
# (first probe after container boot) can hit 5–7 s when 5 providers fire in
# parallel and contend for HTTP clients / DNS. 8 s gives every reasonable
# provider room to answer cold while still catching truly-down providers.
_PROVIDERS_STATUS_PROBE_TIMEOUT = 8.0
# 1-token max so probes cost ~nothing even on paid providers.
_PROVIDERS_STATUS_PROBE_TOKENS = 1
# Stale-while-revalidate window. If a fresh probe shows ALL providers down
# AND we have a cache snapshot from within this many seconds where some were
# healthy, prefer the cached snapshot — this rides over transient cold-start
# / rate-limit hiccups that would otherwise paint the entire UI red.
_PROVIDERS_STATUS_STALE_WINDOW = 60.0

_providers_status_cache: tuple[float, "ProvidersStatusResponse"] | None = None
_providers_status_lock = asyncio.Lock()


async def _probe_single_provider(provider) -> "ProviderStatus":
    """Send a 1-token probe prompt to a single provider, measuring latency."""
    import time as _time

    started = _time.monotonic()
    if provider.provider in {"vllm", "ollama"}:
        try:
            from app.infrastructure.config import get_settings

            settings = get_settings()
            candidate_urls = [
                getattr(settings, "vllm_chat_url", None),
                getattr(settings, "vllm_chat_base_url", None),
                "http://host.docker.internal:18800/v1",
            ]
            api_key = getattr(settings, "vllm_api_key", None) or "EMPTY"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            last_error = ""
            async with httpx.AsyncClient(timeout=3.0) as client:
                for raw_url in dict.fromkeys(str(u).rstrip("/") for u in candidate_urls if u):
                    try:
                        resp = await client.get(f"{raw_url}/models", headers=headers)
                        resp.raise_for_status()
                        data = resp.json()
                    except Exception as e:
                        last_error = str(e)[:160]
                        continue
                    model_ids = {
                        str(item.get("id") or item.get("model") or item.get("name"))
                        for item in (data.get("data") or data.get("models") or [])
                        if isinstance(item, dict)
                    }
                    ok = (
                        not model_ids
                        or provider.model in model_ids
                        or f"vllm/{provider.model}" in model_ids
                        or any(model_id.endswith(f"/{provider.model}") for model_id in model_ids)
                    )
                    if ok:
                        elapsed_ms = int((_time.monotonic() - started) * 1000)
                        return ProviderStatus(
                            id=provider.id,
                            label=provider.label,
                            provider=provider.provider,
                            model=provider.model,
                            ok=True,
                            latency_ms=elapsed_ms,
                            checked_at=_time.time(),
                        )
                    last_error = f"{provider.model} not in /models"
            return ProviderStatus(
                id=provider.id,
                label=provider.label,
                provider=provider.provider,
                model=provider.model,
                ok=False,
                error=last_error,
                checked_at=_time.time(),
            )
        except Exception as e:
            return ProviderStatus(
                id=provider.id,
                label=provider.label,
                provider=provider.provider,
                model=provider.model,
                ok=False,
                error=str(e)[:160],
                checked_at=_time.time(),
            )

    from app.infrastructure.unified_llm_client import get_unified_llm_client

    client = get_unified_llm_client()
    try:
        await asyncio.wait_for(
            client.chat(
                prompt="ok",
                system="Reply with one word.",
                temperature=0.0,
                max_tokens=_PROVIDERS_STATUS_PROBE_TOKENS,
                model=f"{provider.provider}/{provider.model}",
            ),
            timeout=_PROVIDERS_STATUS_PROBE_TIMEOUT,
        )
        elapsed_ms = int((_time.monotonic() - started) * 1000)
        return ProviderStatus(
            id=provider.id,
            label=provider.label,
            provider=provider.provider,
            model=provider.model,
            ok=True,
            latency_ms=elapsed_ms,
            checked_at=_time.time(),
        )
    except asyncio.TimeoutError:
        return ProviderStatus(
            id=provider.id,
            label=provider.label,
            provider=provider.provider,
            model=provider.model,
            ok=False,
            error=f"timeout after {int(_PROVIDERS_STATUS_PROBE_TIMEOUT)}s",
            checked_at=_time.time(),
        )
    except Exception as e:
        return ProviderStatus(
            id=provider.id,
            label=provider.label,
            provider=provider.provider,
            model=provider.model,
            ok=False,
            error=str(e)[:160],
            checked_at=_time.time(),
        )


@router.get("/providers/status", response_model=ProvidersStatusResponse)
async def providers_status():
    """Return per-provider reachability so the UI can paint red/green dots.

    Concurrent 1-token probes per provider. 15s cached — voice-turn health
    is cheap to re-check but hammering every provider on every poll would
    leak tokens + trigger rate limits on the free tier keys.
    """
    import time as _time

    from app.services.reachy_chat_provider import (
        AVAILABLE_PROVIDERS,
        get_active_provider_id,
    )

    global _providers_status_cache
    async with _providers_status_lock:
        now = _time.time()
        cached = _providers_status_cache
        if cached is not None and (now - cached[0]) < _PROVIDERS_STATUS_CACHE_TTL:
            return cached[1]

        active_id = get_active_provider_id()
        providers_by_id = {p.id: p for p in AVAILABLE_PROVIDERS}
        providers_to_probe = [
            p for p in AVAILABLE_PROVIDERS
            if p.id == active_id or p.provider in {"vllm", "ollama"}
        ]
        probed = await asyncio.gather(
            *[_probe_single_provider(p) for p in providers_to_probe],
            return_exceptions=False,
        )
        results_by_id = {p.id: status for p, status in zip(providers_to_probe, probed)}
        results = [
            results_by_id.get(p.id)
            or ProviderStatus(
                id=p.id,
                label=p.label,
                provider=p.provider,
                model=p.model,
                ok=False,
                error="not probed until selected",
                checked_at=now,
            )
            for p in AVAILABLE_PROVIDERS
        ]
        response = ProvidersStatusResponse(
            active_id=active_id if active_id in providers_by_id else DEFAULT_PROVIDER_ID,
            checked_at=now,
            providers=list(results),
        )

        # Stale-while-revalidate: if EVERY provider just came back down but
        # we recently had at least one healthy, prefer the cached snapshot.
        # This rides over the cold-start race where 5 concurrent first-probes
        # all exceed the per-provider deadline before warming up.
        all_down = not any(r.ok for r in response.providers)
        if all_down and cached is not None and (now - cached[0]) < _PROVIDERS_STATUS_STALE_WINDOW:
            had_healthy = any(r.ok for r in cached[1].providers)
            if had_healthy:
                logger.info(
                    "reachy_providers_status_stale_revalidate",
                    cached_age_s=round(now - cached[0], 1),
                    note="all-down probe rejected, returning last-known-good",
                )
                # Don't update cache — keep retrying on next call.
                return cached[1]

        _providers_status_cache = (now, response)
        logger.info(
            "reachy_providers_status_probed",
            active_id=response.active_id,
            results=[(r.id, r.ok, r.latency_ms) for r in response.providers],
        )
        return response
