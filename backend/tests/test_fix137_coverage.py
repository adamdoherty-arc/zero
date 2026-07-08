"""Fix-137 — capture / learn / act-with-approval coverage + trust-boundary bugfix.

F1 (BUG): EmailDraftPool._send reported a FAILED Gmail send as status="sent".
    GmailService.send_email is `-> Optional[str]` (str id on success, None on
    failure, never raises). The old parse did getattr(msg, "id", None) for the
    non-dict branch, which returns None WITHOUT raising for both a success-str
    and a failure-None, so the parse-except never fired and the trailing line
    returned ("sent", None) unconditionally — every failed send on the approve
    trust boundary was recorded as sent and became terminal (un-retryable).
    These tests pin: None-return -> "failed" (re-sendable); str-return -> "sent"
    with the REAL message id preserved; and a truthy-but-unparseable response
    still -> "sent" (Fix-126 no-double-send intent preserved).

F2 (test-gap): turn_outcome feedback() -> _bridge_feedback_score upsert-on-0-rows
    (Fix-117 RFL3) — "the rarest, most valuable training input" — was only
    static-getsource-checked. Pin the insert branch actually fires.

F3 (test-gap): ApprovalService.get_stats() bucketing + list_all() envelope were
    existence-checked only.

F4 (test-gap): EmailDraftPool.stats() aggregation had zero tests.
"""
from __future__ import annotations

import json
import types

import pytest


# ---------------------------------------------------------------------------
# F1 — EmailDraftPool._send must not report a failed Gmail send as "sent"
# ---------------------------------------------------------------------------
async def test_f1_send_failure_marks_draft_failed_not_sent(monkeypatch, tmp_path):
    from app.services import email_draft_pool_service as dp
    import app.services.gmail_service as gs

    monkeypatch.setattr(dp, "POOL_PATH", tmp_path / "draft_pool.json")

    class _FakeGmailFail:
        # send_email's real failure contract: returns None, never raises.
        async def send_email(self, **kwargs):
            return None

    monkeypatch.setattr(gs, "get_gmail_service", lambda: _FakeGmailFail())

    pool = dp.EmailDraftPool()
    did = (await pool.add_draft(
        account_id="default", thread_id=None, to="x@example.com",
        subject="s", body="b", meta={},
    )).id

    out = await pool.approve(did)
    assert out is not None
    # The bug: a None-return (send FAILED) was recorded as "sent".
    assert out.status == "failed", f"failed Gmail send wrongly recorded as {out.status!r}"
    assert out.sent_message_id is None
    assert out.error, "a failed send must surface a non-empty error"


async def test_f1_send_success_preserves_real_message_id(monkeypatch, tmp_path):
    from app.services import email_draft_pool_service as dp
    import app.services.gmail_service as gs

    monkeypatch.setattr(dp, "POOL_PATH", tmp_path / "draft_pool.json")

    class _FakeGmailOK:
        async def send_email(self, **kwargs):
            return "gmail-msg-abc123"  # send_email returns the message id (str)

    monkeypatch.setattr(gs, "get_gmail_service", lambda: _FakeGmailOK())

    pool = dp.EmailDraftPool()
    did = (await pool.add_draft(
        account_id="default", thread_id=None, to="y@example.com",
        subject="s2", body="b2", meta={},
    )).id

    out = await pool.approve(did)
    assert out is not None
    assert out.status == "sent"
    # The old code stored the literal "sent" and dropped the real id.
    assert out.sent_message_id == "gmail-msg-abc123", (
        f"real Gmail message id lost, got {out.sent_message_id!r}"
    )
    assert out.error is None


async def test_f1_accepted_but_unparseable_response_still_sent(monkeypatch, tmp_path):
    """Fix-126 intent preserved: a truthy response Gmail ACCEPTED but whose id we
    cannot read must stay "sent" — never "failed" — so an already-sent message is
    never re-sent. Here a dict without an "id" key stands in for that case."""
    from app.services import email_draft_pool_service as dp
    import app.services.gmail_service as gs

    monkeypatch.setattr(dp, "POOL_PATH", tmp_path / "draft_pool.json")

    class _FakeGmailWeird:
        async def send_email(self, **kwargs):
            return {"threadId": "t1"}  # accepted, but no id we can read

    monkeypatch.setattr(gs, "get_gmail_service", lambda: _FakeGmailWeird())

    pool = dp.EmailDraftPool()
    did = (await pool.add_draft(
        account_id="default", thread_id=None, to="z@example.com",
        subject="s3", body="b3", meta={},
    )).id

    out = await pool.approve(did)
    assert out is not None
    assert out.status == "sent", f"accepted-but-unparseable wrongly marked {out.status!r}"
    assert out.error is None


# ---------------------------------------------------------------------------
# F2 — turn_outcome feedback() bridges a thumbs signal by INSERTING when the
#      structured outcome row is missing (Fix-117 RFL3 upsert branch)
# ---------------------------------------------------------------------------
async def test_f2_feedback_bridge_upserts_when_no_matching_row(monkeypatch, tmp_path):
    from app.services import turn_outcome_service as tos
    import app.infrastructure.database as db

    outcome_path = tmp_path / "reachy_turns.jsonl"
    outcome_path.write_text(
        json.dumps({"id": "turn-xyz", "intent": "chat", "ts": 1.0}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tos, "OUTCOME_PATH", outcome_path)

    added: list = []

    class _Result:
        rowcount = 0  # no existing row matched -> upsert insert branch fires

    class _FakeSession:
        async def execute(self, stmt):
            return _Result()

        def add(self, obj):
            added.append(obj)

        async def commit(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(db, "get_session", lambda: _Ctx())

    svc = tos.TurnOutcomeService()
    ok = await svc.feedback("turn-xyz", "thumbs_up")

    assert ok is True
    assert len(added) == 1, "bridge did not INSERT a row when 0 existing rows matched"
    row = added[0]
    assert row.action_id == "turn-xyz"
    assert row.actual_score == 100.0  # thumbs_up on the 0-100 scale (Fix-116 LRN2)
    assert row.learnings, "the thumbs signal must stamp a retrievable learning"


# ---------------------------------------------------------------------------
# F3 — ApprovalService.get_stats() bucketing + list_all() envelope
# ---------------------------------------------------------------------------
async def test_f3_get_stats_buckets_counts_and_avg(monkeypatch):
    from app.services import approval_service as aps

    class _Result:
        def __init__(self, rows=None, scalar=None):
            self._rows = rows or []
            self._scalar = scalar

        def all(self):
            return self._rows

        def scalar(self):
            return self._scalar

    class _FakeSession:
        def __init__(self):
            self._calls = 0

        async def execute(self, stmt):
            self._calls += 1
            if self._calls == 1:  # group_by status
                return _Result(rows=[
                    types.SimpleNamespace(status="pending", count=3),
                    types.SimpleNamespace(status="approved", count=2),
                    types.SimpleNamespace(status="rejected", count=1),
                ])
            return _Result(scalar=7200.0)  # avg decision seconds = 2h

        async def commit(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(aps, "get_session", lambda: _Ctx())

    st = await aps.ApprovalService().get_stats()
    assert st["total"] == 6
    assert st["pending"] == 3
    assert st["approved"] == 2
    assert st["rejected"] == 1
    assert st["expired"] == 0
    assert st["avg_decision_time_hours"] == 2.0
    assert st["by_status"] == {"pending": 3, "approved": 2, "rejected": 1}


async def test_f3_list_all_returns_items_and_total_envelope(monkeypatch):
    from app.services import approval_service as aps

    fake_row = types.SimpleNamespace(
        id="ap-1", request_type="email", title="t", description="d",
        context_data={}, initiated_by="reachy", route="write_external",
        status="pending", decision_by=None, decision_reason=None,
        decided_at=None, expires_at=None, auto_action_on_expiry=None,
        created_at=None,
    )

    class _Result:
        def __init__(self, rows=None, scalar=None):
            self._rows = rows or []
            self._scalar = scalar

        def scalars(self):
            return self

        def all(self):
            return self._rows

        def scalar(self):
            return self._scalar

    class _FakeSession:
        def __init__(self):
            self._calls = 0

        async def execute(self, stmt):
            self._calls += 1
            if self._calls == 1:  # count
                return _Result(scalar=1)
            return _Result(rows=[fake_row])  # rows

        async def commit(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(aps, "get_session", lambda: _Ctx())

    out = await aps.ApprovalService().list_all(limit=50, offset=0)
    assert out["total"] == 1
    assert isinstance(out["items"], list) and len(out["items"]) == 1
    assert out["items"][0]["id"] == "ap-1"
    assert out["items"][0]["status"] == "pending"


# ---------------------------------------------------------------------------
# F4 — EmailDraftPool.stats() aggregates by status and by account
# ---------------------------------------------------------------------------
async def test_f4_draft_pool_stats_aggregates(monkeypatch, tmp_path):
    from app.services import email_draft_pool_service as dp

    monkeypatch.setattr(dp, "POOL_PATH", tmp_path / "draft_pool.json")
    pool = dp.EmailDraftPool()

    await pool.add_draft(account_id="acct-a", thread_id=None, to="a@x.com",
                         subject="1", body="b", meta={})
    await pool.add_draft(account_id="acct-a", thread_id=None, to="b@x.com",
                         subject="2", body="b", meta={})
    d3 = await pool.add_draft(account_id="acct-b", thread_id=None, to="c@x.com",
                              subject="3", body="b", meta={})
    await pool.reject(d3.id, reason="no")

    st = await pool.stats()
    assert st["total"] == 3
    assert st["by_status"].get("pending") == 2
    assert st["by_status"].get("rejected") == 1
    assert st["by_account"].get("acct-a") == 2
    assert st["by_account"].get("acct-b") == 1
