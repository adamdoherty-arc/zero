"""Fix-139 — harden never-swept learn-domain services + coverage.

Coverage hunt (capture/learn/act-with-approval rotation) surfaced three real
defects in services with zero prior Fix-NNN markers and zero test coverage:

BUG-A (CRITICAL, daily_improvement_service.execute_daily_plan): the LEGION_TASK
    branch stamped item status=EXECUTED unconditionally, but _execute_legion_task
    returns {"created": False} when Legion is down / has no active sprint / raises.
    A failed task-creation was recorded as EXECUTED and verify_daily_plan (which
    only processes status==EXECUTED) then carried it as a real task. Same
    trust-boundary class as Fix-137 F1. Now: EXECUTED only when created, else
    FAILED with the reason attached.

BUG-B (HIGH, daily_improvement_service._execute_auto_fix): only .py content was
    ast.parse-validated, yet scan_extensions admits .ts/.tsx/.js/.jsx/.yaml/.yml
    and _determine_execution_strategy can route those to AUTO_FIX — a non-.py file
    was written to disk with no syntax validation. Now non-.py auto-fixes are
    refused (routed to human review) instead of blind-written.

BUG-C (MEDIUM, prompt_breeder_service.breed_all): the per-task_type loop had no
    guard, so one transient failure aborted the whole batch (the scheduler wraps
    the entire call in a single try/except). Now each task_type is guarded;
    one failure records an error entry and the siblings still breed.

Plus pure-logic coverage for the untested selection/scoring gate that decides
whether a signal is auto-written to a live source file, and for the judge-response
parser that drives Thompson-Sampling variant selection.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# BUG-A — LEGION_TASK failure must not be recorded as EXECUTED
# ---------------------------------------------------------------------------

def _legion_plan(item):
    return {"status": "planned", "selected_improvements": [item]}


async def test_fix139a_legion_task_failure_marked_failed():
    from app.services.daily_improvement_service import (
        DailyImprovementService,
        ExecutionStrategy,
        ImprovementStatus,
    )

    svc = DailyImprovementService()
    item = {
        "signal_id": "s1",
        "execution_strategy": ExecutionStrategy.LEGION_TASK.value,
        "title": "t",
    }
    svc._storage.read = AsyncMock(return_value=_legion_plan(item))
    svc._storage.write = AsyncMock()
    svc._execute_legion_task = AsyncMock(
        return_value={"created": False, "reason": "Legion unavailable"}
    )

    await svc.execute_daily_plan()

    assert item["status"] == ImprovementStatus.FAILED.value
    assert item["error"] == "Legion unavailable"


async def test_fix139a_legion_task_success_marked_executed():
    from app.services.daily_improvement_service import (
        DailyImprovementService,
        ExecutionStrategy,
        ImprovementStatus,
    )

    svc = DailyImprovementService()
    item = {
        "signal_id": "s2",
        "execution_strategy": ExecutionStrategy.LEGION_TASK.value,
        "title": "t",
    }
    svc._storage.read = AsyncMock(return_value=_legion_plan(item))
    svc._storage.write = AsyncMock()
    svc._execute_legion_task = AsyncMock(
        return_value={"created": True, "legion_task_id": 99}
    )

    await svc.execute_daily_plan()

    assert item["status"] == ImprovementStatus.EXECUTED.value
    assert "error" not in item


# ---------------------------------------------------------------------------
# BUG-B — non-.py auto-fix must be refused, .py path still validates
# ---------------------------------------------------------------------------

async def test_fix139b_non_py_autofix_refused(tmp_path, monkeypatch):
    from app.services.daily_improvement_service import DailyImprovementService

    svc = DailyImprovementService()
    f = tmp_path / "Foo.tsx"
    f.write_text("a\nb\nc\nd\ne\nf\ng\nh\n", encoding="utf-8")
    item = {"file": str(f), "line": 4, "title": "todo x", "category": "todo"}

    # Get past the LLM + extractor so we reach the syntax-validation branch.
    svc._call_ollama = AsyncMock(return_value="const x = 1;\nconst y = 2;")
    monkeypatch.setattr(
        svc, "_extract_code_from_response", lambda r: ["const x = 1;", "const y = 2;"]
    )

    result = await svc._execute_auto_fix(item)

    assert result["applied"] is False
    assert "non-Python" in result["reason"]
    # The .tsx file must be left untouched (never written).
    assert f.read_text(encoding="utf-8") == "a\nb\nc\nd\ne\nf\ng\nh\n"


async def test_fix139b_py_autofix_still_validates_syntax(tmp_path, monkeypatch):
    from app.services.daily_improvement_service import DailyImprovementService

    svc = DailyImprovementService()
    f = tmp_path / "bar.py"
    f.write_text("x = 1\ny = 2\nz = 3\na = 4\nb = 5\nc = 6\n", encoding="utf-8")
    item = {"file": str(f), "line": 3, "title": "todo", "category": "todo"}

    # LLM returns syntactically invalid Python -> .py path must reject it.
    svc._call_ollama = AsyncMock(return_value="def broken(:")
    monkeypatch.setattr(svc, "_extract_code_from_response", lambda r: ["def broken(:"])

    result = await svc._execute_auto_fix(item)

    assert result["applied"] is False
    assert "Syntax error" in result["reason"]


# ---------------------------------------------------------------------------
# BUG-C — breed_all isolates per-task_type failures
# ---------------------------------------------------------------------------

async def test_fix139c_breed_all_one_failure_does_not_starve_siblings():
    from app.services.prompt_breeder_service import PromptBreederService

    svc = PromptBreederService()

    async def fake_breed(tt):
        if tt == "bad":
            raise RuntimeError("db hiccup")
        return {"task_type": tt, "children_created": 1, "retired": 0}

    svc.breed_task_type = fake_breed

    out = await svc.breed_all(task_types=["good1", "bad", "good2"])
    by_tt = {r["task_type"]: r for r in out["results"]}

    assert len(out["results"]) == 3
    assert by_tt["good1"]["children_created"] == 1
    assert by_tt["good2"]["children_created"] == 1
    assert by_tt["bad"]["children_created"] == 0
    assert by_tt["bad"]["error"] == "db hiccup"


# ---------------------------------------------------------------------------
# Finding 4 — _determine_execution_strategy gates the auto-write path
# ---------------------------------------------------------------------------

def _svc():
    from app.services.daily_improvement_service import DailyImprovementService

    return DailyImprovementService()


def test_fix139_strategy_protected_always_human_review():
    from app.services.daily_improvement_service import ExecutionStrategy

    svc = _svc()
    # A protected path wins even at max confidence + auto-fixable type.
    sig = {
        "type": "todo",
        "confidence": 100,
        "source_file": "backend/app/config.py",
    }
    assert svc._determine_execution_strategy(sig) == ExecutionStrategy.HUMAN_REVIEW


def test_fix139_strategy_autofix_confidence_boundaries():
    from app.services.daily_improvement_service import ExecutionStrategy

    svc = _svc()
    base = {"source_file": "frontend/src/pages/Foo.tsx"}

    assert (
        svc._determine_execution_strategy({**base, "type": "todo", "confidence": 85})
        == ExecutionStrategy.AUTO_FIX
    )
    # Just below the todo/deprecated threshold -> not auto-fix (>=75 => claude).
    assert (
        svc._determine_execution_strategy({**base, "type": "todo", "confidence": 84})
        == ExecutionStrategy.CLAUDE_PROMPT
    )
    assert (
        svc._determine_execution_strategy({**base, "type": "fixme", "confidence": 90})
        == ExecutionStrategy.AUTO_FIX
    )
    # fixme needs >=90; 89 falls through to claude.
    assert (
        svc._determine_execution_strategy({**base, "type": "fixme", "confidence": 89})
        == ExecutionStrategy.CLAUDE_PROMPT
    )


def test_fix139_strategy_security_never_autofix():
    from app.services.daily_improvement_service import ExecutionStrategy

    svc = _svc()
    sig = {"type": "security", "confidence": 100, "source_file": "app/x.py"}
    assert svc._determine_execution_strategy(sig) == ExecutionStrategy.HUMAN_REVIEW


def test_fix139_strategy_hack_and_defaults():
    from app.services.daily_improvement_service import ExecutionStrategy

    svc = _svc()
    base = {"source_file": "app/x.py"}
    assert (
        svc._determine_execution_strategy({**base, "type": "hack", "confidence": 95})
        == ExecutionStrategy.LEGION_TASK
    )
    # Unknown type, low confidence -> default Legion task.
    assert (
        svc._determine_execution_strategy({**base, "type": "other", "confidence": 50})
        == ExecutionStrategy.LEGION_TASK
    )
    # Medium confidence unknown type -> claude prompt.
    assert (
        svc._determine_execution_strategy({**base, "type": "other", "confidence": 75})
        == ExecutionStrategy.CLAUDE_PROMPT
    )


def test_fix139_calculate_score_boosts():
    svc = _svc()
    neutral = {"impact_score": 50, "confidence": 70, "risk_score": 30}
    base = svc._calculate_improvement_score(neutral)
    assert base == pytest.approx(50 * 0.4 + 70 * 0.3 + 70 * 0.3)

    zero_boost = svc._calculate_improvement_score({**neutral, "project_name": "zero"})
    assert zero_boost == pytest.approx(base * 1.2)

    fixme_boost = svc._calculate_improvement_score({**neutral, "type": "fixme"})
    assert fixme_boost == pytest.approx(base * 1.15)


def test_fix139_select_diverse_caps():
    svc = _svc()
    # 4 signals in the same file -> only 2 selected (max 2/file).
    scored = [
        (9, {"source_file": "a.py", "type": "todo"}),
        (8, {"source_file": "a.py", "type": "todo"}),
        (7, {"source_file": "a.py", "type": "todo"}),
        (6, {"source_file": "a.py", "type": "todo"}),
    ]
    selected = svc._select_diverse_improvements(scored, max_count=5)
    assert len(selected) == 2

    # max_count honored across distinct files.
    scored2 = [(10 - i, {"source_file": f"f{i}.py", "type": f"c{i}"}) for i in range(10)]
    assert len(svc._select_diverse_improvements(scored2, max_count=3)) == 3

    # max 3 per category across different files.
    scored3 = [(10 - i, {"source_file": f"f{i}.py", "type": "same"}) for i in range(6)]
    assert len(svc._select_diverse_improvements(scored3, max_count=5)) == 3


# ---------------------------------------------------------------------------
# Finding 5 — prompt_grader._parse_judge_response
# ---------------------------------------------------------------------------

def _grader():
    from app.services.prompt_grader_service import PromptGraderService

    # Bypass __init__ (it wires LLM clients) — the parser is pure.
    return PromptGraderService.__new__(PromptGraderService)


def test_fix139_parse_judge_response_fenced_and_plain():
    g = _grader()
    plain = g._parse_judge_response('{"score": 88, "flags": ["incomplete"], "summary": "ok"}')
    assert plain == {"score": 88.0, "flags": ["incomplete"], "summary": "ok"}

    fenced = g._parse_judge_response('```json\n{"score": 40, "flags": [], "summary": "x"}\n```')
    assert fenced["score"] == 40.0


def test_fix139_parse_judge_response_embedded_and_clamped():
    g = _grader()
    embedded = g._parse_judge_response('Here is the grade: {"score": 150} thanks')
    assert embedded is not None
    assert embedded["score"] == 100.0  # clamped to [0, 100]

    negative = g._parse_judge_response('{"score": -20}')
    assert negative["score"] == 0.0


def test_fix139_parse_judge_response_bad_inputs():
    g = _grader()
    assert g._parse_judge_response("") is None
    assert g._parse_judge_response(None) is None
    assert g._parse_judge_response("no json here") is None
    # Non-numeric score -> None (float() raises, caught).
    assert g._parse_judge_response('{"score": "eighty"}') is None


def test_fix139_parse_judge_response_flag_allowlist():
    g = _grader()
    # Unknown flags dropped; only KNOWN_FLAGS survive; non-list -> [].
    out = g._parse_judge_response(
        '{"score": 10, "flags": ["hallucination", "made_up", 5]}'
    )
    assert out["flags"] == ["hallucination"]

    out2 = g._parse_judge_response('{"score": 10, "flags": "incomplete"}')
    assert out2["flags"] == []
