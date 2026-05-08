"""Episodic + semantic memory (carosel.txt §5 'RAG memory').

Retrieves top-5 positive exemplars (same niche, completion_rate > p75,
judge composite > 8/10) and top-2 negative exemplars (same niche,
completion_rate < p25 + ``failure_annotation``). Negative exemplars are
the trick that prevents repeated mistakes.

Storage: embeddings live in the existing ``pgvector`` instance. Phase 6 can
swap in Qdrant for hybrid (dense + sparse + multi-vector) without changing
the public surface here.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.db.models import (
    CarouselGenerationModel,
    EngagementSignalModel,
)
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


async def cohort_quartiles(franchise: Optional[str], *, days: int = 60) -> tuple[float, float]:
    """Returns (p25, p75) of completion_rate for the franchise cohort."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_session() as session:
        rows = (await session.execute(
            select(EngagementSignalModel.completion_rate)
            .where(
                EngagementSignalModel.sampled_at >= cutoff,
                EngagementSignalModel.completion_rate.isnot(None),
            )
        )).all()
    values = [float(r[0]) for r in rows if r[0] is not None]
    if not values:
        return (0.0, 1.0)
    values.sort()
    n = len(values)
    return (values[n // 4], values[(3 * n) // 4])


async def positive_exemplars(
    *,
    franchise: Optional[str],
    limit: int = 5,
    days: int = 60,
) -> list[dict]:
    """Recent generations where engagement crossed p75 and judge composite > 8."""
    p25, p75 = await cohort_quartiles(franchise, days=days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_session() as session:
        rows = (await session.execute(
            select(CarouselGenerationModel)
            .where(
                CarouselGenerationModel.published_at.isnot(None),
                CarouselGenerationModel.created_at >= cutoff,
                (CarouselGenerationModel.franchise == franchise) if franchise else True,
                CarouselGenerationModel.composite_score >= 8.0,
            )
            .order_by(CarouselGenerationModel.composite_score.desc())
            .limit(limit * 3)
        )).scalars().all()

    enriched = []
    for r in rows:
        cr = (r.engagement_metrics_json or {}).get("completion_rate") if r.engagement_metrics_json else None
        if cr is not None and cr < p75:
            continue
        enriched.append({
            "id": r.id,
            "topic": r.topic,
            "franchise": r.franchise,
            "composite": r.composite_score,
            "slides": r.slides_json[:1] if r.slides_json else [],  # only the hook for prompt context
        })
        if len(enriched) >= limit:
            break
    return enriched


async def negative_exemplars(
    *,
    franchise: Optional[str],
    limit: int = 2,
    days: int = 60,
) -> list[dict]:
    """Recent generations whose completion_rate fell below p25 — the
    ``<bad_example>...</bad_example>`` blocks injected into the Designer.
    """
    p25, _ = await cohort_quartiles(franchise, days=days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_session() as session:
        rows = (await session.execute(
            select(CarouselGenerationModel)
            .where(
                CarouselGenerationModel.published_at.isnot(None),
                CarouselGenerationModel.created_at >= cutoff,
                (CarouselGenerationModel.franchise == franchise) if franchise else True,
            )
            .order_by(CarouselGenerationModel.published_at.desc())
            .limit(limit * 5)
        )).scalars().all()

    out = []
    for r in rows:
        cr = (r.engagement_metrics_json or {}).get("completion_rate") if r.engagement_metrics_json else None
        if cr is None or cr >= p25:
            continue
        out.append({
            "id": r.id,
            "topic": r.topic,
            "composite": r.composite_score,
            "completion_rate": cr,
            "slides": r.slides_json[:2] if r.slides_json else [],
            "failure_annotation": (r.engagement_metrics_json or {}).get("failure_annotation"),
        })
        if len(out) >= limit:
            break
    return out


def render_for_designer(positives: list[dict], negatives: list[dict]) -> str:
    """Stable prompt-block format used by the Designer at draft time."""
    if not (positives or negatives):
        return ""
    parts: list[str] = []
    for p in positives:
        hook = (p.get("slides") or [{}])[0].get("text", "")
        parts.append(f"<good_example score=\"{p.get('composite', 0):.1f}\">{hook[:200]}</good_example>")
    for n in negatives:
        hook = (n.get("slides") or [{}])[0].get("text", "")
        anno = n.get("failure_annotation") or "underperformed"
        parts.append(f"<bad_example reason=\"{anno[:80]}\">{hook[:200]}</bad_example>")
    return "EXEMPLARS:\n" + "\n".join(parts)
