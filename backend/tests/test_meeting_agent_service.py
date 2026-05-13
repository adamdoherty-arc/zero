"""
Tests for the Meeting Agent service. These run without Playwright installed —
the driver path stays "unavailable" but every other side-effect (persistence,
Memory Tree ingestion, summary writes) is exercised.
"""

from __future__ import annotations

import asyncio


class TestUrlValidation:
    def test_rejects_unsupported_urls(self, monkeypatch, tmp_path):
        from app.services import meeting_agent_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
        svc = mod.MeetingAgentService()

        async def run():
            try:
                await svc.join("https://example.com/not-a-meeting")
                return False
            except ValueError:
                return True

        assert asyncio.run(run()) is True

    def test_accepts_google_meet_url(self, monkeypatch, tmp_path):
        from app.services import meeting_agent_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
        svc = mod.MeetingAgentService()
        session = asyncio.run(svc.join("https://meet.google.com/abc-defg-hij"))
        assert session.url.endswith("abc-defg-hij")
        # Without Playwright, status should reflect that
        assert session.status in {"joining", "error"}

    def test_accepts_zoom_url(self, monkeypatch, tmp_path):
        from app.services import meeting_agent_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
        svc = mod.MeetingAgentService()
        session = asyncio.run(svc.join("https://zoom.us/j/123456789"))
        assert "zoom.us" in session.url


class TestPersistence:
    def test_sessions_survive_reload(self, monkeypatch, tmp_path):
        from app.services import meeting_agent_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
        svc1 = mod.MeetingAgentService()
        s = asyncio.run(svc1.join("https://meet.google.com/abc-defg-hij"))
        svc2 = mod.MeetingAgentService()
        reloaded = svc2.get(s.id)
        assert reloaded is not None
        assert reloaded["url"] == s.url


class TestIngestion:
    def test_ingest_writes_to_vault(self, monkeypatch, tmp_path):
        from app.services import meeting_agent_service as mod
        from app.services.memory_tree import service as tree_mod

        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path / "meeting")
        monkeypatch.setattr(tree_mod, "_DATA_DIR", tmp_path / "tree")
        tree_mod.get_memory_tree.cache_clear()  # type: ignore[attr-defined]
        # Force a fresh singleton bound to the patched data dir
        _ = tree_mod.get_memory_tree()

        svc = mod.MeetingAgentService()
        session = asyncio.run(svc.join("https://meet.google.com/test"))
        asyncio.run(
            svc.ingest_transcript(session.id, "Hello team, let's talk about Q4.", speaker="Alice")
        )
        # Transcript chars accumulated
        assert svc.get(session.id)["transcript_chars"] > 0
        # And a vault chunk was written
        tree = tree_mod.get_memory_tree()
        hits = asyncio.run(tree.search("Q4"))
        assert len(hits) >= 1


class TestSpeakWithoutDriver:
    def test_speak_when_unavailable_returns_unavailable(self, monkeypatch, tmp_path):
        from app.services import meeting_agent_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
        svc = mod.MeetingAgentService()
        session = asyncio.run(svc.join("https://meet.google.com/test"))
        # Without Playwright the status is "error" — speak should report
        # unavailable rather than crash.
        result = asyncio.run(svc.speak(session.id, "hello"))
        assert result["status"] in {"unavailable", "error"}


class TestLeave:
    def test_leave_writes_summary_when_transcript_exists(self, monkeypatch, tmp_path):
        from app.services import meeting_agent_service as mod
        from app.services.memory_tree import service as tree_mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path / "meeting")
        monkeypatch.setattr(tree_mod, "_DATA_DIR", tmp_path / "tree")
        tree_mod.get_memory_tree.cache_clear()  # type: ignore[attr-defined]
        _ = tree_mod.get_memory_tree()

        svc = mod.MeetingAgentService()
        session = asyncio.run(svc.join("https://meet.google.com/test"))
        asyncio.run(svc.ingest_transcript(session.id, "We agreed on the launch date."))
        result = asyncio.run(svc.leave(session.id))
        assert result["status"] == "ended"
        # A summary chunk should be searchable for "summary" or "agreed"
        tree = tree_mod.get_memory_tree()
        hits = asyncio.run(tree.search("agreed"))
        assert len(hits) >= 1

class TestWakeWordNote:
    def test_extracts_standard_take_a_note(self):
        from app.services.meeting_agent_service import _extract_take_a_note
        assert (
            _extract_take_a_note("Hey Zero, take a note: ship by Friday.")
            == "ship by Friday"
        )

    def test_extracts_with_ok_zero(self):
        from app.services.meeting_agent_service import _extract_take_a_note
        assert (
            _extract_take_a_note("Ok Zero, record this: budget approved.")
            == "budget approved"
        )

    def test_no_trigger_returns_none(self):
        from app.services.meeting_agent_service import _extract_take_a_note
        assert _extract_take_a_note("So anyway, the next step is...") is None

    def test_case_insensitive(self):
        from app.services.meeting_agent_service import _extract_take_a_note
        assert _extract_take_a_note("HEY ZERO, NOTE: launch is Q4.") == "launch is Q4"

    def test_ingest_writes_topic_when_note_present(self, monkeypatch, tmp_path):
        import asyncio
        from app.services import meeting_agent_service as mod
        from app.services.memory_tree import service as tree_mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path / "meeting")
        monkeypatch.setattr(tree_mod, "_DATA_DIR", tmp_path / "tree")
        tree_mod.get_memory_tree.cache_clear()  # type: ignore[attr-defined]
        _ = tree_mod.get_memory_tree()

        svc = mod.MeetingAgentService()
        session = asyncio.run(svc.join("https://meet.google.com/test"))
        asyncio.run(
            svc.ingest_transcript(
                session.id,
                "Hey Zero, take a note: review the Q3 numbers tomorrow.",
                speaker="Alice",
            )
        )
        tree = tree_mod.get_memory_tree()
        hits = asyncio.run(tree.search("Q3 numbers"))
        # Should appear under topics/meeting_notes_{id}
        assert any("topics" in str(h.path) for h in hits)


class TestLeaveUnknown:
    def test_leave_unknown_raises(self, monkeypatch, tmp_path):
        from app.services import meeting_agent_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
        svc = mod.MeetingAgentService()

        async def run():
            try:
                await svc.leave("nonexistent")
                return False
            except KeyError:
                return True

        assert asyncio.run(run()) is True
