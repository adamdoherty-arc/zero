"""Unit tests for PromptGraderService (LLM-as-judge).

Covers the two supervise/Fix-143 findings on this previously never-swept file:
  * F4: `_parse_judge_response` must not blank a single-line fenced JSON response
        (```{...}``` with no newline) — that used to slice to "" and leave the
        run ungraded forever.
  * F3: `grade_run` must stamp `grader_model` with the model that ACTUALLY served
        the call (fallback-aware), not the pre-resolved primary.
Plus the score-clamp / flag-filter invariants the parser must hold.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.services.prompt_grader_service as pgs
from app.services.prompt_grader_service import PromptGraderService


# --------------------------------------------------------------------------- #
# F4 — _parse_judge_response
# --------------------------------------------------------------------------- #
def test_parse_single_line_fenced_json_not_blanked():
    """Regression: ```{...}``` on ONE line (no newline) must still parse."""
    svc = PromptGraderService()
    raw = '```{"score": 80, "flags": [], "summary": "ok"}```'
    parsed = svc._parse_judge_response(raw)
    assert parsed is not None, "single-line fenced JSON was blanked (F4 regression)"
    assert parsed["score"] == 80.0
    assert parsed["summary"] == "ok"


def test_parse_multi_line_fenced_json():
    svc = PromptGraderService()
    raw = '```json\n{"score": 90, "flags": ["incomplete"], "summary": "gap"}\n```'
    parsed = svc._parse_judge_response(raw)
    assert parsed is not None
    assert parsed["score"] == 90.0
    assert parsed["flags"] == ["incomplete"]


def test_parse_bare_json():
    svc = PromptGraderService()
    parsed = svc._parse_judge_response('{"score": 55, "flags": [], "summary": "mixed"}')
    assert parsed["score"] == 55.0


def test_parse_json_with_trailing_text_recovered():
    svc = PromptGraderService()
    parsed = svc._parse_judge_response('Here you go: {"score": 42, "flags": [], "summary": "weak"} thanks')
    assert parsed is not None
    assert parsed["score"] == 42.0


def test_parse_clamps_score_out_of_range():
    svc = PromptGraderService()
    assert svc._parse_judge_response('{"score": 150, "summary": "x"}')["score"] == 100.0
    assert svc._parse_judge_response('{"score": -20, "summary": "x"}')["score"] == 0.0


def test_parse_filters_unknown_flags():
    svc = PromptGraderService()
    parsed = svc._parse_judge_response(
        '{"score": 30, "flags": ["hallucination", "made_up_flag", "off_topic"], "summary": "y"}'
    )
    assert parsed["flags"] == ["hallucination", "off_topic"]


@pytest.mark.parametrize("raw", ["", "   ", "no json here", "```\n```", None])
def test_parse_garbage_returns_none(raw):
    svc = PromptGraderService()
    assert svc._parse_judge_response(raw) is None


# --------------------------------------------------------------------------- #
# F3 — grade_run stamps the ACTUAL served model (fallback-aware)
# --------------------------------------------------------------------------- #
def _fake_run():
    return SimpleNamespace(
        id=1,
        response_text="some response",
        success=True,
        task_type="content_slide",
        source="unit-test",
        system_prompt="sys",
        user_prompt="usr",
    )


@pytest.mark.asyncio
async def test_grade_run_attributes_fallback_model():
    """When the fallback chain fires, grader_model records the model that answered,
    not the pre-resolved primary."""
    svc = PromptGraderService()
    fake_client = SimpleNamespace(
        chat=AsyncMock(return_value='{"score": 88, "flags": [], "summary": "good"}')
    )
    fake_router = SimpleNamespace(resolve=lambda tt: "primary-model")

    with patch.object(pgs, "get_unified_llm_client", return_value=fake_client), \
         patch.object(pgs, "get_llm_router", return_value=fake_router), \
         patch.object(pgs, "get_last_served_model", return_value="fallback-kimi"):
        grade = await svc.grade_run(_fake_run())

    assert grade is not None
    assert grade.quality_score == 88
    assert grade.grader_model == "fallback-kimi"


@pytest.mark.asyncio
async def test_grade_run_falls_back_to_resolved_when_served_unknown():
    """If the served model is unavailable (e.g. emergency freellm tier), fall back
    to the resolved primary name rather than None."""
    svc = PromptGraderService()
    fake_client = SimpleNamespace(
        chat=AsyncMock(return_value='{"score": 70, "flags": [], "summary": "ok"}')
    )
    fake_router = SimpleNamespace(resolve=lambda tt: "primary-model")

    with patch.object(pgs, "get_unified_llm_client", return_value=fake_client), \
         patch.object(pgs, "get_llm_router", return_value=fake_router), \
         patch.object(pgs, "get_last_served_model", return_value=None):
        grade = await svc.grade_run(_fake_run())

    assert grade.grader_model == "primary-model"


@pytest.mark.asyncio
async def test_grade_run_skips_unsuccessful_or_empty():
    svc = PromptGraderService()
    empty = SimpleNamespace(response_text="", success=True, task_type="x")
    failed = SimpleNamespace(response_text="hi", success=False, task_type="x")
    assert await svc.grade_run(empty) is None
    assert await svc.grade_run(failed) is None
