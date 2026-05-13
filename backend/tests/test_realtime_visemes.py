"""
Tests for backend viseme alignment used by the mascot mouth.
"""

from __future__ import annotations


class TestVisemeForChar:
    def test_vowels(self):
        from app.services.reachy_realtime.visemes import viseme_for_char
        assert viseme_for_char("a") == "A"
        assert viseme_for_char("e") == "E"
        assert viseme_for_char("i") == "I"
        assert viseme_for_char("o") == "O"
        assert viseme_for_char("u") == "U"

    def test_m_b_p_close_lips(self):
        from app.services.reachy_realtime.visemes import viseme_for_char
        assert viseme_for_char("m") == "M"
        assert viseme_for_char("b") == "M"
        assert viseme_for_char("p") == "M"

    def test_punctuation_rest(self):
        from app.services.reachy_realtime.visemes import viseme_for_char
        assert viseme_for_char(" ") == "REST"
        assert viseme_for_char(".") == "REST"
        assert viseme_for_char("") == "REST"


class TestVisemeShape:
    def test_known_id(self):
        from app.services.reachy_realtime.visemes import viseme_shape
        op, wd = viseme_shape("A")
        assert op > 0.5
        assert wd > 0.1

    def test_unknown_falls_back_to_rest(self):
        from app.services.reachy_realtime.visemes import viseme_shape
        op, wd = viseme_shape("XYZ")
        assert op == 0.0


class TestFrameGeneration:
    def test_empty_text_yields_nothing(self):
        from app.services.reachy_realtime.visemes import viseme_frames_for_speech
        frames = list(viseme_frames_for_speech("", 1.0))
        assert frames == []

    def test_zero_duration_yields_nothing(self):
        from app.services.reachy_realtime.visemes import viseme_frames_for_speech
        frames = list(viseme_frames_for_speech("hi", 0))
        assert frames == []

    def test_frames_count_matches_rate(self):
        from app.services.reachy_realtime.visemes import viseme_frames_for_speech
        frames = list(viseme_frames_for_speech("hello world", 2.0, frame_rate_hz=20.0))
        assert len(frames) == 40  # 2s * 20Hz

    def test_first_frame_has_offset_zero(self):
        from app.services.reachy_realtime.visemes import viseme_frames_for_speech
        frames = list(viseme_frames_for_speech("hi", 1.0))
        assert frames[0]["offset_ms"] == 0

    def test_frames_have_openness_and_width(self):
        from app.services.reachy_realtime.visemes import viseme_frames_for_speech
        frames = list(viseme_frames_for_speech("hi", 1.0))
        for f in frames:
            assert "viseme_id" in f
            assert "openness" in f
            assert "width" in f


class TestCollapseConsecutive:
    def test_collapses_runs(self):
        from app.services.reachy_realtime.visemes import collapse_consecutive
        frames = [
            {"viseme_id": "A"},
            {"viseme_id": "A"},
            {"viseme_id": "E"},
            {"viseme_id": "E"},
            {"viseme_id": "A"},
        ]
        out = list(collapse_consecutive(frames))
        ids = [f["viseme_id"] for f in out]
        assert ids == ["A", "E", "A"]

    def test_empty(self):
        from app.services.reachy_realtime.visemes import collapse_consecutive
        assert list(collapse_consecutive([])) == []
