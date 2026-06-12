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
