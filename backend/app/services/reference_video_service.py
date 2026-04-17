"""
Reference Video Service for TikTok video inspiration / copy feature.
Fetches TikTok video metadata via oEmbed, analyzes with LLM, and generates similar scripts.
"""

import asyncio
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import ReferenceVideoModel, VideoScriptModel, TikTokProductModel
from app.infrastructure.database import get_session
from app.infrastructure.json_utils import extract_json_from_text, llm_retry, sanitize_for_prompt
from app.infrastructure.langchain_adapter import get_zero_chat_model
from app.infrastructure.unified_llm_client import get_unified_llm_client
from app.models.reference_video import ReferenceVideo, ReferenceVideoCreate

logger = structlog.get_logger()

TIKTOK_OEMBED_URL = "https://www.tiktok.com/oembed"


class ReferenceVideoService:
    """Manage TikTok reference videos for content inspiration."""

    def __init__(self):
        from app.infrastructure.circuit_breaker import get_circuit_breaker
        self._breaker = get_circuit_breaker("tiktok_oembed", failure_threshold=5, recovery_timeout=60.0)

    def _generate_id(self) -> str:
        return f"ref-{uuid.uuid4().hex[:12]}"

    def _model_to_pydantic(self, row: ReferenceVideoModel) -> ReferenceVideo:
        return ReferenceVideo(
            id=row.id,
            tiktok_url=row.tiktok_url,
            product_id=row.product_id,
            title=row.title,
            author_name=row.author_name,
            author_url=row.author_url,
            thumbnail_url=row.thumbnail_url,
            caption=row.caption,
            hashtags=row.hashtags or [],
            views=row.views,
            likes=row.likes,
            comments=row.comments,
            shares=row.shares,
            hook_analysis=row.hook_analysis,
            structure_analysis=row.structure_analysis,
            style_notes=row.style_notes,
            content_type=row.content_type,
            estimated_duration=row.estimated_duration,
            generated_script_id=row.generated_script_id,
            status=row.status or "pending",
            created_at=row.created_at or datetime.now(timezone.utc),
            analyzed_at=row.analyzed_at,
        )

    async def create_reference(self, data: ReferenceVideoCreate) -> ReferenceVideo:
        """Create a reference video record and trigger analysis."""
        ref_id = self._generate_id()
        async with get_session() as session:
            row = ReferenceVideoModel(
                id=ref_id,
                tiktok_url=data.tiktok_url,
                product_id=data.product_id,
                status="pending",
            )
            session.add(row)
            await session.flush()
            ref = self._model_to_pydantic(row)

        # Auto-analyze
        try:
            ref = await self.analyze_video(ref_id)
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("auto_analyze_failed", ref_id=ref_id, error=str(e))

        return ref

    async def analyze_video(self, ref_id: str) -> ReferenceVideo:
        """Fetch oEmbed metadata and run LLM analysis on the video."""
        async with get_session() as session:
            result = await session.execute(
                select(ReferenceVideoModel).where(ReferenceVideoModel.id == ref_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Reference video {ref_id} not found")

            # Step 1: Fetch TikTok oEmbed data
            oembed = await self._fetch_oembed(row.tiktok_url)
            if oembed:
                row.title = oembed.get("title")
                row.author_name = oembed.get("author_name")
                row.author_url = oembed.get("author_url")
                row.thumbnail_url = oembed.get("thumbnail_url")
                # oEmbed title is often the caption
                row.caption = oembed.get("title")

            # Extract hashtags from caption
            if row.caption:
                hashtags = re.findall(r"#(\w+)", row.caption)
                row.hashtags = hashtags

            # Step 2: LLM analysis of the video caption and metadata
            analysis = await self._llm_analyze(row)
            if analysis:
                row.hook_analysis = analysis.get("hook_analysis")
                row.structure_analysis = analysis.get("structure_analysis")
                row.style_notes = analysis.get("style_notes")
                row.content_type = analysis.get("content_type")
                row.estimated_duration = analysis.get("estimated_duration")

            row.status = "analyzed"
            row.analyzed_at = datetime.now(timezone.utc)
            await session.flush()
            return self._model_to_pydantic(row)

    async def _fetch_oembed(self, tiktok_url: str) -> Optional[dict]:
        """Fetch TikTok video metadata via oEmbed API (public, no auth)."""
        try:
            return await self._breaker.call(self._do_oembed_fetch, tiktok_url)
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError) as e:
            logger.warning("oembed_fetch_failed", url=tiktok_url, error=str(e))
        return None

    async def _do_oembed_fetch(self, tiktok_url: str) -> Optional[dict]:
        """Inner oEmbed fetch, wrapped by circuit breaker."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(TIKTOK_OEMBED_URL, params={"url": tiktok_url})
            if resp.status_code == 200:
                return resp.json()
            logger.warning("oembed_non_200", status=resp.status_code, url=tiktok_url)
            return None

    @llm_retry
    async def _do_llm_analyze(self, prompt: str) -> dict:
        """Retryable LLM analysis call."""
        client = get_unified_llm_client()
        return await client.structured_chat(
            prompt=prompt,
            system="You are a TikTok content analyst.",
            task_type="extraction",
            temperature=0.5,
            max_tokens=2048,
            output_schema={"hook_analysis": "str", "structure_analysis": "str", "style_notes": "str", "content_type": "str", "estimated_duration": 30},
        )

    async def _llm_analyze(self, row: ReferenceVideoModel) -> Optional[dict]:
        """LLM analyzes the video caption/title for content strategy insights."""
        if not row.caption and not row.title:
            return None

        try:
            content = sanitize_for_prompt(row.caption or row.title or "", max_length=1000)
            hashtags = sanitize_for_prompt(", ".join(row.hashtags or []), max_length=500)

            prompt = (
                f"Analyze this TikTok video for content strategy insights.\n\n"
                f"Video caption: {content}\n"
                f"Hashtags: {hashtags}\n"
                f"Author: {row.author_name or 'Unknown'}\n\n"
                f"Provide: hook_analysis (technique used), structure_analysis (video structure), "
                f"style_notes (tone), content_type (one of: review, unboxing, tutorial, comedy, "
                f"aesthetic, comparison, storytelling, duet, trend), estimated_duration (seconds as integer)"
            )

            data = await self._do_llm_analyze(prompt)

            if isinstance(data, dict):
                if isinstance(data.get("estimated_duration"), str):
                    try:
                        data["estimated_duration"] = int(re.sub(r"\D", "", data["estimated_duration"]))
                    except (ValueError, TypeError):
                        data["estimated_duration"] = 30
                return data
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError) as e:
            logger.warning("llm_analyze_failed", ref_id=row.id, error=str(e))
        return None

    async def generate_script_from_reference(
        self,
        ref_id: str,
        product_id: str,
        template_type: str = "voiceover_broll",
    ) -> dict:
        """Generate a video script for a product based on a reference video's style."""
        async with get_session() as session:
            # Load reference
            ref_result = await session.execute(
                select(ReferenceVideoModel).where(ReferenceVideoModel.id == ref_id)
            )
            ref = ref_result.scalar_one_or_none()
            if not ref:
                raise ValueError(f"Reference video {ref_id} not found")

            # Load product
            prod_result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            product = prod_result.scalar_one_or_none()
            if not product:
                raise ValueError(f"Product {product_id} not found")

            # Generate script via LLM
            client = get_unified_llm_client()

            prompt = f"""You are a TikTok content strategist. Create a video script for my product that copies the style of a successful reference video.

REFERENCE VIDEO:
- Caption: {sanitize_for_prompt(ref.caption or ref.title or 'N/A', 500)}
- Hook technique: {ref.hook_analysis or 'Unknown'}
- Video structure: {ref.structure_analysis or 'Unknown'}
- Style/tone: {ref.style_notes or 'Unknown'}
- Content type: {ref.content_type or 'Unknown'}
- Hashtags: {', '.join(ref.hashtags or [])[:300]}

MY PRODUCT:
- Name: {sanitize_for_prompt(product.name, 200)}
- Niche: {product.niche or 'general'}
- Description: {sanitize_for_prompt(product.description or 'N/A', 500)}
- Why trending: {sanitize_for_prompt(product.why_trending or 'N/A', 300)}

Create a {template_type} style script. Return ONLY JSON:
{{
    "hook_text": "attention-grabbing first 2-3 seconds text",
    "body_sections": [{{"title": "section name", "content": "what happens in this section"}}],
    "cta_text": "call to action text",
    "text_overlays": ["overlay 1", "overlay 2"],
    "voiceover_script": "full voiceover narration",
    "caption": "TikTok post caption",
    "hashtags": ["hashtag1", "hashtag2"]
}}"""

            try:
                script_data = await client.structured_chat(
                    prompt=prompt,
                    system="You are a TikTok content strategist. Create engaging video scripts.",
                    task_type="structured_output",
                    temperature=0.7,
                    max_tokens=4096,
                )
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError):
                script_data = {}

            # Fallback if parsing failed
            if not script_data.get("hook_text"):
                script_data = {
                    "hook_text": f"You NEED this {product.name}!",
                    "body_sections": [{"title": "Why it's trending", "content": product.why_trending or product.description or ""}],
                    "cta_text": "Link in bio!",
                    "text_overlays": [product.name],
                    "voiceover_script": (product.description or product.why_trending or product.name)[:500],
                    "caption": f"{product.name} #tiktokshop",
                    "hashtags": ref.hashtags or ["tiktokshop", "trending"],
                }

            # Duration based on template
            duration_map = {
                "voiceover_broll": 30,
                "text_overlay_showcase": 15,
                "before_after": 20,
                "listicle_topn": 30,
                "problem_solution": 25,
            }

            # Save as VideoScript
            script_id = f"vs-{uuid.uuid4().hex[:12]}"
            script_row = VideoScriptModel(
                id=script_id,
                product_id=product_id,
                template_type=template_type,
                hook_text=script_data.get("hook_text", ""),
                body_json=script_data.get("body_sections", []),
                cta_text=script_data.get("cta_text", ""),
                text_overlays=script_data.get("text_overlays", []),
                voiceover_script=script_data.get("voiceover_script", ""),
                duration_seconds=duration_map.get(template_type, 30),
                status="draft",
                reference_video_id=ref_id,
            )
            session.add(script_row)

            # Update reference with generated script link
            ref.generated_script_id = script_id
            ref.status = "script_created"

            await session.flush()

            logger.info(
                "reference_script_generated",
                ref_id=ref_id,
                product_id=product_id,
                script_id=script_id,
            )

            return {
                "script_id": script_id,
                "reference_id": ref_id,
                "product_id": product_id,
                "template_type": template_type,
                "hook_text": script_data.get("hook_text"),
                "voiceover_script": script_data.get("voiceover_script"),
                "caption": script_data.get("caption"),
                "hashtags": script_data.get("hashtags"),
                "status": "draft",
            }

    async def auto_discover_references(self, product_id: str, max_refs: int = 5) -> List[ReferenceVideo]:
        """For an approved product, search for existing TikTok videos promoting it."""
        from app.services.searxng_service import get_searxng_service

        async with get_session() as session:
            prod_result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            product = prod_result.scalar_one_or_none()
            if not product:
                return []

        searxng = get_searxng_service()
        queries = [
            f'tiktok.com "{product.name}" review',
            f'tiktok shop "{product.name}" showcase',
        ]

        tiktok_urls = set()
        for query in queries:
            try:
                results = await searxng.search(query, num_results=5)
                for r in results:
                    url = r.url if hasattr(r, 'url') else (r.get('url') if isinstance(r, dict) else '')
                    if url and 'tiktok.com' in url and '/video/' in url:
                        tiktok_urls.add(url)
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError) as e:
                logger.warning("reference_search_failed", query=query, error=str(e))

        # Check existing references to avoid duplicates
        async with get_session() as session:
            existing = await session.execute(
                select(ReferenceVideoModel.tiktok_url).where(
                    ReferenceVideoModel.product_id == product_id
                )
            )
            existing_urls = {r[0] for r in existing.all()}

        new_urls = list(tiktok_urls - existing_urls)[:max_refs]
        refs = []
        for url in new_urls:
            try:
                ref = await self.create_reference(
                    ReferenceVideoCreate(tiktok_url=url, product_id=product_id)
                )
                refs.append(ref)
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                logger.warning("reference_create_failed", url=url, error=str(e))

        logger.info("auto_discover_references_complete",
                     product_id=product_id, found=len(tiktok_urls), created=len(refs))
        return refs

    async def list_references(
        self,
        product_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ReferenceVideo]:
        async with get_session() as session:
            query = select(ReferenceVideoModel).order_by(
                ReferenceVideoModel.created_at.desc()
            )
            if product_id:
                query = query.where(ReferenceVideoModel.product_id == product_id)
            if status:
                query = query.where(ReferenceVideoModel.status == status)
            if offset > 0:
                query = query.offset(offset)
            query = query.limit(limit)

            result = await session.execute(query)
            rows = result.scalars().all()
            return [self._model_to_pydantic(r) for r in rows]

    async def get_reference(self, ref_id: str) -> Optional[ReferenceVideo]:
        async with get_session() as session:
            result = await session.execute(
                select(ReferenceVideoModel).where(ReferenceVideoModel.id == ref_id)
            )
            row = result.scalar_one_or_none()
            return self._model_to_pydantic(row) if row else None

    async def delete_reference(self, ref_id: str) -> bool:
        async with get_session() as session:
            result = await session.execute(
                select(ReferenceVideoModel).where(ReferenceVideoModel.id == ref_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return False
            await session.delete(row)
            await session.flush()
            return True


def get_reference_video_service() -> ReferenceVideoService:
    """Get reference video service instance."""
    return ReferenceVideoService()
