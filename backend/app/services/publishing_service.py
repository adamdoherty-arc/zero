"""
Multi-Platform Publishing Service.

Manages content publishing to TikTok (and extensible to other platforms).
Orchestrates the flow: review → approve → publish → track status.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from functools import lru_cache

import aiohttp
import structlog
from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.database import get_session
from app.db.models import ContentQueueModel, VideoScriptModel, TikTokProductModel

logger = structlog.get_logger(__name__)


class PublishingService:
    """Orchestrates content publishing across platforms."""

    # ============================================
    # REVIEW QUEUE
    # ============================================

    async def get_review_items(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get content items for review, joining product + script + queue data."""
        async with get_session() as session:
            query = (
                select(ContentQueueModel, VideoScriptModel, TikTokProductModel)
                .join(VideoScriptModel, ContentQueueModel.script_id == VideoScriptModel.id)
                .join(TikTokProductModel, ContentQueueModel.product_id == TikTokProductModel.id)
                .order_by(ContentQueueModel.created_at.desc())
            )
            if offset > 0:
                query = query.offset(offset)
            query = query.limit(limit)

            if status:
                query = query.where(ContentQueueModel.publish_status == status)
            else:
                # Show all review-relevant items (not null publish_status)
                query = query.where(ContentQueueModel.publish_status.isnot(None))

            result = await session.execute(query)
            items = []
            for queue, script, product in result.all():
                items.append(self._build_review_item(queue, script, product))
            return items

    async def get_review_item(self, queue_id: str) -> Optional[Dict[str, Any]]:
        """Get a single review item by queue ID."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel, VideoScriptModel, TikTokProductModel)
                .join(VideoScriptModel, ContentQueueModel.script_id == VideoScriptModel.id)
                .join(TikTokProductModel, ContentQueueModel.product_id == TikTokProductModel.id)
                .where(ContentQueueModel.id == queue_id)
            )
            row = result.one_or_none()
            if not row:
                return None
            queue, script, product = row
            return self._build_review_item(queue, script, product)

    # ============================================
    # APPROVE / REJECT
    # ============================================

    async def approve_content(
        self,
        queue_id: str,
        caption: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Approve content for publishing, with optional caption/hashtag edits."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            row.publish_status = "approved"
            if caption is not None:
                row.caption = caption
            if hashtags is not None:
                row.hashtags = hashtags

            await session.flush()

        return await self.get_review_item(queue_id)

    async def reject_content(self, queue_id: str, reason: Optional[str] = None) -> bool:
        """Reject content from the review queue."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return False

            row.publish_status = "rejected"
            if reason:
                row.publish_error = reason
            await session.flush()
            return True

    # ============================================
    # PUBLISHING
    # ============================================

    async def publish_content(self, queue_id: str, platform: str = "tiktok") -> Dict[str, Any]:
        """Publish approved content to specified platform."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel, VideoScriptModel)
                .join(VideoScriptModel, ContentQueueModel.script_id == VideoScriptModel.id)
                .where(ContentQueueModel.id == queue_id)
            )
            row = result.one_or_none()
            if not row:
                return {"success": False, "error": "Content not found"}

            queue, script = row

            if queue.publish_status not in ("approved", "publish_failed"):
                return {"success": False, "error": f"Content must be approved first (current: {queue.publish_status})"}

            # Mark as publishing
            queue.publish_status = "publishing"
            queue.publish_platform = platform
            await session.flush()

        if platform == "tiktok":
            return await self._publish_to_tiktok(queue_id)
        else:
            return {"success": False, "error": f"Platform '{platform}' not yet supported"}

    async def publish_all_approved(self, platform: str = "tiktok") -> Dict[str, Any]:
        """Publish all approved content items."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel.id).where(
                    ContentQueueModel.publish_status == "approved"
                )
            )
            queue_ids = [r[0] for r in result.all()]

        results = []
        for qid in queue_ids:
            result = await self.publish_content(qid, platform)
            results.append({"queue_id": qid, **result})

        published = sum(1 for r in results if r.get("success"))
        failed = sum(1 for r in results if not r.get("success"))
        return {
            "total": len(results),
            "published": published,
            "failed": failed,
            "results": results,
        }

    async def _publish_to_tiktok(self, queue_id: str) -> Dict[str, Any]:
        """Publish content to TikTok via Content Posting API."""
        from app.infrastructure.tiktok_api_client import get_tiktok_api_client
        client = get_tiktok_api_client()

        if not client.is_configured:
            await self._mark_publish_failed(queue_id, "TikTok API not configured. Add ZERO_TIKTOK_CLIENT_KEY and ZERO_TIKTOK_CLIENT_SECRET.")
            return {"success": False, "error": "TikTok API not configured"}

        if not client.is_authorized:
            await client.load_tokens_from_db()
            if not client.is_authorized:
                await self._mark_publish_failed(queue_id, "TikTok not authorized. Click 'Connect TikTok' in settings.")
                return {"success": False, "error": "TikTok not authorized"}

        # Get the content queue item with its video URL
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
            )
            queue = result.scalar_one_or_none()
            if not queue:
                return {"success": False, "error": "Queue item not found"}

            # Build caption with hashtags
            caption = queue.caption or ""
            if queue.hashtags:
                tags = " ".join(f"#{h.strip('#')}" for h in queue.hashtags)
                caption = f"{caption}\n\n{tags}" if caption else tags

            # Get video URL - try multiple sources
            video_url = getattr(queue, 'video_url', None)

            # If no direct video_url, try to get from AIContentTools via job_id
            if not video_url and queue.act_job_id:
                try:
                    from app.services.ai_content_tools_client import get_ai_content_tools_client
                    act_client = get_ai_content_tools_client()
                    video_url = await act_client.get_video_download_url(queue.act_job_id)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                    logger.warning("tiktok_get_video_url_failed", error=str(e))

            # Fallback: try generation_id with performance API
            if not video_url and queue.act_generation_id:
                try:
                    from app.services.ai_content_tools_client import get_ai_content_tools_client
                    act_client = get_ai_content_tools_client()
                    perf = await act_client.get_performance(generation_id=queue.act_generation_id)
                    if perf and len(perf) > 0:
                        video_url = perf[0].get("video_url") or perf[0].get("url")
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                    logger.warning("tiktok_get_video_url_perf_failed", error=str(e))

            if not video_url:
                await self._mark_publish_failed(queue_id, "No video URL available. Upload a video or wait for generation to complete.")
                return {"success": False, "error": "No video URL available"}

        # Post to TikTok
        try:
            post_result = await client.create_post(
                caption=caption[:150],
                video_url=video_url,
                privacy_level="PUBLIC_TO_EVERYONE",
            )

            if not post_result or post_result.get("error"):
                error = post_result.get("error", "Unknown error") if post_result else "No response"
                await self._mark_publish_failed(queue_id, str(error))
                return {"success": False, "error": str(error)}

            publish_id = post_result.get("data", {}).get("publish_id", "")

            async with get_session() as session:
                result = await session.execute(
                    select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
                )
                row = result.scalar_one_or_none()
                if row:
                    row.publish_status = "published"
                    row.published_at = datetime.now(timezone.utc)
                    row.publish_url = f"https://www.tiktok.com/@me/video/{publish_id}"
                    await session.flush()

            return {"success": True, "publish_id": publish_id}

        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            await self._mark_publish_failed(queue_id, str(e))
            return {"success": False, "error": str(e)}

    async def _mark_publish_failed(self, queue_id: str, error: str):
        """Mark a queue item as publish_failed."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.publish_status = "publish_failed"
                row.publish_error = error
                await session.flush()

    # ============================================
    # PLATFORM STATUS
    # ============================================

    async def get_publish_readiness(self) -> Dict[str, Any]:
        """Check which platforms are configured and ready for publishing."""
        from app.infrastructure.tiktok_api_client import get_tiktok_api_client
        client = get_tiktok_api_client()

        if not client.is_authorized:
            await client.load_tokens_from_db()

        tiktok_status = client.get_status()

        # Count items by publish status
        async with get_session() as session:
            from sqlalchemy import func as sql_func
            counts_result = await session.execute(
                select(
                    ContentQueueModel.publish_status,
                    sql_func.count().label("cnt")
                )
                .where(ContentQueueModel.publish_status.isnot(None))
                .group_by(ContentQueueModel.publish_status)
            )
            counts = {r[0]: r[1] for r in counts_result.all()}

        return {
            "platforms": {
                "tiktok": tiktok_status,
            },
            "queue_counts": {
                "pending_review": counts.get("pending_review", 0),
                "approved": counts.get("approved", 0),
                "publishing": counts.get("publishing", 0),
                "published": counts.get("published", 0),
                "publish_failed": counts.get("publish_failed", 0),
                "rejected": counts.get("rejected", 0),
            },
        }

    # ============================================
    # HELPERS
    # ============================================

    def _build_review_item(
        self, queue: ContentQueueModel, script: VideoScriptModel, product: TikTokProductModel
    ) -> Dict[str, Any]:
        """Build a rich review item combining product, script, and queue data."""
        return {
            "queue_id": queue.id,
            "product": {
                "id": product.id,
                "name": product.name,
                "niche": product.niche,
                "category": product.category,
                "image_url": product.image_url,
                "opportunity_score": product.opportunity_score,
                "why_trending": product.why_trending,
                "estimated_price_range": product.estimated_price_range,
            },
            "script": {
                "id": script.id,
                "template_type": script.template_type,
                "hook_text": script.hook_text,
                "body_sections": script.body_json or [],
                "cta_text": script.cta_text,
                "text_overlays": script.text_overlays or [],
                "voiceover_script": script.voiceover_script,
                "duration_seconds": script.duration_seconds,
                "status": script.status,
            },
            "queue": {
                "id": queue.id,
                "status": queue.status,
                "generation_type": queue.generation_type,
                "act_job_id": queue.act_job_id,
                "act_generation_id": queue.act_generation_id,
                "created_at": queue.created_at.isoformat() if queue.created_at else None,
                "completed_at": queue.completed_at.isoformat() if queue.completed_at else None,
            },
            "publish": {
                "status": queue.publish_status,
                "platform": queue.publish_platform,
                "url": queue.publish_url,
                "published_at": queue.published_at.isoformat() if queue.published_at else None,
                "error": queue.publish_error,
                "caption": queue.caption,
                "hashtags": queue.hashtags or [],
            },
        }


@lru_cache()
def get_publishing_service() -> PublishingService:
    """Get cached publishing service instance."""
    return PublishingService()
