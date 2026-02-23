"""
LangChain tool functions for Gmail and Calendar API integration.
Sprint 53 Task 113 + Sprint 59 fix: Build LangChain tools for Gmail and Calendar.

These tools wrap the existing GmailService and CalendarService to expose
email/calendar operations as LangGraph-compatible tool nodes. Called via
.ainvoke() from orchestration_graph.py's email_node and calendar_node.
"""

from typing import Optional
from datetime import datetime, timedelta

from langchain_core.tools import tool
import structlog

logger = structlog.get_logger()


def _get_gmail_service():
    """Lazy import to avoid circular imports."""
    from app.services.gmail_service import get_gmail_service
    return get_gmail_service()


def _get_calendar_service():
    """Lazy import to avoid circular imports."""
    from app.services.calendar_service import get_calendar_service
    return get_calendar_service()


@tool
async def fetch_emails(limit: int = 10) -> str:
    """Fetch recent emails from Gmail inbox.

    Args:
        limit: Maximum number of emails to return (default 10)

    Returns:
        Formatted list of emails with subject, sender, date
    """
    service = _get_gmail_service()
    if not await service.is_connected():
        return "Gmail is not connected. Please connect via /api/email/auth."

    try:
        emails = await service.list_emails(limit=limit)
        if not emails:
            return "No emails found."

        lines = [f"**{len(emails)} Recent Emails:**\n"]
        for e in emails:
            sender = e.from_address.name or e.from_address.email if e.from_address else "Unknown"
            unread = " [UNREAD]" if e.status.value == "unread" else ""
            starred = " *" if e.is_starred else ""
            date_str = e.received_at.strftime("%b %d %H:%M") if e.received_at else ""
            lines.append(
                f"- {e.subject or '(no subject)'} - from {sender} ({date_str}){unread}{starred}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error("fetch_emails_failed", error=str(e))
        return f"Error fetching emails: {e}"


@tool
async def get_email_digest() -> str:
    """Generate a digest of recent emails with urgency classification.

    Returns:
        Formatted email digest with categories and highlights
    """
    service = _get_gmail_service()
    if not await service.is_connected():
        return "Gmail is not connected. Please connect via /api/email/auth."

    try:
        digest = await service.generate_digest()
        if not digest:
            return "No email digest available."

        lines = [f"**Email Digest** ({digest.total_emails} total, {digest.unread_emails} unread)\n"]

        if digest.by_category:
            lines.append("**By Category:**")
            for cat, count in digest.by_category.items():
                lines.append(f"  - {cat}: {count}")

        if digest.urgent_emails:
            lines.append(f"\n**Urgent:** {len(digest.urgent_emails)}")
            for e in digest.urgent_emails[:5]:
                lines.append(f"  - {e.subject} (from {e.from_address.email if e.from_address else 'Unknown'})")

        if digest.highlights:
            lines.append("\n**Highlights:**")
            for h in digest.highlights[:5]:
                lines.append(f"  - {h}")

        return "\n".join(lines)
    except Exception as e:
        logger.error("get_email_digest_failed", error=str(e))
        return f"Error generating digest: {e}"


@tool
async def get_calendar_events(days_ahead: int = 7) -> str:
    """Get upcoming calendar events.

    Args:
        days_ahead: Number of days ahead to look (default 7)

    Returns:
        Formatted list of upcoming events with time, title, location
    """
    service = _get_calendar_service()
    sync_status = await service.get_sync_status()

    if not sync_status.connected:
        return "Calendar is not connected. Please connect via /api/calendar/auth."

    try:
        now = datetime.utcnow()
        events = await service.list_events(
            start_date=now,
            end_date=now + timedelta(days=days_ahead),
            limit=20,
        )

        if not events:
            return f"No events in the next {days_ahead} days."

        lines = [f"**{len(events)} Events (next {days_ahead} days):**\n"]
        for evt in events:
            start_str = ""
            if evt.start:
                if evt.start.dateTime:
                    try:
                        dt = datetime.fromisoformat(
                            evt.start.dateTime.replace("Z", "+00:00")
                        )
                        start_str = dt.strftime("%b %d %H:%M")
                    except Exception:
                        start_str = str(evt.start.dateTime)
                elif evt.start.date:
                    start_str = str(evt.start.date)

            location = f" @ {evt.location}" if evt.location else ""
            attendees = " [with others]" if evt.has_attendees else ""
            all_day = " (all day)" if evt.is_all_day else ""

            lines.append(
                f"- {evt.summary} ({start_str}{all_day}){location}{attendees}"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error("get_calendar_events_failed", error=str(e))
        return f"Error fetching calendar events: {e}"


@tool
async def get_today_schedule() -> str:
    """Get today's full schedule with conflict detection and free slots.

    Returns:
        Formatted today's schedule with events, conflicts, and available time
    """
    service = _get_calendar_service()
    sync_status = await service.get_sync_status()

    if not sync_status.connected:
        return "Calendar is not connected. Please connect via /api/calendar/auth."

    try:
        schedule = await service.get_today_schedule()
        if not schedule:
            return "No events scheduled for today."

        lines = [f"**Today's Schedule** ({schedule.date})\n"]
        lines.append(f"Total events: {schedule.total_events}")

        if schedule.events:
            lines.append("\n**Events:**")
            for evt in schedule.events:
                start_str = ""
                if evt.start and evt.start.dateTime:
                    try:
                        dt = datetime.fromisoformat(
                            evt.start.dateTime.replace("Z", "+00:00")
                        )
                        start_str = dt.strftime("%H:%M")
                    except Exception:
                        start_str = str(evt.start.dateTime)
                all_day = " (all day)" if evt.is_all_day else ""
                lines.append(f"  - {start_str} {evt.summary}{all_day}")

        if schedule.has_conflicts:
            lines.append("\n**Scheduling conflicts detected!**")

        if schedule.free_slots:
            lines.append("\n**Free Slots:**")
            for slot in schedule.free_slots:
                lines.append(f"  - {slot}")

        return "\n".join(lines)
    except Exception as e:
        logger.error("get_today_schedule_failed", error=str(e))
        return f"Error getting today's schedule: {e}"


@tool
async def find_free_slots(duration_minutes: int = 30) -> str:
    """Find available time slots in today's calendar.

    Args:
        duration_minutes: Minimum slot duration in minutes (default 30)

    Returns:
        List of available time slots meeting the minimum duration
    """
    service = _get_calendar_service()
    sync_status = await service.get_sync_status()

    if not sync_status.connected:
        return "Calendar is not connected. Please connect via /api/calendar/auth."

    try:
        schedule = await service.get_today_schedule()
        if not schedule:
            return "Calendar not connected or no data available."

        if not schedule.free_slots:
            return "No free slots found today."

        # Filter slots by minimum duration
        matching = []
        for slot in schedule.free_slots:
            if isinstance(slot, str) and " - " in slot:
                try:
                    parts = slot.split(" - ")
                    start_time = datetime.strptime(parts[0].strip(), "%H:%M")
                    end_time = datetime.strptime(parts[1].strip(), "%H:%M")
                    slot_minutes = (end_time - start_time).total_seconds() / 60
                    if slot_minutes >= duration_minutes:
                        matching.append(f"{slot} ({int(slot_minutes)} min)")
                except Exception:
                    matching.append(str(slot))
            else:
                matching.append(str(slot))

        if not matching:
            return f"No free slots of {duration_minutes}+ minutes found today."

        lines = [f"**{len(matching)} Free Slots ({duration_minutes}+ min):**\n"]
        for slot in matching:
            lines.append(f"  - {slot}")

        return "\n".join(lines)
    except Exception as e:
        logger.error("find_free_slots_failed", error=str(e))
        return f"Error finding free slots: {e}"
