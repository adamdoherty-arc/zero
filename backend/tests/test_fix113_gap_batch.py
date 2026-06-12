"""Fix-113 regression guards (act-with-approval + learn coverage batch).

AP-1: ambient vision actionable observations must reach the real approval
      queue (the old code imported a module that never existed and swallowed
      the ImportError, so every actionable frame was silently dropped).
AP-3: auto_expire_check must write canonical statuses (the action verb
      "reject" is not a status; get_stats only buckets rejected/approved/
      expired).
LN-5: response-length preference learning must skip feedback rows without a
      numeric response_length instead of averaging sentinel zeros.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_ambient_vision_propose_approval_reaches_queue(monkeypatch):
    from app.services import ambient_vision_service as avs

    queue = MagicMock()
    approval_row = MagicMock()
    approval_row.id = "ap-test123"
    queue.request = AsyncMock(return_value=approval_row)

    import app.services.approval_queue_service as aqs
    monkeypatch.setattr(aqs, "get_approval_queue", lambda: queue)

    result = await avs._propose_approval(
        "test-provider", {"caption": "a person at the door", "actionable": "answer door"}
    )

    assert result == "ap-test123"
    kwargs = queue.request.await_args.kwargs
    assert kwargs["tool_name"] == "vision_observation"
    assert kwargs["tier"] == "write_local"
    assert kwargs["requested_by"] == "ambient_vision"
    assert kwargs["arguments"]["actionable"] == "answer door"


@pytest.mark.asyncio
async def test_auto_expire_writes_canonical_status(monkeypatch):
    from app.services import approval_service as aps

    expired_reject = MagicMock()
    expired_reject.auto_action_on_expiry = "reject"
    expired_approve = MagicMock()
    expired_approve.auto_action_on_expiry = "approve"
    expired_none = MagicMock()
    expired_none.auto_action_on_expiry = None

    rows = [expired_reject, expired_approve, expired_none]

    class _FakeSession:
        async def execute(self, _stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = rows
            return result

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(aps, "get_session", lambda: _Ctx())

    count = await aps.ApprovalService().auto_expire_check()

    assert count == 3
    assert expired_reject.status == "rejected"
    assert expired_approve.status == "approved"
    assert expired_none.status == "expired"
    for row in rows:
        assert row.decision_by == "auto_expire"


@pytest.mark.asyncio
async def test_content_outcomes_dedup_at_sink(monkeypatch):
    """A record whose action_id already has a content_published brain outcome
    must be skipped (idempotency across the 3 overlapping schedulers) — and
    the dedup must NOT touch content_agent_service's feedback_processed flag."""
    from app.services import content_learning_engine as cle
    import app.services.outcome_learning_service as ols
    import app.services.episodic_memory_service as ems

    rec_done = MagicMock()
    rec_done.id = "cp-already"
    rec_done.engagement_rate = 0.05
    rec_new = MagicMock()
    rec_new.id = "cp-fresh"
    rec_new.engagement_rate = 0.02
    rec_new.content_type = "carousel"

    calls = {"n": 0}

    class _FakeSession:
        async def execute(self, _stmt):
            calls["n"] += 1
            result = MagicMock()
            if calls["n"] == 1:
                result.scalars.return_value.all.return_value = [rec_done, rec_new]
            else:
                result.all.return_value = [("cp-already",)]
            return result

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(cle, "get_session", lambda: _Ctx())

    outcome_svc = MagicMock()
    outcome_svc.record_outcome = AsyncMock(return_value="bo-test")
    memory_svc = MagicMock()
    memory_svc.store_direct = AsyncMock()
    monkeypatch.setattr(ols, "get_outcome_learning_service", lambda: outcome_svc)
    monkeypatch.setattr(ems, "get_episodic_memory_service", lambda: memory_svc)

    result = await cle.ContentLearningEngine().process_content_outcomes()

    assert result == {"processed": 1}
    assert outcome_svc.record_outcome.await_count == 1
    assert outcome_svc.record_outcome.await_args.kwargs["action_id"] == "cp-fresh"
    # No third execute (the old fix issued an UPDATE on feedback_processed)
    assert calls["n"] == 2


def test_expire_sweep_wired_into_scheduler():
    """The hourly approvals_expire_stale job must sweep BOTH queues."""
    import inspect
    from app.services.scheduler_service import SchedulerService

    src = inspect.getsource(SchedulerService._run_approvals_expire_stale)
    assert "get_approval_queue" in src
    assert "auto_expire_check" in src


@pytest.mark.asyncio
async def test_length_preference_skips_rows_without_length(monkeypatch):
    from app.services import feedback_service as fs

    def _fb(rating, context):
        row = MagicMock()
        row.rating = rating
        row.context = context
        return row

    # One positive WITH length 400; three positives whose context lacks
    # response_length. Old code averaged the missing ones as 0 -> avg_good=100
    # < avg_bad*0.7 (210) -> learned "concise" from sentinel zeros. New code
    # skips them -> avg_good=400 > avg_bad*1.3 (390) -> "detailed".
    recent = [
        _fb(1, {"response_length": 400}),
        _fb(1, {"route": "chat"}),
        _fb(1, {"route": "chat"}),
        _fb(1, {"route": "chat"}),
        _fb(-1, {"response_length": 300}),
        _fb(-1, {"response_length": 300}),
    ]

    class _FakeSession:
        async def execute(self, _stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = recent
            return result

        async def commit(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(fs, "AsyncSessionLocal", lambda: _Ctx())

    svc = fs.FeedbackService()
    captured = {}

    async def _capture(db, category, key, value, confidence=0.0, evidence_count=0):
        captured[(category, key)] = value

    monkeypatch.setattr(svc, "_upsert_preference", _capture, raising=True)

    await svc._maybe_update_preferences("response")

    assert captured.get(("response_style", "preferred_length")) == "detailed"
