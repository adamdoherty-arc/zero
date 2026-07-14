"""Unit tests for PromptBreederService parent-selection gate (Fix-143 F1).

The genetic breeder's docstring promises parents are "top-3 active variants by
avg_score (min 20 runs each)". The retire query enforced the min-runs floor but
the PARENT query did not — so a freshly bred child (avg_score=50.0 default) with
one lucky high grade could become a breeding parent, letting single-sample noise
drive the next generation. This locks the min-runs filter onto the parent query.

Uses a statement-capturing fake session (the codebase's no-DB test idiom) so the
SQL WHERE clause is asserted deterministically.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import app.services.prompt_breeder_service as pbs
from app.services.prompt_breeder_service import MIN_RUNS_TO_RETIRE


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _CapturingSession:
    def __init__(self, captured):
        self._captured = captured

    async def execute(self, stmt):
        self._captured.append(stmt)
        return _EmptyResult()


class _CapturingCtx:
    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return _CapturingSession(self._captured)

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_parent_query_enforces_min_runs_floor():
    captured = []
    with patch.object(pbs, "get_session", lambda: _CapturingCtx(captured)):
        result = await pbs.PromptBreederService().breed_task_type("content_slide")

    # Empty parents -> early return, but both queries were built + captured.
    assert result["reason"] == "no_parents"
    assert len(captured) >= 2

    sqls = [str(stmt) for stmt in captured]
    parent_sql = next(s for s in sqls if "DESC" in s.upper())  # parents order by avg_score DESC
    retire_sql = next(s for s in sqls if "ASC" in s.upper())   # retire order by avg_score ASC

    # The fix: parent selection now carries the same total_uses >= floor as retire.
    assert "total_uses >=" in parent_sql.lower(), (
        "parent query missing the min-runs floor (F1 regression)"
    )
    assert "total_uses >=" in retire_sql.lower()


def test_min_runs_constant_is_positive():
    # Guards against the floor being silently zeroed (which would re-open F1).
    assert MIN_RUNS_TO_RETIRE >= 1
