"""Fix-106 (supervise run 65d49777, 2026-06-06) — act-with-approval coverage +
adversarial gap batch. Hermetic: no live DB / network / robot. Each test
discriminates the NEW behavior from the pre-fix bug so a regression re-breaks it.

Gaps covered:
  AP1  approval_service.py landmine stub reverted (module imports + class present)
  AP2  meeting_followup external-owner approval bypass (real factory + no fall-through)
  AP3/C4 attention_middleware atomic interrupt-budget (advisory lock + same-session count)
  AP4  attention_middleware DND evaluated in user-local tz, not UTC
  A1   meeting_face thresholds env-configurable + cosine clustering separates/merges
  RL4  outcome_learning get_strategy_metrics N+1 calibration query collapsed
  CR2  deep_research uses req.query (not the unbound loop var)
  RL1  local_handler barge-in / nod tasks tracked via _spawn_bg
"""
from __future__ import annotations

import importlib
import inspect
import os

import numpy as np


# ---------------------------------------------------------------- AP1 (landmine)
def test_ap1_approval_service_restored_not_stub():
    """The dependency-bot 67-byte stub is gone; the real ApprovalService +
    factory import cleanly (a stub would ImportError every approval caller)."""
    mod = importlib.import_module("app.services.approval_service")
    assert hasattr(mod, "ApprovalService"), "ApprovalService class missing — stub not reverted"
    assert hasattr(mod, "get_approval_service"), "get_approval_service factory missing"
    # The stub was a single comment line; the real module is ~180 lines.
    assert len(inspect.getsource(mod).splitlines()) > 100


# ---------------------------------------------------------------- AP2 (bypass)
def test_ap2_meeting_followup_uses_real_approval_factory():
    src = inspect.getsource(importlib.import_module("app.services.meeting_followup_service"))
    # Real factory exists and is importable...
    from app.services.approval_queue_service import get_approval_queue  # noqa: F401
    # ...and the dead wrong name is no longer referenced.
    assert "get_approval_queue_service" not in src, "still references nonexistent factory"
    assert "get_approval_queue" in src


def test_ap2_external_owner_does_not_fall_through_to_direct_create():
    """On approval-queue failure for an external owner the item is SKIPPED
    (approval_queue_failed), not silently created without approval."""
    src = inspect.getsource(importlib.import_module("app.services.meeting_followup_service"))
    assert "approval_queue_failed" in src
    assert "Fall through to direct create" not in src, "trust-boundary fall-through still present"


# ------------------------------------------------------------- AP3/C4 (budget)
def test_c4_interrupt_budget_is_atomic():
    mod = importlib.import_module("app.services.attention_middleware")
    assert hasattr(mod, "_INTERRUPT_BUDGET_LOCK_KEY")
    decide_src = inspect.getsource(mod.AttentionMiddleware.decide)
    # The check-then-mark is serialized by a xact advisory lock...
    assert "pg_advisory_xact_lock" in decide_src
    # ...and the count runs on the SAME session (not the old separate-session
    # interrupts_sent_today() that made the read+write non-atomic).
    assert "_count_interrupts_today" in decide_src
    assert "await self.interrupts_sent_today()" not in decide_src


# ----------------------------------------------------------------- AP4 (tz)
def test_ap4_now_local_is_timezone_aware_and_configurable():
    mod = importlib.import_module("app.services.attention_middleware")

    class _Stub:
        def __init__(self, tz):
            self.user_timezone = tz

    orig = mod.get_settings
    try:
        mod.get_settings = lambda: _Stub("America/New_York")  # type: ignore
        tz = mod._user_tz()
        assert tz is not None and str(tz) == "America/New_York"
        assert mod._now_local().tzinfo is not None  # tz-aware, never naive UTC

        # Invalid / empty tz falls back to UTC instead of raising.
        mod.get_settings = lambda: _Stub("Not/AZone")  # type: ignore
        assert mod._user_tz() == __import__("datetime").timezone.utc
        mod.get_settings = lambda: _Stub("")  # type: ignore
        assert mod._user_tz() == __import__("datetime").timezone.utc
    finally:
        mod.get_settings = orig  # type: ignore


# ----------------------------------------------------------------- A1 (faces)
def test_a1_face_thresholds_env_configurable():
    os.environ["ZERO_FACE_CLUSTER_COSINE_THRESHOLD"] = "0.42"
    try:
        mod = importlib.reload(importlib.import_module("app.services.meeting_face_service"))
        assert abs(mod._CLUSTER_COSINE_THRESHOLD - 0.42) < 1e-9
    finally:
        del os.environ["ZERO_FACE_CLUSTER_COSINE_THRESHOLD"]
        importlib.reload(importlib.import_module("app.services.meeting_face_service"))


def test_a1_cosine_clustering_separates_and_merges():
    """The calibration metric the cluster threshold operates on: identical/near
    faces collapse (dist below 0.35), orthogonal faces separate (dist above)."""
    mod = importlib.import_module("app.services.meeting_face_service")
    rng = np.random.default_rng(7)
    a = rng.normal(size=mod.EMBEDDING_DIM)
    same = a.copy()
    near = a + rng.normal(scale=0.01, size=mod.EMBEDDING_DIM)
    # An orthogonal-ish distinct face.
    b = rng.normal(size=mod.EMBEDDING_DIM)

    thr = mod._CLUSTER_COSINE_THRESHOLD
    assert mod._cosine_dist(a, same) < 1e-6                # identical merges
    assert mod._cosine_dist(a, near) < thr                 # near-identical merges
    assert mod._cosine_dist(a, b) > thr                    # distinct separates


# ----------------------------------------------------------------- RL4 (N+1)
def test_rl4_strategy_metrics_no_per_row_query():
    src = inspect.getsource(
        importlib.import_module("app.services.outcome_learning_service").OutcomeLearningService.get_strategy_metrics
    )
    # Calibration is precomputed in one grouped query keyed by (strategy, domain)...
    assert "cal_by_key" in src
    # ...so there is no per-row `await session.execute(cal_query)` inside the loop.
    loop_idx = src.index("for row in rows:")
    assert "session.execute(cal_query)" not in src[loop_idx:], "N+1 query still inside the row loop"


# ----------------------------------------------------------------- CR2 / RL1
def test_cr2_deep_research_uses_req_query():
    src = inspect.getsource(importlib.import_module("app.services.deep_research_service"))
    assert '"query": req.query' in src or "req.query" in src
    assert '"query": query}' not in src  # the old unbound-loop-var reference is gone


def test_rl1_barge_in_tasks_tracked():
    src = inspect.getsource(importlib.import_module("app.services.reachy_realtime.local_handler"))
    assert "asyncio.create_task(self._maybe_listening_nod())" not in src
    assert "self._spawn_bg(self._maybe_listening_nod())" in src
