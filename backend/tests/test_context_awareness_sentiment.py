"""Fix-139 follow-on (capture domain, hunter finding 6) — coverage for
context_awareness_service.detect_sentiment.

detect_sentiment is pure rule-based logic whose tone_guidance is injected into
every LLM system prompt via get_context_prompt_section, so a silent regression in
its word lists / thresholds / priority order would change Zero's tone on every
turn. It had zero tests. This locks in the current behavior and the priority
order (frustration>=2 -> urgency>=1 -> positive>=2 -> frustration==1 -> neutral).
"""
from __future__ import annotations


def _svc():
    from app.services.context_awareness_service import ContextAwarenessService

    # detect_sentiment is a pure method; bypass __init__ (calendar/db wiring).
    return ContextAwarenessService.__new__(ContextAwarenessService)


def test_sentiment_frustrated_via_words():
    out = _svc().detect_sentiment("this is broken and terrible")
    assert out["sentiment"] == "frustrated"
    assert "empathetic" in out["tone_guidance"].lower()
    assert out["scores"]["frustration"] == 2


def test_sentiment_frustrated_via_patterns():
    # "why won't" pattern + "!!" pattern -> frustration_score 2.
    out = _svc().detect_sentiment("why won't this work!!")
    assert out["sentiment"] == "frustrated"
    assert out["scores"]["frustration"] >= 2


def test_sentiment_urgent():
    out = _svc().detect_sentiment("I need this asap")
    assert out["sentiment"] == "urgent"
    assert "action-oriented" in out["tone_guidance"].lower()


def test_frustration_outranks_urgency():
    # frustration_score 2 is checked BEFORE urgency -> frustrated wins.
    out = _svc().detect_sentiment("this is broken and useless, need it urgent")
    assert out["scores"]["frustration"] == 2
    assert out["scores"]["urgency"] == 1
    assert out["sentiment"] == "frustrated"


def test_sentiment_positive_requires_two():
    two = _svc().detect_sentiment("thanks, this is awesome")
    assert two["sentiment"] == "positive"
    assert "warm" in two["tone_guidance"].lower()

    # A single positive word is not enough -> neutral.
    one = _svc().detect_sentiment("thanks")
    assert one["sentiment"] == "neutral"
    assert one["tone_guidance"] == ""


def test_sentiment_mildly_negative_single_frustration():
    out = _svc().detect_sentiment("this is annoying")
    assert out["scores"]["frustration"] == 1
    assert out["sentiment"] == "mildly_negative"


def test_sentiment_neutral_default():
    out = _svc().detect_sentiment("what is on my calendar tomorrow")
    assert out["sentiment"] == "neutral"
    assert out["tone_guidance"] == ""
    assert out["scores"] == {"frustration": 0, "positive": 0, "urgency": 0}
