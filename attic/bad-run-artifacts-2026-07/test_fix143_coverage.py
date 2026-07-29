"""Fix-143 — learn-domain coverage for daily_improvement_service crown methods.

The never-swept scan (coverage_priority = learn, missed=2) flagged
daily_improvement_service.py (896L, 0 test file) as the top learn target.
Fix-139 covered the scoring/strategy/legion-task branches; the PLAN, VERIFY,
METRICS, RECORD and LLM-response-parse methods still had zero coverage.

This file locks the behaviour of the six untested crown methods:
  create_daily_plan, verify_daily_plan, _update_metrics, _record_fix,
  _execute_claude_prompt, _extract_code_from_response.

It also covers one real hardening shipped with this run:

  _extract_code_from_response previously returned [''] / [' '] for a
  whitespace-only (or fences-wrapping-only-whitespace) LLM response. Because
  ast.parse('') succeeds, _execute_auto_fix's syntax gate would NOT catch it,
  so that near-empty extraction could be spliced into a live source file,
  silently blanking code. It now fails closed (returns None) so the signal is
  routed to human review instead of a blind overwrite.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# _extract_code_from_response — fence / line-number stripping + fail-closed
# ---------------------------------------------------------------------------

def _svc():
    from app.services.daily_improvement_service import DailyImprovementService
    return DailyImprovementService()


def test_extract_strips_markdown_fences():
    svc = _svc()
    out = svc._extract_code_from_response("```python\nx = 1\ny = 2\n```")
    assert out == ["x = 1", "y = 2"]


def test_extract_strips_line_number_prefixes():
    svc = _svc()
    out = svc._extract_code_from_response("12: x = 1\n13: y = 2")
    assert out == ["x = 1", "y = 2"]


def test_extract_plain_code_passthrough():
    svc = _svc()
    out = svc._extract_code_from_response("def f():\n    return 1")
    assert out == ["def f():", "    return 1"]


def test_extract_empty_returns_none():
    svc = _svc()
    assert svc._extract_code_from_response("") is None


def test_extract_whitespace_only_returns_none():
    # Fix-143 hardening: whitespace-only must fail closed, not return [' '].
    svc = _svc()
    assert svc._extract_code_from_response("   \n  \n\t") is None


def test_extract_fences_wrapping_blank_returns_none():
    # The exact auto-fix data-loss vector: a fence pair around only blank lines.
    svc = _svc()
    assert svc._extract_code_from_response("```\n   \n```") is None


def test_extract_fences_only_returns_none():
    svc = _svc()
    assert svc._extract_code_from_response("```\n```") is None


# ---------------------------------------------------------------------------
# create_daily_plan — candidate filtering + plan shape
# ---------------------------------------------------------------------------

async def test_create_daily_plan_no_candidates_writes_empty_plan():
    svc = _svc()
    # All signals fail the filter (confidence too low / no source_file / not pending).
    signals = {
        "signals": [
            {"id": "a", "status": "done", "confidence": 99, "source_file": "x.py"},
            {"id": "b", "status": "pending", "confidence": 10, "source_file": "y.py"},
            {"id": "c", "status": "pending", "confidence": 99, "source_file": ""},
        ]
    }
    svc._storage.read = AsyncMock(return_value=signals)
    svc._storage.write = AsyncMock()

    plan = await svc.create_daily_plan()

    assert plan["status"] == "empty"
    assert plan["selected_improvements"] == []
    # Empty plan is still persisted to the plan file.
    svc._storage.write.assert_awaited()
    assert svc._storage.write.await_args.args[0] == svc._plan_file


async def test_create_daily_plan_selects_and_persists_candidates():
    svc = _svc()
    signals = {
        "signals": [
            {
                "id": "s1", "status": "pending", "confidence": 88,
                "source_file": "app/services/foo.py", "type": "todo",
                "message": "clean up", "project_name": "zero",
                "line_number": 12, "impact_score": 60,
            },
            {
                "id": "s2", "status": "pending", "confidence": 92,
                "source_file": "app/services/bar.py", "type": "fixme",
                "message": "wrong branch", "project_name": "zero",
                "line_number": 40, "impact_score": 80,
            },
        ]
    }
    svc._storage.read = AsyncMock(return_value=signals)
    svc._storage.write = AsyncMock()
    svc._notify_plan = AsyncMock()

    plan = await svc.create_daily_plan()

    assert plan["status"] == "planned"
    assert len(plan["selected_improvements"]) == 2
    assert plan["total_candidates"] == 2
    ids = {i["signal_id"] for i in plan["selected_improvements"]}
    assert ids == {"s1", "s2"}
    svc._notify_plan.assert_awaited_once()


# ---------------------------------------------------------------------------
# verify_daily_plan — skip / verified / failed / pending + success_rate
# ---------------------------------------------------------------------------

async def test_verify_daily_plan_skips_when_not_executed():
    svc = _svc()
    svc._storage.read = AsyncMock(return_value={"status": "planned"})
    svc._storage.write = AsyncMock()

    result = await svc.verify_daily_plan()

    assert result["status"] == "skipped"
    # Nothing persisted when there is no executed plan.
    svc._storage.write.assert_not_awaited()


async def test_verify_daily_plan_autofix_verified_and_failed_and_rate():
    from app.services.daily_improvement_service import (
        ExecutionStrategy,
        ImprovementStatus,
    )

    svc = _svc()
    good = {
        "signal_id": "g", "status": ImprovementStatus.EXECUTED.value,
        "execution_strategy": ExecutionStrategy.AUTO_FIX.value,
    }
    bad = {
        "signal_id": "b", "status": ImprovementStatus.EXECUTED.value,
        "execution_strategy": ExecutionStrategy.AUTO_FIX.value,
    }
    pend = {
        "signal_id": "p", "status": ImprovementStatus.EXECUTED.value,
        "execution_strategy": ExecutionStrategy.CLAUDE_PROMPT.value,
    }
    plan = {"status": "executed", "selected_improvements": [good, bad, pend]}

    svc._storage.read = AsyncMock(return_value=plan)
    svc._storage.write = AsyncMock()
    svc._update_metrics = AsyncMock()
    svc._notify_verification = AsyncMock()
    # First AUTO_FIX resolves, second does not.
    svc._verify_auto_fix = AsyncMock(side_effect=[True, False])

    result = await svc.verify_daily_plan()

    assert result["status"] == "verified"
    assert result["verified"] == 1
    assert result["failed"] == 1
    assert result["pending"] == 1
    # success_rate = verified / (verified + failed) = 1/2 = 50.0
    assert result["success_rate"] == 50.0
    assert good["status"] == ImprovementStatus.VERIFIED.value
    assert bad["status"] == ImprovementStatus.FAILED.value
    svc._update_metrics.assert_awaited_once()


# ---------------------------------------------------------------------------
# _update_metrics — daily append, rolling windows, 90-day cap
# ---------------------------------------------------------------------------

async def test_update_metrics_rolling_windows_and_cap():
    svc = _svc()
    # Pre-load 95 prior days so the 90-day cap is exercised.
    prior = {"daily": [
        {"date": f"d{i}", "verified": 1, "failed": 1, "pending": 0,
         "total": 2, "success_rate": 50.0}
        for i in range(95)
    ]}
    svc._storage.read = AsyncMock(return_value=prior)
    captured = {}

    async def _capture(filename, data):
        captured["data"] = data

    svc._storage.write = AsyncMock(side_effect=_capture)

    await svc._update_metrics(
        {"verified": 4, "failed": 0, "pending": 1, "total": 5, "success_rate": 100.0}
    )

    data = captured["data"]
    # 95 prior + 1 new = 96, capped to last 90.
    assert len(data["daily"]) == 90
    # Newest entry is today's summary.
    assert data["daily"][-1]["verified"] == 4
    assert "rolling_7day" in data and "rolling_30day" in data
    assert data["rolling_7day"]["total_verified"] >= 4


# ---------------------------------------------------------------------------
# _record_fix — hash capture + 200-entry cap
# ---------------------------------------------------------------------------

async def test_record_fix_appends_hashes_and_caps_200():
    svc = _svc()
    prior = {"fixes": [{"signal_id": f"old{i}"} for i in range(200)]}
    svc._storage.read = AsyncMock(return_value=prior)
    captured = {}

    async def _capture(filename, data):
        captured["data"] = data

    svc._storage.write = AsyncMock(side_effect=_capture)

    item = {"signal_id": "new", "file": "f.py", "line": 3, "category": "todo"}
    await svc._record_fix(item, "original text", "fixed text", "/tmp/f.py.bak")

    fixes = captured["data"]["fixes"]
    assert len(fixes) == 200  # capped
    last = fixes[-1]
    assert last["signal_id"] == "new"
    assert last["backup_path"] == "/tmp/f.py.bak"
    # Hashes are recorded as 12-char md5 prefixes.
    assert len(last["original_hash"]) == 12
    assert last["original_hash"] != last["fixed_hash"]


# ---------------------------------------------------------------------------
# _execute_claude_prompt — prompt generation
# ---------------------------------------------------------------------------

async def test_execute_claude_prompt_generates_and_stamps_item():
    svc = _svc()
    item = {"file": "app/x.py", "line": 5, "title": "do the thing", "category": "todo"}

    result = await svc._execute_claude_prompt(item)

    assert result["prompt_generated"] is True
    assert "app/x.py" in result["prompt"]
    assert item["claude_prompt"] == result["prompt"]
