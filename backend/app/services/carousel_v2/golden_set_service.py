"""Golden set CRUD + Cohen's κ replay (carosel.txt §5).

Hand-rated carousels live in ``golden_set``; CI replays every prompt change
against this corpus and gates merges that regress composite by >5% within
95% CI. ``mark_as_golden`` is wired to the frontend ``CarouselEditorPage``
in Phase 6.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.db.models import GoldenSetModel, JudgeScoreModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


async def mark_as_golden(
    *,
    carousel_id: str,
    human_score_per_axis: dict[str, float],
    human_rater: str,
    franchise: Optional[str] = None,
    generation_id: Optional[str] = None,
    notes: Optional[str] = None,
    adversarial_category: Optional[str] = None,
) -> str:
    """Idempotent on (carousel_id) — re-marking updates scores."""
    async with get_session() as session:
        existing = (await session.execute(
            select(GoldenSetModel).where(GoldenSetModel.carousel_id == carousel_id)
        )).scalar_one_or_none()
        composite = _composite(human_score_per_axis)
        if existing is not None:
            existing.human_score_per_axis = human_score_per_axis
            existing.human_composite = composite
            existing.human_rater = human_rater
            existing.notes = notes or existing.notes
            existing.adversarial_category = adversarial_category or existing.adversarial_category
            existing.frozen = True
            await session.flush()
            return existing.id

        new_id = uuid.uuid4().hex
        session.add(
            GoldenSetModel(
                id=new_id,
                carousel_id=carousel_id,
                generation_id=generation_id,
                franchise=franchise,
                frozen=True,
                human_score_per_axis=human_score_per_axis,
                human_composite=composite,
                human_rater=human_rater,
                notes=notes,
                adversarial_category=adversarial_category,
                added_at=datetime.now(timezone.utc),
            )
        )
        await session.flush()
        return new_id


def _composite(per_axis: dict[str, float]) -> float:
    from app.models.carousel import RUBRIC_WEIGHTS, RubricAxis
    total = 0.0
    for axis, weight in RUBRIC_WEIGHTS.items():
        total += float(per_axis.get(axis.value, 0.0)) * weight
    return total


def cohen_kappa_score(human: list[int], judge: list[int], *, n_bins: int = 5) -> float:
    """Quadratic-weighted Cohen's κ for binned ordinal scores."""
    if len(human) != len(judge) or not human:
        return 0.0
    n = len(human)
    bins = list(range(n_bins))

    def bucket(x: float) -> int:
        return max(0, min(n_bins - 1, int(round((x / 10.0) * (n_bins - 1)))))

    h = [bucket(v) for v in human]
    j = [bucket(v) for v in judge]
    h_dist = Counter(h)
    j_dist = Counter(j)
    obs = Counter(zip(h, j))

    weights = [[((a - b) ** 2) / ((n_bins - 1) ** 2) for b in bins] for a in bins]
    expected = [[(h_dist[a] / n) * (j_dist[b] / n) for b in bins] for a in bins]

    num = sum(weights[a][b] * (obs.get((a, b), 0) / n) for a in bins for b in bins)
    den = sum(weights[a][b] * expected[a][b] for a in bins for b in bins)
    if den == 0:
        return 1.0 if num == 0 else 0.0
    return 1.0 - (num / den)


async def kappa_per_judge(axis: str) -> dict[str, float]:
    """For a given axis, compute Cohen's κ between each judge and the
    human-rated golden set.
    """
    async with get_session() as session:
        gs = (await session.execute(select(GoldenSetModel))).scalars().all()
        carousel_ids = [g.carousel_id for g in gs]
        if not carousel_ids:
            return {}

        judge_rows = (await session.execute(
            select(JudgeScoreModel).where(
                JudgeScoreModel.axis == axis,
                JudgeScoreModel.carousel_id.in_(carousel_ids),
            )
        )).scalars().all()

    human_by_id: dict[str, float] = {
        g.carousel_id: float((g.human_score_per_axis or {}).get(axis, 0.0))
        for g in gs
    }
    judge_scores: dict[str, dict[str, list[float]]] = {}
    for row in judge_rows:
        judge_scores.setdefault(row.judge_name, {}).setdefault(row.carousel_id, []).append(row.score)

    out: dict[str, float] = {}
    for judge_name, by_carousel in judge_scores.items():
        pairs: list[tuple[float, float]] = []
        for cid, scores in by_carousel.items():
            if cid not in human_by_id:
                continue
            pairs.append((human_by_id[cid], statistics.median(scores)))
        if len(pairs) < 5:
            continue
        out[judge_name] = cohen_kappa_score([int(p[0]) for p in pairs], [int(p[1]) for p in pairs])
    return out


async def replay_against_golden(prompt_version_id: str) -> dict:
    """Stub for the CI gate — Phase 6 wires the actual prompt-replay loop.

    Phase 6 adds: load the golden carousels, regenerate each with the
    candidate prompt, judge with the panel, compare composite vs human
    consensus. Block merge when regression > 5% within 95% CI.
    """
    async with get_session() as session:
        n = (await session.execute(select(GoldenSetModel))).scalars().all()
    return {
        "prompt_version_id": prompt_version_id,
        "golden_set_size": len(n),
        "status": "stub_phase6_replay_not_yet_wired",
    }
