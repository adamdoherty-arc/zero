"""
Context Awareness Service

Provides calendar-aware availability, sentiment detection,
and time-of-day context for adaptive responses.
"""

import re
from datetime import datetime, UTC
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class ContextAwarenessService:
    """Detects user context: availability, sentiment, time patterns."""

    # ------------------------------------------------------------------
    # Calendar awareness
    # ------------------------------------------------------------------

    async def is_user_available(self) -> Dict[str, Any]:
        """Check if user is currently in a meeting or has focus time."""
        try:
            from app.services.calendar_service import get_calendar_service
            cal = get_calendar_service()
            schedule = await cal.get_today_schedule()
            events = schedule.events if hasattr(schedule, 'events') else []

            now = datetime.now(UTC).replace(tzinfo=None)
            in_meeting = False
            current_event = None
            next_event = None

            for ev in events:
                start = ev.get("start", {})
                end = ev.get("end", {})
                # Parse datetime strings
                start_dt = self._parse_event_time(start)
                end_dt = self._parse_event_time(end)

                if start_dt and end_dt:
                    if start_dt <= now <= end_dt:
                        in_meeting = True
                        current_event = ev.get("summary", "Unknown event")
                    elif start_dt > now and next_event is None:
                        next_event = {
                            "summary": ev.get("summary", "Unknown"),
                            "starts_in_minutes": int((start_dt - now).total_seconds() / 60),
                        }

            return {
                "available": not in_meeting,
                "in_meeting": in_meeting,
                "current_event": current_event,
                "next_event": next_event,
            }
        except Exception as e:
            logger.debug(f"Calendar check failed: {e}")
            return {"available": True, "in_meeting": False, "error": str(e)}

    def _parse_event_time(self, time_obj) -> Optional[datetime]:
        if isinstance(time_obj, str):
            try:
                return datetime.fromisoformat(time_obj.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None
        if isinstance(time_obj, dict):
            dt_str = time_obj.get("dateTime", time_obj.get("date", ""))
            if dt_str:
                return self._parse_event_time(dt_str)
        return None

    # ------------------------------------------------------------------
    # Sentiment detection
    # ------------------------------------------------------------------

    def detect_sentiment(self, message: str) -> Dict[str, Any]:
        """Lightweight rule-based sentiment detection from user message."""
        message_lower = message.lower()

        # Frustration signals
        frustration_words = ["frustrated", "annoying", "broken", "stupid", "hate", "ugh",
                           "wtf", "damn", "useless", "waste", "terrible", "awful"]
        frustration_patterns = [r"!{2,}", r"\?{3,}", r"why (won't|doesn't|can't|isn't)"]

        # Positive signals
        positive_words = ["thanks", "great", "awesome", "perfect", "love", "excellent",
                         "nice", "good job", "well done", "helpful", "amazing"]

        # Urgency signals
        urgency_words = ["urgent", "asap", "immediately", "right now", "emergency",
                        "critical", "deadline", "hurry"]

        frustration_score = sum(1 for w in frustration_words if w in message_lower)
        frustration_score += sum(1 for p in frustration_patterns if re.search(p, message))

        positive_score = sum(1 for w in positive_words if w in message_lower)
        urgency_score = sum(1 for w in urgency_words if w in message_lower)

        # Determine overall sentiment
        if frustration_score >= 2:
            sentiment = "frustrated"
            tone_guidance = "Be empathetic and solution-focused. Acknowledge the frustration."
        elif urgency_score >= 1:
            sentiment = "urgent"
            tone_guidance = "Be direct and action-oriented. Skip pleasantries."
        elif positive_score >= 2:
            sentiment = "positive"
            tone_guidance = "Match the positive energy. Be warm."
        elif frustration_score == 1:
            sentiment = "mildly_negative"
            tone_guidance = "Be helpful and efficient. Don't dwell on the issue."
        else:
            sentiment = "neutral"
            tone_guidance = ""

        return {
            "sentiment": sentiment,
            "tone_guidance": tone_guidance,
            "scores": {
                "frustration": frustration_score,
                "positive": positive_score,
                "urgency": urgency_score,
            },
        }

    # ------------------------------------------------------------------
    # Time-of-day context
    # ------------------------------------------------------------------

    def get_time_context(self) -> Dict[str, Any]:
        """Get time-of-day context for adaptive responses."""
        now = datetime.now()
        hour = now.hour

        if 5 <= hour < 9:
            period = "early_morning"
            greeting = "Good morning"
            suggestion = "Here's what's on your plate today"
        elif 9 <= hour < 12:
            period = "morning"
            greeting = "Good morning"
            suggestion = "Let's focus on high-priority items"
        elif 12 <= hour < 14:
            period = "midday"
            greeting = "Good afternoon"
            suggestion = "Quick midday check-in"
        elif 14 <= hour < 17:
            period = "afternoon"
            greeting = "Good afternoon"
            suggestion = "Let's wrap up key tasks"
        elif 17 <= hour < 21:
            period = "evening"
            greeting = "Good evening"
            suggestion = "Let's review today's progress"
        else:
            period = "night"
            greeting = "Working late"
            suggestion = "Just the essentials — rest is important"

        return {
            "period": period,
            "hour": hour,
            "greeting": greeting,
            "suggestion": suggestion,
            "is_work_hours": 9 <= hour < 17,
            "day_of_week": now.strftime("%A"),
            "is_weekend": now.weekday() >= 5,
        }

    # ------------------------------------------------------------------
    # Combined context
    # ------------------------------------------------------------------

    async def get_full_context(self, message: Optional[str] = None) -> Dict[str, Any]:
        """Get complete context: time, availability, sentiment."""
        context = {
            "time": self.get_time_context(),
            "availability": await self.is_user_available(),
        }
        if message:
            context["sentiment"] = self.detect_sentiment(message)
        return context

    async def get_context_prompt_section(self, message: Optional[str] = None) -> str:
        """Generate context section for LLM system prompt."""
        ctx = await self.get_full_context(message)
        lines = ["## Current Context"]

        time_ctx = ctx["time"]
        lines.append(f"- Time: {time_ctx['greeting']} ({time_ctx['day_of_week']} {time_ctx['hour']}:00)")
        if not time_ctx["is_work_hours"]:
            lines.append("- Outside work hours — keep responses brief")
        if time_ctx["is_weekend"]:
            lines.append("- Weekend — only surface urgent items")

        avail = ctx["availability"]
        if avail.get("in_meeting"):
            lines.append(f"- User is in a meeting: {avail.get('current_event', 'Unknown')}")
            lines.append("- Keep response very brief")
        elif avail.get("next_event"):
            nxt = avail["next_event"]
            if nxt["starts_in_minutes"] <= 15:
                lines.append(f"- Meeting '{nxt['summary']}' starting in {nxt['starts_in_minutes']} min")

        if "sentiment" in ctx:
            sent = ctx["sentiment"]
            if sent["tone_guidance"]:
                lines.append(f"- {sent['tone_guidance']}")

        return "\n".join(lines) if len(lines) > 1 else ""


_context_service: Optional[ContextAwarenessService] = None

def get_context_awareness_service() -> ContextAwarenessService:
    global _context_service
    if _context_service is None:
        _context_service = ContextAwarenessService()
    return _context_service
