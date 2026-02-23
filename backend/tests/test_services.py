"""
Unit tests for core Zero services.
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.services.orchestration_graph import classify_route
from app.services.email_classifier import EmailClassifier


class TestClassifyRoute:
    """Tests for the orchestration graph route classifier."""

    def test_sprint_keywords(self):
        assert classify_route("show me the active sprints") == "sprint"
        assert classify_route("what tasks are blocked?") == "sprint"

    def test_email_keywords(self):
        assert classify_route("check my inbox") == "email"
        assert classify_route("any unread emails?") == "email"

    def test_calendar_keywords(self):
        assert classify_route("what's on my schedule today?") == "calendar"
        assert classify_route("find free slots for a meeting") == "calendar"

    def test_enhancement_keywords(self):
        assert classify_route("scan code for todo comments") == "enhancement"

    def test_briefing_keywords(self):
        assert classify_route("give me the daily briefing") == "briefing"

    def test_research_keywords(self):
        assert classify_route("show research discoveries") == "research"

    def test_general_fallback(self):
        assert classify_route("hello how are you") == "general"
        assert classify_route("random text with no keywords") == "general"

    def test_highest_score_wins(self):
        # "sprint task project" has 3 sprint keywords vs 0 for others
        assert classify_route("show sprint task project details") == "sprint"


class TestEmailClassifierMapping:
    """Tests for email category mapping (without loading HF model)."""

    def test_urgent_keywords(self):
        classifier = EmailClassifier.__new__(EmailClassifier)
        result = classifier._map_to_email_category("POSITIVE", "URGENT: Deploy fix", "dev@co.com", "")
        assert result == "urgent"

    def test_newsletter_detection(self):
        classifier = EmailClassifier.__new__(EmailClassifier)
        result = classifier._map_to_email_category("POSITIVE", "Weekly Newsletter", "noreply@news.com", "")
        assert result == "newsletter"

    def test_spam_detection(self):
        classifier = EmailClassifier.__new__(EmailClassifier)
        result = classifier._map_to_email_category("POSITIVE", "You are a winner!", "spam@scam.com", "click here")
        assert result == "spam"

    def test_important_keywords(self):
        classifier = EmailClassifier.__new__(EmailClassifier)
        result = classifier._map_to_email_category("POSITIVE", "Meeting Tomorrow", "boss@co.com", "review needed")
        assert result == "important"

    def test_default_normal(self):
        classifier = EmailClassifier.__new__(EmailClassifier)
        result = classifier._map_to_email_category("POSITIVE", "Hello", "friend@co.com", "just saying hi")
        assert result == "normal"


class TestCalendarFreeSlots:
    """Tests for CalendarService._calculate_free_slots()."""

    def test_free_slots_with_events(self):
        from app.services.calendar_service import CalendarService

        svc = CalendarService.__new__(CalendarService)
        today = datetime.utcnow().date()

        # Use the internal dict format that _event_start_datetime / _event_end_datetime expect:
        # keys are "date_time" (underscore), not "dateTime" (camelCase).
        events = [
            {
                "start": {"date_time": f"{today.isoformat()}T09:00:00"},
                "end": {"date_time": f"{today.isoformat()}T09:30:00"},
                "is_all_day": False,
            },
            {
                "start": {"date_time": f"{today.isoformat()}T12:00:00"},
                "end": {"date_time": f"{today.isoformat()}T13:00:00"},
                "is_all_day": False,
            },
        ]

        slots = svc._calculate_free_slots(events)
        # Should have free time: 9:30-12:00 and 13:00-17:00
        assert len(slots) >= 2
        assert slots[0]["start"] == "09:30"
        assert slots[0]["end"] == "12:00"

    def test_free_slots_no_events(self):
        from app.services.calendar_service import CalendarService

        svc = CalendarService.__new__(CalendarService)
        slots = svc._calculate_free_slots([])
        assert len(slots) == 1
        assert slots[0]["start"] == "09:00"
        assert slots[0]["end"] == "17:00"
        assert slots[0]["duration_minutes"] == "480"

    def test_all_day_events_ignored(self):
        from app.services.calendar_service import CalendarService

        svc = CalendarService.__new__(CalendarService)
        events = [
            {"start": {"date": "2025-01-15"}, "end": {"date": "2025-01-16"}, "is_all_day": True}
        ]
        slots = svc._calculate_free_slots(events)
        assert len(slots) == 1  # Full day free
