"""Fix-119 coverage gap batch — discriminating hermetic tests.

Covers the DB-/pool-/LLM-backed fixes from the learn + act-with-approval +
reflect coverage run. Each test is written to FAIL against the pre-fix code and
PASS against the fix (old-vs-new discrimination), except where noted as a
regression guard. Handler-internal fixes (RFL-1 summary counter, RSP-1 single
assistant message, RSP-2 eager-task GC), RSN-2 and ACT-1/ACT-3 are verified via
deployed-import + runtime probes (they need a full realtime-handler / scheduler
harness to exercise).

Run in-container:  pytest backend/tests/test_fix119_gap_batch.py -v
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# LRN-1: decisions_only pushes the strategy/predicted filter into SQL so the
# LIMIT counts reflectable decision rows (not voice-thumbs noise).
# ---------------------------------------------------------------------------
async def test_lrn1_decisions_only_not_starved_by_feedback_rows():
    from app.services.outcome_learning_service import get_outcome_learning_service
    from app.infrastructure.database import get_session
    from app.db.models import BrainOutcomeRecordModel
    from sqlalchemy import delete

    dom = f"t119lrn1_{uuid.uuid4().hex[:8]}"
    base = datetime.now(timezone.utc)
    try:
        async with get_session() as s:
            # one genuine decision row, OLDEST
            s.add(BrainOutcomeRecordModel(
                id=f"bo-{uuid.uuid4().hex[:12]}", domain=dom, action_type="general",
                action_id=f"a-{uuid.uuid4().hex[:8]}", strategy_used="strat_a",
                predicted_score=70.0, actual_score=80.0, metrics={},
                created_at=base - timedelta(hours=2),
            ))
            # 25 pure-feedback rows (scored, but no strategy/predicted), NEWER —
            # these would fully consume a bare limit=20 and starve reflection.
            for i in range(25):
                s.add(BrainOutcomeRecordModel(
                    id=f"bo-{uuid.uuid4().hex[:12]}", domain=dom, action_type="turn",
                    action_id=f"a-{uuid.uuid4().hex[:8]}", strategy_used=None,
                    predicted_score=None, actual_score=100.0, metrics={},
                    learnings="User rated this turn thumbs_up (score 100/100).",
                    created_at=base - timedelta(minutes=i),
                ))
            await s.commit()

        svc = get_outcome_learning_service()
        # NEW path: decisions_only makes the LIMIT count the decision row.
        rows = await svc.get_recent(domain=dom, limit=20, scored_only=True, decisions_only=True)
        assert any(r.strategy_used == "strat_a" for r in rows), \
            "decisions_only must surface the genuine decision row, not be starved by 25 feedback rows"

        # Sanity: without decisions_only the decision row falls outside limit=20.
        bare = await svc.get_recent(domain=dom, limit=20, scored_only=True)
        assert not any(r.strategy_used == "strat_a" for r in bare), \
            "pre-fix behavior: limit=20 of feedback-dominated rows excludes the decision row"
    finally:
        async with get_session() as s:
            await s.execute(delete(BrainOutcomeRecordModel).where(BrainOutcomeRecordModel.domain == dom))
            await s.commit()


# ---------------------------------------------------------------------------
# LRN-2: extract_learnings de-dupes so identical thumbs boilerplate can't evict
# the distinct synthesized learning from the limited window.
# ---------------------------------------------------------------------------
async def test_lrn2_extract_learnings_dedupes_boilerplate():
    from app.services.outcome_learning_service import get_outcome_learning_service
    from app.infrastructure.database import get_session
    from app.db.models import BrainOutcomeRecordModel
    from sqlalchemy import delete

    dom = f"t119lrn2_{uuid.uuid4().hex[:8]}"
    base = datetime.now(timezone.utc)
    distinct = "Calibration drifted: predictions ran 20pts hot for strat_a this week."
    boiler = "User rated this turn thumbs_up (score 100/100)."
    try:
        async with get_session() as s:
            # distinct learning OLDEST
            s.add(BrainOutcomeRecordModel(
                id=f"bo-{uuid.uuid4().hex[:12]}", domain=dom, action_type="general",
                action_id=f"a-{uuid.uuid4().hex[:8]}", learnings=distinct, metrics={},
                actual_score=80.0, created_at=base - timedelta(hours=3),
            ))
            # 30 identical boilerplate rows, NEWER
            for i in range(30):
                s.add(BrainOutcomeRecordModel(
                    id=f"bo-{uuid.uuid4().hex[:12]}", domain=dom, action_type="turn",
                    action_id=f"a-{uuid.uuid4().hex[:8]}", learnings=boiler, metrics={},
                    actual_score=100.0, created_at=base - timedelta(minutes=i),
                ))
            await s.commit()

        svc = get_outcome_learning_service()
        learnings = await svc.extract_learnings(domain=dom, days=7, limit=3)
        assert distinct in learnings, \
            "dedup must let the distinct synthesized learning into the limit, not just 3x boilerplate"
        assert learnings.count(boiler) <= 1, "boilerplate must be de-duplicated"
    finally:
        async with get_session() as s:
            await s.execute(delete(BrainOutcomeRecordModel).where(BrainOutcomeRecordModel.domain == dom))
            await s.commit()


# ---------------------------------------------------------------------------
# ACT-2: guarded auto-expire UPDATE still correctly expires a genuinely-pending
# expired request (regression guard for the ORM-loop -> guarded-UPDATE rewrite).
# ---------------------------------------------------------------------------
async def test_act2_auto_expire_expires_pending_regression():
    from app.services.approval_service import ApprovalService
    svc = ApprovalService()
    req = await svc.create_approval_request(
        request_type="write_local", title="t119act2",
        expires_in_hours=-1, auto_action_on_expiry="reject",
    )
    rid = req["id"]
    # ACT-1 (supervise ee392aa1): _to_dict now reports the EFFECTIVE status, so a
    # row created already-past-expiry reads "expired" here (it truly is) before
    # the sweep flips the stored column. The raw DB column is still "pending" —
    # which is what auto_expire_check() below claims and rejects.
    assert req["status"] == "expired"
    n = await svc.auto_expire_check()
    assert n >= 1
    after = await svc.get_request(rid)
    # auto_action_on_expiry="reject" -> canonical "rejected"; decision_by stamped.
    assert after["status"] == "rejected", after["status"]
    assert after["decision_by"] == "auto_expire"


async def test_act2_auto_expire_does_not_touch_decided_row():
    """A row already decided (approved) before the sweep must not be clobbered.

    Fix-128 (ACT-B1) refuses to APPROVE an already-expired request, so the row is
    created with a FUTURE expiry, approved (succeeds), then aged into the past to
    simulate the real decided-then-expired race (approve commits, time passes, the
    sweep runs). The pending-guarded UPDATE must skip the non-pending row."""
    from app.services.approval_service import ApprovalService
    from app.infrastructure.database import get_session
    from app.db.models import ApprovalRequestModel
    from sqlalchemy import update as _sql_update

    svc = ApprovalService()
    req = await svc.create_approval_request(
        request_type="write_external", title="t119act2b",
        expires_in_hours=1, auto_action_on_expiry="reject",
    )
    rid = req["id"]
    decided = await svc.approve(rid, decision_by="user")
    assert decided is not None and decided["status"] == "approved"
    # Age the already-approved row into the past: the decided-then-expired race.
    async with get_session() as s:
        await s.execute(
            _sql_update(ApprovalRequestModel)
            .where(ApprovalRequestModel.id == rid)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )
        await s.commit()
    await svc.auto_expire_check()
    after = await svc.get_request(rid)
    assert after["status"] == "approved", "expiry sweep must not overwrite a human decision"
    assert after["decision_by"] == "user"


# ---------------------------------------------------------------------------
# ACT-4: reject() guards terminal/in-flight states like approve() does.
# ---------------------------------------------------------------------------
async def test_act4_reject_does_not_clobber_sent_draft():
    from app.services.email_draft_pool_service import get_email_draft_pool
    pool = get_email_draft_pool()
    d = await pool.add_draft(
        account_id="t119", thread_id=None, to="x@example.com",
        subject="s", body="b", meta={"source": "test_fix119"},
    )
    did = d.id if hasattr(d, "id") else d["id"]
    # Force the draft into a terminal 'sent' state directly in the store.
    store = pool._read()
    for r in store.get("drafts") or []:
        if r.get("id") == did:
            r["status"] = "sent"
            r["sent_message_id"] = "msg-123"
    pool._write(store)

    res = await pool.reject(did, reason="late reject")
    status = res.status if hasattr(res, "status") else res["status"]
    assert status == "sent", "reject() must not flip an already-sent draft to rejected"


# ---------------------------------------------------------------------------
# RFL-2: empty-critique break now validates so the reported final_score is the
# calibrated validation score, not the pre-validate analyze score.
# ---------------------------------------------------------------------------
async def test_rfl2_validate_runs_on_empty_critique_break():
    from app.services import reflection_service as rs

    class FakeLLM:
        def __init__(self):
            self.n = 0
        async def structured_chat(self, *, prompt, **kw):
            self.n += 1
            if self.n == 1:
                # analyze: below threshold so the threshold-validate path is skipped
                return {"overall": 50, "issues": ["x"], "scores": {}}
            if self.n == 2:
                # critique returns EMPTY -> triggers the empty-critique break
                return {"critiques": []}
            # third structured_chat call == the NEW validate on the break path
            return {"overall": 88}
        async def chat(self, *, prompt, **kw):
            return "an improved answer that is comfortably long enough"

    fake = FakeLLM()
    rs_get = rs.get_unified_llm_client
    rs.get_unified_llm_client = lambda: fake
    try:
        svc = rs.ReflectionService()
        result = await svc.reflect(content="hello", content_type="general",
                                   criteria=["clarity"], max_iterations=3)
    finally:
        rs.get_unified_llm_client = rs_get

    scores = result["quality_scores"]
    assert any(s.get("validation") for s in scores), \
        "a validation-scored entry must be appended on the empty-critique break"
    assert scores[-1]["score"] == 88, \
        "final reported score must be the calibrated validation score, not the analyze 50"
