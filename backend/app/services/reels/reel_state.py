"""reel_generations row lifecycle + reel reconstruction.

Mirrors ``carousel_v2.generation_state`` but for reels. Failure-soft: when the
DB isn't initialised (unit tests), helpers no-op / return None so the pipeline
still runs in-process.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.db.models import ReelGenerationModel, ReelPlatformPublishModel
from app.infrastructure.database import get_session
from app.models.reel import MotivationReel, PlatformPublish

logger = structlog.get_logger(__name__)


async def upsert_reel_state(
    reel: MotivationReel, *, status: Optional[str] = None,
    initiated_by: Optional[str] = None, error: Optional[str] = None,
) -> None:
    """Idempotent upsert of a reel_generations row from a MotivationReel."""
    q = reel.quote.model_dump(mode="json") if reel.quote else {}
    music = reel.music_track.model_dump(mode="json") if reel.music_track else {}
    rubric = reel.rubric.model_dump(mode="json") if reel.rubric else {}
    try:
        async with get_session() as session:
            row = (await session.execute(
                select(ReelGenerationModel).where(ReelGenerationModel.id == reel.id)
            )).scalar_one_or_none()
            fields = dict(
                reel_id=reel.id,
                workflow_id=reel.workflow_id,
                workflow_run_id=reel.workflow_run_id,
                sub_niche=reel.sub_niche,
                theme=reel.theme,
                mood=reel.mood,
                quote_text=reel.quote.text if reel.quote else None,
                quote_author=reel.quote.author if reel.quote else None,
                quote_json=q,
                scenes_json=[s.model_dump(mode="json") for s in reel.scenes],
                music_track_id=reel.music_track.id if reel.music_track else None,
                music_json=music,
                voiceover=reel.voiceover,
                voiceover_url=reel.voiceover_url,
                video_url=reel.video_url,
                video_sha256=reel.video_sha256,
                duration_s=reel.duration_s,
                visual_style=reel.visual_style,
                caption=reel.caption,
                hashtags_json=list(reel.hashtags or []),
                cta_text=reel.cta_text,
                cta_link=reel.cta_link,
                composite_score=reel.composite_score,
                rubric_json=rubric,
                revision_count=reel.revision_count,
                arms_json=dict(reel.arms or {}),
                bandit_log_ids_json=dict(reel.bandit_log_ids or {}),
                status=status or (reel.status if isinstance(reel.status, str) else reel.status.value),
                error=error,
                initiated_by=initiated_by,
                updated_at=datetime.now(timezone.utc),
            )
            if reel.published_at:
                fields["published_at"] = reel.published_at
            if row is None:
                session.add(ReelGenerationModel(
                    id=reel.id, created_at=datetime.now(timezone.utc), **fields
                ))
            else:
                for k, v in fields.items():
                    setattr(row, k, v)
            await session.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("reel_state_upsert_failed", reel_id=reel.id, error=str(exc))


async def record_platform_publish(
    *, reel_id: str, generation_id: Optional[str], pub: PlatformPublish,
) -> None:
    """Upsert one (reel × platform) publish record."""
    try:
        async with get_session() as session:
            row = (await session.execute(
                select(ReelPlatformPublishModel).where(
                    ReelPlatformPublishModel.reel_id == reel_id,
                    ReelPlatformPublishModel.platform == pub.platform,
                )
            )).scalar_one_or_none()
            fields = dict(
                reel_id=reel_id, generation_id=generation_id, platform=pub.platform,
                platform_post_id=pub.post_id, publish_url=pub.publish_url,
                publish_status=pub.status, publish_error=pub.error,
                idempotency_key=pub.idempotency_key, dry_run=pub.dry_run,
                published_at=pub.published_at,
            )
            if row is None:
                session.add(ReelPlatformPublishModel(id=uuid.uuid4().hex, **fields))
            else:
                for k, v in fields.items():
                    setattr(row, k, v)
            await session.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("reel_platform_publish_record_failed", reel_id=reel_id, error=str(exc))


async def get_reel(generation_id: str) -> Optional[dict]:
    """Return the stored reel row as a dict (for the API / review UI)."""
    try:
        async with get_session() as session:
            row = (await session.execute(
                select(ReelGenerationModel).where(ReelGenerationModel.id == generation_id)
            )).scalar_one_or_none()
            if row is None:
                return None
            pubs = (await session.execute(
                select(ReelPlatformPublishModel).where(
                    ReelPlatformPublishModel.reel_id == row.reel_id
                )
            )).scalars().all()
            return _row_to_dict(row, pubs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reel_get_failed", generation_id=generation_id, error=str(exc))
        return None


async def list_reels(*, limit: int = 30, status: Optional[str] = None,
                     sub_niche: Optional[str] = None) -> list[dict]:
    try:
        async with get_session() as session:
            q = select(ReelGenerationModel)
            if status:
                q = q.where(ReelGenerationModel.status == status)
            if sub_niche:
                q = q.where(ReelGenerationModel.sub_niche == sub_niche)
            q = q.order_by(ReelGenerationModel.created_at.desc()).limit(limit)
            rows = (await session.execute(q)).scalars().all()
            return [_row_to_dict(r, []) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("reel_list_failed", error=str(exc))
        return []


def _row_to_dict(row: ReelGenerationModel, pubs) -> dict:
    return {
        "id": row.id,
        "reel_id": row.reel_id,
        "sub_niche": row.sub_niche,
        "theme": row.theme,
        "mood": row.mood,
        "quote": row.quote_json or {"text": row.quote_text, "author": row.quote_author},
        "scenes": row.scenes_json or [],
        "music": row.music_json or {},
        "voiceover": row.voiceover,
        "voiceover_url": row.voiceover_url,
        "video_url": row.video_url,
        "duration_s": row.duration_s,
        "visual_style": row.visual_style,
        "caption": row.caption,
        "hashtags": row.hashtags_json or [],
        "cta_text": row.cta_text,
        "cta_link": row.cta_link,
        "composite_score": row.composite_score,
        "rubric": row.rubric_json or {},
        "status": row.status,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "platform_publishes": [
            {
                "platform": p.platform, "post_id": p.platform_post_id,
                "publish_url": p.publish_url, "status": p.publish_status,
                "dry_run": p.dry_run, "error": p.publish_error,
            } for p in pubs
        ],
    }
