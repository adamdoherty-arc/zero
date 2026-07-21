"""Fix-150 coverage sweep — discriminating hermetic tests (learn + reflect + council).

Each test is written to FAIL against the pre-fix code and PASS against the fix
(old-vs-new discrimination). Covers:
  L1  content_learning engagement->score unit (percentage, *10 not *1000)
  L2  get_best_strategy() action_type now optional (domain-level lookup works)
  R1  weekly-review "Get Clear" includes the DEFAULT `backlog` status
  R2  episodic get_recent(source_type=...) keeps a low-frequency source findable
  R4  weekly-review "Get Creative" recency + not-promoted filter
  council  _score_experiment_rigor counts only DECIDED councils (orphans excluded)

R3 (reflect overall coercion) is a defensive isinstance guard verified by
deployed-import + code inspection (the full multi-round reflect loop needs the
LLM harness to exercise) — see the run record.

Run in-container:  pytest backend/tests/test_fix150_coverage.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import delete, select

from tests import conftest as _conftest

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _db():
    await _conftest._ensure_test_database(_conftest._test_postgres_url())


# ---------------------------------------------------------------------------
# L2: get_best_strategy() action_type is optional; the sole prod caller passed a
# literal "general" that no record_outcome ever writes, so the hint was dead.
# ---------------------------------------------------------------------------
async def test_l2_get_best_strategy_domain_level_ignores_missing_action_type():
    from app.services.outcome_learning_service import get_outcome_learning_service
    from app.infrastructure.database import get_session
    from app.db.models import BrainOutcomeRecordModel

    dom = f"t150l2_{uuid.uuid4().hex[:8]}"
    base = datetime.now(timezone.utc)
    try:
        async with get_session() as s:
            for i in range(6):
                s.add(BrainOutcomeRecordModel(
                    id=f"bo-{uuid.uuid4().hex[:12]}", domain=dom,
                    action_type="content_published",  # NOT "general"
                    action_id=f"a-{uuid.uuid4().hex[:8]}", strategy_used="strat_win",
                    predicted_score=70.0, actual_score=90.0, metrics={},
                    created_at=base - timedelta(hours=i),
                ))
            await s.commit()

        svc = get_outcome_learning_service()
        # NEW: domain-level lookup (action_type=None) surfaces the real best strategy.
        best = await svc.get_best_strategy(domain=dom)
        assert best == "strat_win", "domain-level get_best_strategy must find the recorded strategy"

        # The old prod call shape (literal 'general') still matches nothing — proves
        # the pre-fix hint was permanently dead.
        assert await svc.get_best_strategy(domain=dom, action_type="general") is None
    finally:
        async with get_session() as s:
            await s.execute(delete(BrainOutcomeRecordModel).where(BrainOutcomeRecordModel.domain == dom))
            await s.commit()


# ---------------------------------------------------------------------------
# R2: episodic get_recent(source_type=) filters in SQL, so a weekly reflection row
# stays findable even when high-frequency sources dominate recency.
# ---------------------------------------------------------------------------
async def test_r2_get_recent_source_type_survives_high_frequency_crowding():
    from app.services.episodic_memory_service import get_episodic_memory_service
    from app.infrastructure.database import get_session
    from app.db.models import EpisodicMemoryModel

    ns = f"t150r2_{uuid.uuid4().hex[:8]}"
    base = datetime.now(timezone.utc)
    try:
        async with get_session() as s:
            # 1 reflection row, OLDEST.
            s.add(EpisodicMemoryModel(
                id=f"em-{uuid.uuid4().hex[:12]}", namespace=ns, content="weekly reflection win",
                source_type="reflection", importance=60, created_at=base - timedelta(hours=3),
            ))
            # 30 NEWER non-reflection rows that would evict it from a bare limit=20.
            for i in range(30):
                s.add(EpisodicMemoryModel(
                    id=f"em-{uuid.uuid4().hex[:12]}", namespace=ns, content=f"noise {i}",
                    source_type="content_learning", importance=40,
                    created_at=base - timedelta(minutes=i),
                ))
            await s.commit()

        svc = get_episodic_memory_service()
        # NEW: SQL source_type filter surfaces the reflection regardless of crowding.
        got = await svc.get_recent(namespace=ns, source_type="reflection", limit=20)
        assert any(m.source_type == "reflection" for m in got), \
            "source_type filter must keep the weekly reflection findable"

        # Pre-fix behavior: bare limit=20 of newest rows drops the older reflection.
        bare = await svc.get_recent(namespace=ns, limit=20)
        assert not any(m.source_type == "reflection" for m in bare), \
            "bare limit=20 is crowded out by the 30 newer non-reflection rows"
    finally:
        async with get_session() as s:
            await s.execute(delete(EpisodicMemoryModel).where(EpisodicMemoryModel.namespace == ns))
            await s.commit()


# ---------------------------------------------------------------------------
# R1: weekly-review "Get Clear" stale sweep must include the DEFAULT `backlog`
# status (and all non-terminal statuses), not just todo/in_progress/blocked.
# ---------------------------------------------------------------------------
async def test_r1_weekly_review_stale_includes_backlog_default():
    from app.services.weekly_review_service import WeeklyReviewService
    from app.infrastructure.database import get_session
    from app.db.models import TaskModel

    tag = uuid.uuid4().hex[:8]
    backlog_id = f"tk-backlog-{tag}"
    done_id = f"tk-done-{tag}"
    very_old = datetime.now(timezone.utc) - timedelta(days=500)
    try:
        async with get_session() as s:
            s.add(TaskModel(
                id=backlog_id, title=f"STALE-BACKLOG-{tag}", status="backlog",
                category="general", priority=3, source="test", created_at=very_old,
            ))
            # A terminal task, even older, must NOT surface.
            s.add(TaskModel(
                id=done_id, title=f"DONE-{tag}", status="done",
                category="general", priority=3, source="test",
                created_at=very_old - timedelta(days=1),
            ))
            await s.commit()

        svc = WeeklyReviewService()
        rendered = await svc._render("2026-Wtest", "2026-07-21")
        assert f"STALE-BACKLOG-{tag}" in rendered, \
            "a >7d-old backlog task (the default status) must appear in Get Clear"
        assert f"DONE-{tag}" not in rendered, "terminal (done) tasks must be excluded"
    finally:
        async with get_session() as s:
            await s.execute(delete(TaskModel).where(TaskModel.id.in_((backlog_id, done_id))))
            await s.commit()


# ---------------------------------------------------------------------------
# R4: weekly-review "Get Creative" must filter to RECENT, not-yet-actioned findings
# instead of rendering the same all-time top-5 forever.
# ---------------------------------------------------------------------------
async def test_r4_weekly_review_get_creative_recency_and_not_promoted():
    from app.services.weekly_review_service import WeeklyReviewService
    from app.infrastructure.database import get_session
    from app.db.models import ResearchFindingModel

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    recent_id = f"rf-recent-{tag}"
    old_id = f"rf-old-{tag}"
    linked_id = f"rf-linked-{tag}"

    def _finding(fid, title, discovered, linked_task):
        return ResearchFindingModel(
            id=fid, title=title, url=f"https://x/{fid}", snippet="s",
            category="general", status="new", relevance_score=50.0,
            novelty_score=99.0, actionability_score=50.0, composite_score=50.0,
            discovered_at=discovered, linked_task_id=linked_task,
        )
    try:
        async with get_session() as s:
            s.add(_finding(recent_id, f"RECENT-{tag}", now - timedelta(days=2), None))
            s.add(_finding(old_id, f"OLD-{tag}", now - timedelta(days=90), None))
            s.add(_finding(linked_id, f"LINKED-{tag}", now - timedelta(days=1), "some-task-id"))
            await s.commit()

        svc = WeeklyReviewService()
        rendered = await svc._render("2026-Wtest", "2026-07-21")
        assert f"RECENT-{tag}" in rendered, "recent un-actioned high-novelty finding must surface"
        assert f"OLD-{tag}" not in rendered, "stale (90d) finding must be filtered by recency"
        assert f"LINKED-{tag}" not in rendered, "already-actioned (linked_task_id) finding must be filtered"
    finally:
        async with get_session() as s:
            await s.execute(delete(ResearchFindingModel).where(ResearchFindingModel.id.in_((recent_id, old_id, linked_id))))
            await s.commit()


# ---------------------------------------------------------------------------
# L1: content_performance.engagement_rate is a weighted PERCENTAGE; the score map
# must be *10 (10% -> 100), not *1000 (which scored any >=0.1% as a perfect 100).
# ---------------------------------------------------------------------------
async def test_l1_engagement_percentage_score_mapping():
    from app.services.content_learning_engine import get_content_learning_engine
    from app.infrastructure.database import get_session
    from app.db.models import ContentPerformanceModel, BrainOutcomeRecordModel

    tag = uuid.uuid4().hex[:8]
    rec_id = f"cp-{tag}"
    try:
        async with get_session() as s:
            s.add(ContentPerformanceModel(
                id=rec_id, topic_id=f"topic-{tag}", platform="tiktok",
                content_type="video", views=2000, likes=50, comments=5, shares=2,
                saves=0, engagement_rate=5.0,  # 5.0 == 5% weighted engagement
                performance_score=0.0, feedback_processed=False,
                synced_at=datetime.now(timezone.utc),
            ))
            await s.commit()

        engine = get_content_learning_engine()
        await engine.process_content_outcomes()

        async with get_session() as s:
            row = (await s.execute(
                select(BrainOutcomeRecordModel).where(BrainOutcomeRecordModel.action_id == rec_id)
            )).scalars().first()
        assert row is not None, "process_content_outcomes must record an outcome for the synced row"
        # 5% * 10 == 50.0 (pre-fix: 5.0 * 1000 == 5000 -> capped 100)
        assert abs(float(row.actual_score) - 50.0) < 0.001, \
            f"engagement 5% must map to score 50, got {row.actual_score}"
    finally:
        async with get_session() as s:
            await s.execute(delete(BrainOutcomeRecordModel).where(BrainOutcomeRecordModel.action_id == rec_id))
            await s.execute(delete(ContentPerformanceModel).where(ContentPerformanceModel.id == rec_id))
            await s.commit()


# ---------------------------------------------------------------------------
# Council: experiment-rigor must count only DECIDED councils — abandoned/orphan
# proposals (decision IS NULL) must not inflate the score.
# ---------------------------------------------------------------------------
async def test_council_rigor_counts_only_decided():
    from app.services.employee_benchmark_service import EmployeeBenchmarkService
    from app.infrastructure.database import get_session
    from app.db.models import CouncilDecisionModel

    tag = uuid.uuid4().hex[:8]
    ids = []
    svc = EmployeeBenchmarkService()
    try:
        baseline = (await svc._score_experiment_rigor())[1]["council_decisions"]

        async with get_session() as s:
            for i in range(2):  # genuine verdicts
                cid = f"council-dec-{tag}-{i}"
                ids.append(cid)
                s.add(CouncilDecisionModel(id=cid, topic=f"decided {i}", proposer_role="ceo",
                                           decision="reject", decided_at=datetime.now(timezone.utc)))
            for i in range(3):  # orphans (decision NULL) — must not count
                cid = f"council-orph-{tag}-{i}"
                ids.append(cid)
                s.add(CouncilDecisionModel(id=cid, topic=f"orphan {i}", proposer_role="ceo"))
            # a reaped orphan (terminal 'expired') — also must not count as rigor
            exp_id = f"council-exp-{tag}"
            ids.append(exp_id)
            s.add(CouncilDecisionModel(id=exp_id, topic="expired one", proposer_role="ceo",
                                       decision="expired", decided_at=datetime.now(timezone.utc)))
            await s.commit()

        after = (await svc._score_experiment_rigor())[1]["council_decisions"]
        assert after - baseline == 2, \
            f"only the 2 GENUINE verdicts must count, not the 3 orphans + 1 expired (delta={after - baseline})"
    finally:
        async with get_session() as s:
            await s.execute(delete(CouncilDecisionModel).where(CouncilDecisionModel.id.in_(ids)))
            await s.commit()
