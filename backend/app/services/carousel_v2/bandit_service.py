"""Contextual bandit for production decisions (carosel.txt §5).

Implements Thompson-sampling Beta-Binomial bandits across the six decision
points. Vowpal Wabbit ``--cb_explore_adf`` is the production target; this
in-process implementation is a stand-in that reads/writes ``bandit_logs``
so we collect the right data shape from day one. Phase 6 swap-in: replace
``select_arm`` internals with VW without changing the public API.

Decision points (each with own arm space)::

    topic_angle, hook_style, slide_count, design_template,
    image_source_mix, posting_slot

Always keeps a 5-10% epsilon-floor so a winner doesn't starve out new arms.
"""

from __future__ import annotations

import math
import os
import random
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy import select

from app.db.models import BanditLogModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


EPSILON = float(os.getenv("ZERO_BANDIT_EPSILON", "0.1"))
DEFAULT_PRIOR_ALPHA = 1.0
DEFAULT_PRIOR_BETA = 1.0
ARM_REINTRO_DAYS = 30


async def _arm_stats(decision_point: str, arms: Iterable[str], window_days: int = 60) -> dict[str, tuple[float, float]]:
    """Returns (alpha, beta) priors per arm — α = wins, β = losses computed
    from rewarded ``bandit_logs`` rows in the recent window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    out: dict[str, tuple[float, float]] = {a: (DEFAULT_PRIOR_ALPHA, DEFAULT_PRIOR_BETA) for a in arms}
    async with get_session() as session:
        rows = (await session.execute(
            select(BanditLogModel).where(
                BanditLogModel.decision_point == decision_point,
                BanditLogModel.decided_at >= cutoff,
                BanditLogModel.reward.isnot(None),
            )
        )).scalars().all()
    for row in rows:
        a, b = out.get(row.arm_chosen, (DEFAULT_PRIOR_ALPHA, DEFAULT_PRIOR_BETA))
        # Treat reward as bounded [0,1]; clamp anything outside.
        r = max(0.0, min(1.0, float(row.reward or 0.0)))
        out[row.arm_chosen] = (a + r, b + (1.0 - r))
    return out


def _thompson_sample(alpha: float, beta: float) -> float:
    """Sample from Beta(α, β). Uses random.betavariate which is fine at
    bandit cadences; switch to numpy for batch sampling when wired into VW.
    """
    return random.betavariate(max(0.5, alpha), max(0.5, beta))


async def select_arm(
    *,
    decision_point: str,
    arms: list[str],
    context_features: dict | None = None,
    generation_id: Optional[str] = None,
    carousel_id: Optional[str] = None,
    policy_id: str = "thompson_v1",
) -> tuple[str, float, str]:
    """Return ``(arm, propensity, log_id)`` for a single decision.

    ``propensity`` is the model-estimated probability of choosing this arm —
    used by the doubly-robust counterfactual estimator (VW ``--cb_type dr``)
    to debias offline policy evaluation.
    """
    if not arms:
        raise ValueError("bandit_select_arm requires at least one arm")

    epsilon = EPSILON
    if random.random() < epsilon:
        chosen = random.choice(arms)
        propensity = epsilon / len(arms) + (1.0 - epsilon) * 0.0
    else:
        stats = await _arm_stats(decision_point, arms)
        samples = {a: _thompson_sample(*stats[a]) for a in arms}
        chosen = max(samples, key=lambda a: samples[a])
        # Estimated probability ≈ 1 - epsilon for the winner under Thompson;
        # for offline IPW correction we record the empirical equivalent.
        propensity = (1.0 - epsilon) + (epsilon / len(arms))

    log_id = uuid.uuid4().hex
    async with get_session() as session:
        session.add(
            BanditLogModel(
                id=log_id,
                generation_id=generation_id,
                carousel_id=carousel_id,
                decision_point=decision_point,
                context_features=context_features or {},
                arm_chosen=chosen,
                arms_offered=list(arms),
                propensity=propensity,
                policy_id=policy_id,
                decided_at=datetime.now(timezone.utc),
            )
        )
        await session.flush()
    logger.debug("bandit_select", point=decision_point, arm=chosen, propensity=propensity)
    return chosen, propensity, log_id


async def reward(log_id: str, reward_value: float, *, t_offset_h: Optional[int] = None) -> None:
    """Stamp the realized reward back onto a logged decision."""
    async with get_session() as session:
        row = (await session.execute(
            select(BanditLogModel).where(BanditLogModel.id == log_id)
        )).scalar_one_or_none()
        if row is None:
            return
        row.reward = float(reward_value)
        row.reward_t_offset_h = t_offset_h
        row.rewarded_at = datetime.now(timezone.utc)
        await session.flush()


def composite_reward(
    *,
    completion_rate: float | None = None,
    saves_per_view: float | None = None,
    shares_per_view: float | None = None,
    comments_per_view: float | None = None,
    follows_per_view: float | None = None,
    likes_per_view: float | None = None,
    cohort_stats: dict[str, tuple[float, float]] | None = None,
) -> float:
    """Weighted reward per carosel.txt §5 'Composite reward'.

    Inputs are niche-cohort z-scored when ``cohort_stats[name] = (mean, std)``
    is provided; otherwise raw values feed directly into the weighted sum.
    """
    raw = {
        "completion_rate": completion_rate or 0.0,
        "saves_per_view": saves_per_view or 0.0,
        "shares_per_view": shares_per_view or 0.0,
        "comments_per_view": comments_per_view or 0.0,
        "follows_per_view": follows_per_view or 0.0,
        "likes_per_view": likes_per_view or 0.0,
    }
    if cohort_stats:
        normed: dict[str, float] = {}
        for k, v in raw.items():
            mean, sd = cohort_stats.get(k, (0.0, 1.0))
            sd = sd if sd > 1e-9 else 1.0
            normed[k] = (v - mean) / sd
        raw = normed

    weights = {
        "completion_rate": 0.40,
        "saves_per_view": 0.20,
        "shares_per_view": 0.15,
        "comments_per_view": 0.10,
        "follows_per_view": 0.10,
        "likes_per_view": 0.05,
    }
    return sum(weights[k] * raw.get(k, 0.0) for k in weights)


async def stale_arms(decision_point: str, *, days: int = ARM_REINTRO_DAYS) -> list[str]:
    """Arms not pulled in the last N days — return for forced re-introduction
    so a stale optimum can't permanently dominate.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_session() as session:
        rows = (await session.execute(
            select(BanditLogModel.arm_chosen, BanditLogModel.decided_at)
            .where(BanditLogModel.decision_point == decision_point)
        )).all()
    last_pulled: dict[str, datetime] = {}
    for arm, when in rows:
        if when is None:
            continue
        if arm not in last_pulled or when > last_pulled[arm]:
            last_pulled[arm] = when
    return [a for a, t in last_pulled.items() if t < cutoff]
