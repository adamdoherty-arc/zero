"""Resilience tests for ContentLearningEngine defensive DB/network fallbacks (Fix-132).

Each of these methods wraps DB / network I/O in a try/except that is meant to
return a safe default (list / dict / 0) rather than propagate a transient
infra error. Prior fixes (Fix-128 LRN-X3, Fix-130 LRN-N5) widened the sibling
`process_content_outcomes` / `record_outcome` guards; this run widened the
remaining narrow `except (ValueError, KeyError, TypeError[, ImportError])`
guards to `except Exception` so a DB OperationalError / embedding TimeoutError
on these paths honors the return contract instead of raising.

These tests inject a non-narrow error (RuntimeError, standing in for
OperationalError / httpx.TimeoutError which are NOT in the old tuples) and assert
the safe default is returned. Before the widening they would raise and fail.
"""

from __future__ import annotations

import pytest

import app.services.content_learning_engine as cle


class _RaisingSessionCtx:
    """Async context manager whose entry raises — simulates a DB down blip."""

    async def __aenter__(self):
        raise RuntimeError("simulated OperationalError (db unavailable)")

    async def __aexit__(self, *_exc):
        return False


@pytest.fixture
def db_down(monkeypatch):
    monkeypatch.setattr(cle, "get_session", lambda: _RaisingSessionCtx())


def _engine() -> cle.ContentLearningEngine:
    return cle.ContentLearningEngine()


# --- get_session-backed read methods return safe defaults on a DB error ---
async def test_check_experiments_empty_on_db_error(db_down):
    assert await _engine().check_experiments() == []


async def test_get_experiments_empty_on_db_error(db_down):
    assert await _engine().get_experiments() == []


async def test_count_active_experiments_zero_on_db_error(db_down):
    assert await _engine().count_active_experiments() == 0


async def test_product_insights_safe_shape_on_db_error(db_down):
    out = await _engine().get_product_performance_insights()
    assert out["by_niche"] == []
    assert "error" in out


async def test_posting_time_analysis_safe_shape_on_db_error(db_down):
    out = await _engine().get_posting_time_analysis()
    assert out["by_hour"] == []
    assert "error" in out


# --- best-effort episodic memory store must not lose the registration result ---
async def test_register_prompt_evolution_survives_memory_store_error(monkeypatch):
    import app.services.episodic_memory_service as ems

    class _BoomMemory:
        async def store_direct(self, **_kw):
            raise RuntimeError("simulated OperationalError in episodic store")

    monkeypatch.setattr(ems, "get_episodic_memory_service", lambda: _BoomMemory())

    # ai_score >= 8.0 -> category "winning" -> triggers the store_direct path
    out = await _engine().register_prompt_evolution("car-1", "a strong prompt", 9.5)
    assert out == {"carousel_id": "car-1", "category": "winning", "score": 9.5}


# --- strategy leaderboard degrades to [] when the outcome service errors ---
async def test_strategy_leaderboard_empty_on_service_error(monkeypatch):
    import app.services.outcome_learning_service as ols

    class _BoomOutcome:
        async def get_strategy_metrics(self, **_kw):
            raise RuntimeError("simulated outcome-service failure")

    monkeypatch.setattr(ols, "get_outcome_learning_service", lambda: _BoomOutcome())

    assert await _engine().get_content_strategy_leaderboard() == []
