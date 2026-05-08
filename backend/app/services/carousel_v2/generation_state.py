"""carousel_generations row lifecycle.

The Temporal workflow threads state through a context dict, but every
generation also gets a long-lived row in ``carousel_generations`` so post-hoc
queries (drift, golden set, exemplar memory, bandit reward attribution) can
join on ``generation_id`` without orphans.

All operations are failure-soft — when the DB isn't initialised (unit tests
without a Postgres session) the helpers no-op. The activities still update
``ctx`` in-process, so the workflow runs to completion either way.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select

from app.db.models import CarouselGenerationModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


async def upsert_state(
    generation_id: str,
    *,
    topic: Optional[str] = None,
    franchise: Optional[str] = None,
    character_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
    prompt_version_id: Optional[str] = None,
    designer_prompt_id: Optional[str] = None,
    skeptic_prompt_id: Optional[str] = None,
    slides_json: Optional[list] = None,
    judge_scores_json: Optional[dict] = None,
    source_citations_json: Optional[list] = None,
    engagement_metrics_json: Optional[dict] = None,
    composite_score: Optional[float] = None,
    revision_count: Optional[int] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
    published_at: Optional[datetime] = None,
) -> None:
    """Idempotent upsert keyed on ``generation_id``. Failure-soft."""
    try:
        async with get_session() as session:
            existing = (await session.execute(
                select(CarouselGenerationModel).where(CarouselGenerationModel.id == generation_id)
            )).scalar_one_or_none()
            if existing is None:
                if topic is None:
                    topic = "(unknown)"
                row = CarouselGenerationModel(
                    id=generation_id,
                    topic=topic,
                    franchise=franchise,
                    character_id=character_id,
                    workflow_id=workflow_id,
                    workflow_run_id=workflow_run_id,
                    prompt_version_id=prompt_version_id,
                    designer_prompt_id=designer_prompt_id,
                    skeptic_prompt_id=skeptic_prompt_id,
                    slides_json=list(slides_json or []),
                    judge_scores_json=dict(judge_scores_json or {}),
                    source_citations_json=list(source_citations_json or []),
                    engagement_metrics_json=dict(engagement_metrics_json or {}),
                    composite_score=composite_score,
                    revision_count=revision_count or 0,
                    status=status or "pending",
                    error=error,
                    published_at=published_at,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)
                await session.flush()
                return

            existing.updated_at = datetime.now(timezone.utc)
            for field, value in (
                ("topic", topic),
                ("franchise", franchise),
                ("character_id", character_id),
                ("workflow_id", workflow_id),
                ("workflow_run_id", workflow_run_id),
                ("prompt_version_id", prompt_version_id),
                ("designer_prompt_id", designer_prompt_id),
                ("skeptic_prompt_id", skeptic_prompt_id),
                ("composite_score", composite_score),
                ("status", status),
                ("error", error),
                ("published_at", published_at),
            ):
                if value is not None:
                    setattr(existing, field, value)
            if revision_count is not None:
                existing.revision_count = revision_count
            if slides_json is not None:
                existing.slides_json = list(slides_json)
            if judge_scores_json is not None:
                existing.judge_scores_json = dict(judge_scores_json)
            if source_citations_json is not None:
                existing.source_citations_json = list(source_citations_json)
            if engagement_metrics_json is not None:
                existing.engagement_metrics_json = dict(engagement_metrics_json)
            await session.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("generation_state_upsert_failed", generation_id=generation_id, error=str(exc))
