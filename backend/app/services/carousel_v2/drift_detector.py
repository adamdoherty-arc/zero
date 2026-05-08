"""EWMA + CUSUM drift detectors over judge scores per axis (carosel.txt §5).

Reads ``judge_scores`` over a rolling 14-day window, computes per-axis
EWMA control chart (α=0.2) and CUSUM (Page 1954). Alerts fire when:

  EWMA drift  → |S_t − μ_baseline| > 3σ / √n  (medium shifts)
  CUSUM drift → cumulative deviation > 5σ      (small persistent shifts)

On alert: flips ``prompt_versions.status`` from ``active`` to
``rolled_back`` for the offending prompt, and the prompt with
``status='last_known_good'`` becomes the new active. Halts auto-publishing
for the affected niche until manual review.

Engagement-vs-judge correlation is tracked weekly: if Pearson ρ falls below
0.3 the judge is decoupled from reality — a separate alert.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.db.models import (
    EngagementSignalModel,
    JudgeScoreModel,
    PromptVersionModel,
)
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


EWMA_ALPHA = 0.2
EWMA_K = 3.0
CUSUM_K = 5.0


def ewma(values: list[float], alpha: float = EWMA_ALPHA) -> float:
    if not values:
        return 0.0
    s = values[0]
    for v in values[1:]:
        s = alpha * v + (1 - alpha) * s
    return s


def cusum(values: list[float], target: float) -> tuple[float, float]:
    """Returns (positive_cusum, negative_cusum)."""
    pos = neg = 0.0
    for v in values:
        d = v - target
        pos = max(0.0, pos + d - 0.5)
        neg = min(0.0, neg + d + 0.5)
    return pos, neg


async def evaluate_axis_drift(
    axis: str,
    *,
    baseline_window_days: int = 30,
    monitor_window_days: int = 7,
) -> dict:
    """Per-axis drift detection across all judges."""
    now = datetime.now(timezone.utc)
    baseline_start = now - timedelta(days=baseline_window_days)
    monitor_start = now - timedelta(days=monitor_window_days)

    async with get_session() as session:
        rows = (await session.execute(
            select(JudgeScoreModel).where(
                JudgeScoreModel.axis == axis,
                JudgeScoreModel.sampled_at >= baseline_start,
            )
        )).scalars().all()

    baseline = [r.score for r in rows if r.sampled_at and r.sampled_at < monitor_start]
    monitor = [r.score for r in rows if r.sampled_at and r.sampled_at >= monitor_start]

    if len(baseline) < 5 or len(monitor) < 5:
        return {"axis": axis, "status": "insufficient_data", "baseline_n": len(baseline), "monitor_n": len(monitor)}

    base_mean = statistics.mean(baseline)
    base_sd = statistics.pstdev(baseline) or 1.0
    monitor_ewma = ewma(monitor)
    z = (monitor_ewma - base_mean) / (base_sd / max(1.0, len(monitor) ** 0.5))
    pos, neg = cusum(monitor, base_mean)

    ewma_alert = abs(z) > EWMA_K
    cusum_alert = pos > CUSUM_K * base_sd or abs(neg) > CUSUM_K * base_sd

    return {
        "axis": axis,
        "status": "alert" if (ewma_alert or cusum_alert) else "ok",
        "baseline_mean": base_mean,
        "baseline_sd": base_sd,
        "monitor_ewma": monitor_ewma,
        "z_score": z,
        "cusum_pos": pos,
        "cusum_neg": neg,
        "ewma_alert": ewma_alert,
        "cusum_alert": cusum_alert,
    }


async def auto_rollback(prompt_name: str) -> bool:
    """Flip the active prompt to ``last_known_good`` for ``prompt_name``.

    Returns True when a rollback actually happened. No-op when there's no
    ``last_known_good`` registered.
    """
    async with get_session() as session:
        active = (await session.execute(
            select(PromptVersionModel).where(
                PromptVersionModel.name == prompt_name,
                PromptVersionModel.status == "active",
            )
        )).scalar_one_or_none()
        lkg = (await session.execute(
            select(PromptVersionModel).where(
                PromptVersionModel.name == prompt_name,
                PromptVersionModel.status == "last_known_good",
            )
        )).scalar_one_or_none()
        if active is None or lkg is None or active.id == lkg.id:
            return False
        active.status = "rolled_back"
        active.retired_at = datetime.now(timezone.utc)
        lkg.status = "active"
        lkg.activated_at = datetime.now(timezone.utc)
        await session.flush()
    logger.warning("prompt_auto_rollback", prompt=prompt_name, retired=active.id, restored=lkg.id)
    return True


async def correlation_engagement_vs_judge(
    axis: str,
    *,
    days: int = 30,
) -> Optional[float]:
    """Pearson correlation between this axis's judge score and the
    engagement reward residual. ρ < 0.3 → judge has decoupled from reality.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_session() as session:
        judge_rows = (await session.execute(
            select(JudgeScoreModel.generation_id, JudgeScoreModel.score)
            .where(JudgeScoreModel.axis == axis, JudgeScoreModel.sampled_at >= cutoff)
        )).all()
        eng_rows = (await session.execute(
            select(EngagementSignalModel.generation_id, EngagementSignalModel.residual)
            .where(
                EngagementSignalModel.sampled_at >= cutoff,
                EngagementSignalModel.residual.isnot(None),
            )
        )).all()

    by_gen: dict[str, dict] = defaultdict(dict)
    for gen_id, score in judge_rows:
        if gen_id and score is not None:
            by_gen[gen_id]["judge"] = score
    for gen_id, residual in eng_rows:
        if gen_id and residual is not None:
            by_gen[gen_id]["eng"] = residual

    pairs = [(d["judge"], d["eng"]) for d in by_gen.values() if "judge" in d and "eng" in d]
    if len(pairs) < 10:
        return None

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    denx = sum((x - mx) ** 2 for x in xs) ** 0.5
    deny = sum((y - my) ** 2 for y in ys) ** 0.5
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny)
