"""Coverage for Phase 6 DB-backed learning-loop services:

  bandit_service.select_arm           — Thompson sample + propensity logging
  drift_detector.auto_rollback        — flips active → rolled_back, lkg → active
  golden_set_service.mark_as_golden   — idempotent on carousel_id
  golden_set_service.kappa_per_judge  — empty-golden-set short-circuit
  exemplar_memory.render_for_designer — handled in test_v2_services already
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# bandit_service.select_arm
# ---------------------------------------------------------------------------

async def test_bandit_select_arm_records_log_row(stub_db, monkeypatch):
    from app.services.carousel_v2 import bandit_service

    # Force epsilon=0 so the greedy branch is taken deterministically.
    monkeypatch.setattr(bandit_service, "EPSILON", 0.0)

    # No prior logs → uniform Beta(1,1) → Thompson picks one of three arms.
    arm, propensity, log_id = await bandit_service.select_arm(
        decision_point="hook_style",
        arms=["curiosity_gap", "contrarian", "listicle"],
        context_features={"niche": "the_boys"},
    )
    assert arm in {"curiosity_gap", "contrarian", "listicle"}
    assert 0.0 < propensity <= 1.0
    assert log_id

    # The stub session records what the service tries to insert.
    assert len(stub_db.added) == 1
    log = stub_db.added[0]
    assert log.decision_point == "hook_style"
    assert log.arm_chosen == arm
    assert log.context_features == {"niche": "the_boys"}
    assert list(log.arms_offered) == ["curiosity_gap", "contrarian", "listicle"]


async def test_bandit_select_arm_raises_on_empty_arms():
    from app.services.carousel_v2 import bandit_service

    with pytest.raises(ValueError):
        await bandit_service.select_arm(decision_point="hook_style", arms=[])


async def test_bandit_select_arm_explores_with_high_epsilon(stub_db, monkeypatch):
    """ε=1.0 forces uniform random — propensity should be ε/N for the
    exploration branch.
    """
    from app.services.carousel_v2 import bandit_service

    monkeypatch.setattr(bandit_service, "EPSILON", 1.0)

    arms = ["a", "b", "c", "d"]
    arm, propensity, _ = await bandit_service.select_arm(
        decision_point="topic_angle", arms=arms,
    )
    assert arm in arms
    # Exploration branch: propensity = ε/N = 1/4 = 0.25
    assert propensity == pytest.approx(0.25, abs=1e-6)


# ---------------------------------------------------------------------------
# drift_detector.auto_rollback
# ---------------------------------------------------------------------------

async def test_auto_rollback_returns_false_when_no_lkg(monkeypatch):
    from app.services.carousel_v2 import drift_detector

    # Stub a session that returns no rows for both queries.
    class _Result:
        def scalar_one_or_none(self):
            return None

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result()
        async def flush(self):
            return None
        def add(self, _):
            return None

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _gs():
        yield _Session()

    # Services import get_session at module level — patch the module's binding,
    # not the source module.
    monkeypatch.setattr(drift_detector, "get_session", _gs)
    assert await drift_detector.auto_rollback("designer.fact_slide") is False


async def test_auto_rollback_swaps_active_and_lkg(monkeypatch):
    from app.services.carousel_v2 import drift_detector

    class _Row:
        def __init__(self, id_, status):
            self.id = id_
            self.status = status
            self.activated_at = None
            self.retired_at = None

    active = _Row("p_active", "active")
    lkg = _Row("p_lkg", "last_known_good")
    fed = [active, lkg]
    flushed: list[bool] = []

    class _Result:
        def __init__(self, value): self._v = value
        def scalar_one_or_none(self): return self._v

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result(fed.pop(0) if fed else None)
        async def flush(self):
            flushed.append(True)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _gs():
        yield _Session()

    monkeypatch.setattr(drift_detector, "get_session", _gs)

    flipped = await drift_detector.auto_rollback("designer.fact_slide")
    assert flipped is True
    assert active.status == "rolled_back"
    assert lkg.status == "active"
    assert active.retired_at is not None
    assert lkg.activated_at is not None
    assert flushed


# ---------------------------------------------------------------------------
# golden_set_service.mark_as_golden + kappa
# ---------------------------------------------------------------------------

async def test_mark_as_golden_inserts_new_row(stub_db, monkeypatch):
    from app.services.carousel_v2 import golden_set_service

    new_id = await golden_set_service.mark_as_golden(
        carousel_id="c-test-1",
        human_score_per_axis={
            "hook_strength": 9.0, "fact_accuracy": 9.5, "narrative_arc": 8.0,
            "image_relevance": 8.5, "design_polish": 9.0, "voice_consistency": 8.5, "novelty": 7.0,
        },
        human_rater="hadam",
        franchise="the_boys",
        adversarial_category="actor_swap",
    )
    assert new_id
    row = stub_db.added[0]
    assert row.carousel_id == "c-test-1"
    assert row.human_rater == "hadam"
    assert row.frozen is True
    # Composite uses RUBRIC_WEIGHTS — voice + novelty weight 0, only 5 axes count.
    assert 7.0 < row.human_composite <= 10.0


async def test_mark_as_golden_updates_existing_row(monkeypatch):
    from app.services.carousel_v2 import golden_set_service
    from app.db.models import GoldenSetModel

    existing = GoldenSetModel(
        id="g-existing",
        carousel_id="c-test-2",
        frozen=True,
        human_score_per_axis={"hook_strength": 6.0},
        human_composite=2.0,
        human_rater="old_rater",
    )

    class _Result:
        def __init__(self, v): self._v = v
        def scalar_one_or_none(self): return self._v

    flushed: list[bool] = []

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result(existing)
        async def flush(self):
            flushed.append(True)
        def add(self, _):
            raise AssertionError("must not insert when row already exists")

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _gs():
        yield _Session()

    monkeypatch.setattr(golden_set_service, "get_session", _gs)

    returned_id = await golden_set_service.mark_as_golden(
        carousel_id="c-test-2",
        human_score_per_axis={"hook_strength": 9.0, "fact_accuracy": 9.0},
        human_rater="new_rater",
    )
    assert returned_id == existing.id
    assert existing.human_rater == "new_rater"
    assert existing.human_score_per_axis == {"hook_strength": 9.0, "fact_accuracy": 9.0}
    assert flushed


async def test_kappa_per_judge_returns_empty_when_golden_set_empty(monkeypatch):
    from app.services.carousel_v2 import golden_set_service

    class _Result:
        def scalars(self):
            class _S:
                def all(self_): return []
            return _S()

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _gs():
        yield _Session()

    monkeypatch.setattr(golden_set_service, "get_session", _gs)

    out = await golden_set_service.kappa_per_judge("hook_strength")
    assert out == {}


# ---------------------------------------------------------------------------
# exemplar_memory.cohort_quartiles
# ---------------------------------------------------------------------------

async def test_cohort_quartiles_returns_default_when_no_data(monkeypatch):
    from app.services.carousel_v2 import exemplar_memory

    class _Result:
        def all(self): return []

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _gs():
        yield _Session()

    monkeypatch.setattr(exemplar_memory, "get_session", _gs)
    p25, p75 = await exemplar_memory.cohort_quartiles("the_boys")
    assert p25 == 0.0
    assert p75 == 1.0


async def test_cohort_quartiles_computes_p25_p75(monkeypatch):
    from app.services.carousel_v2 import exemplar_memory

    class _Result:
        def all(self):
            # 12 values ranging 0.1..0.99 → p25 ≈ 0.3, p75 ≈ 0.8
            return [(v,) for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.75, 0.8, 0.9, 0.99]]

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _gs():
        yield _Session()

    monkeypatch.setattr(exemplar_memory, "get_session", _gs)
    p25, p75 = await exemplar_memory.cohort_quartiles(None)
    assert 0.2 <= p25 <= 0.4
    assert 0.7 <= p75 <= 0.9
