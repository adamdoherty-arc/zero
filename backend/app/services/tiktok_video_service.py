"""
TikTok Faceless Video Service.

Generates video scripts from templates, queues them for AIContentTools generation,
and tracks the content pipeline. Uses LangChain for LLM calls.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog
import uuid

from sqlalchemy import select, func as sql_func

from app.infrastructure.database import get_session
from app.infrastructure.langchain_adapter import get_zero_chat_model
from app.db.models import VideoScriptModel, ContentQueueModel, TikTokProductModel
from app.models.tiktok_content import (
    VideoScript, VideoScriptCreate, VideoScriptUpdate,
    VideoScriptStatus, VideoTemplateType, VideoTemplateInfo,
    ContentQueueItem, ContentQueueStatus, ContentQueueStats,
)

logger = structlog.get_logger()


# ============================================
# FACELESS VIDEO TEMPLATES
# ============================================

FACELESS_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "voiceover_broll": {
        "name": "Voiceover + B-Roll",
        "description": "AI voiceover narrating over product footage and stock clips. No face shown.",
        "duration": 30,
        "sections": ["hook", "problem", "solution", "benefit", "cta"],
        "prompt_template": (
            "Create a TikTok video script for a faceless voiceover-style video.\n"
            "Product: {product_name}\n"
            "Niche: {niche}\n"
            "Description: {description}\n\n"
            "The video is {duration}s with AI voiceover over B-roll footage.\n"
            "NO FACE is shown. Visual style: product close-ups, lifestyle B-roll, text overlays.\n\n"
            "Write the script with these sections:\n"
            "1. HOOK (0-3s): Pattern interrupt or curiosity gap. Must stop the scroll.\n"
            "2. PROBLEM (3-10s): Pain point the viewer relates to.\n"
            "3. SOLUTION (10-18s): Present the product as the solution. Show it in use.\n"
            "4. BENEFIT (18-25s): Key benefit with social proof or stats.\n"
            "5. CTA (25-30s): Clear call to action.\n\n"
            "For each section provide:\n"
            "- voiceover: What the AI voice says\n"
            "- visual: What the viewer sees (B-roll description)\n"
            "- text_overlay: On-screen text (short, impactful)\n\n"
            "Also provide:\n"
            "- caption: TikTok caption with emojis and hooks\n"
            "- hashtags: 5-8 relevant hashtags\n"
            "- music_mood: Suggested background music mood\n\n"
            "Return as JSON with keys: sections (array), caption, hashtags (array), music_mood"
        ),
    },
    "text_overlay_showcase": {
        "name": "Text Overlay Product Showcase",
        "description": "Text captions + product images/clips with trending audio. No voice needed.",
        "duration": 15,
        "sections": ["hook_text", "feature_1", "feature_2", "price_reveal", "cta_text"],
        "prompt_template": (
            "Create a TikTok video script for a text-overlay product showcase.\n"
            "Product: {product_name}\n"
            "Niche: {niche}\n"
            "Description: {description}\n\n"
            "The video is {duration}s with ONLY text overlays on screen. No voice.\n"
            "Uses trending audio/music. Text appears in sync with beat drops.\n\n"
            "Write the script with these sections:\n"
            "1. HOOK_TEXT (0-3s): Bold text that creates curiosity. Example: 'POV: You found THE product'\n"
            "2. FEATURE_1 (3-6s): First key feature as punchy text\n"
            "3. FEATURE_2 (6-9s): Second key feature\n"
            "4. PRICE_REVEAL (9-12s): Price or deal reveal with emphasis\n"
            "5. CTA_TEXT (12-15s): 'Link in bio' or 'Comment LINK'\n\n"
            "For each section provide:\n"
            "- text: The on-screen text (MAX 8 words per screen)\n"
            "- visual: Background visual description\n"
            "- transition: Transition style (cut, zoom, swipe)\n\n"
            "Also provide: caption, hashtags (array), music_mood\n"
            "Return as JSON."
        ),
    },
    "before_after": {
        "name": "Before/After Transformation",
        "description": "Split screen or transition showing problem state vs product solution.",
        "duration": 20,
        "sections": ["before_hook", "before_state", "transition", "after_state", "cta"],
        "prompt_template": (
            "Create a TikTok video script for a before/after transformation video.\n"
            "Product: {product_name}\n"
            "Niche: {niche}\n"
            "Description: {description}\n\n"
            "The video is {duration}s showing dramatic before/after with the product.\n"
            "NO FACE shown. Use hands-only POV, product close-ups, or screen recordings.\n\n"
            "Write the script with these sections:\n"
            "1. BEFORE_HOOK (0-3s): 'Watch this transformation' or similar hook\n"
            "2. BEFORE_STATE (3-8s): Show the problem/mess/struggle\n"
            "3. TRANSITION (8-10s): Dramatic reveal transition (zoom, swipe, flash)\n"
            "4. AFTER_STATE (10-17s): Show the amazing result with the product\n"
            "5. CTA (17-20s): Call to action with product link reference\n\n"
            "For each section provide: voiceover (optional), visual, text_overlay\n"
            "Also provide: caption, hashtags (array), music_mood\n"
            "Return as JSON."
        ),
    },
    "listicle_topn": {
        "name": "Top N Listicle",
        "description": "'Top 5 reasons...' countdown format. Text-heavy, engaging.",
        "duration": 30,
        "sections": ["hook", "reason_5", "reason_4", "reason_3", "reason_2", "reason_1", "cta"],
        "prompt_template": (
            "Create a TikTok video script for a 'Top 5' listicle countdown.\n"
            "Product: {product_name}\n"
            "Niche: {niche}\n"
            "Description: {description}\n\n"
            "The video is {duration}s as a countdown: 5 reasons to buy/try this product.\n"
            "NO FACE shown. Use text overlays, product shots, and stock footage.\n\n"
            "Write the script with these sections:\n"
            "1. HOOK (0-3s): 'Top 5 reasons you NEED this' or similar\n"
            "2-6. REASON_5 through REASON_1 (3-27s): Each reason ~4s, building excitement\n"
            "   - Number 1 should be the most compelling\n"
            "7. CTA (27-30s): 'Link in bio' with urgency\n\n"
            "For each section provide: text (on screen), voiceover, visual\n"
            "Also provide: caption, hashtags (array), music_mood\n"
            "Return as JSON."
        ),
    },
    "problem_solution": {
        "name": "Problem/Solution",
        "description": "Hook with relatable pain point, product as the hero solution.",
        "duration": 25,
        "sections": ["hook", "problem_1", "problem_2", "solution_reveal", "demo", "cta"],
        "prompt_template": (
            "Create a TikTok video script for a problem/solution style video.\n"
            "Product: {product_name}\n"
            "Niche: {niche}\n"
            "Description: {description}\n\n"
            "The video is {duration}s. Start with a relatable problem, then reveal the product.\n"
            "NO FACE shown. Hands-only POV, screen recordings, or product demonstrations.\n\n"
            "Write the script with these sections:\n"
            "1. HOOK (0-3s): Relatable frustration. 'Tired of [problem]?'\n"
            "2. PROBLEM_1 (3-8s): Show the problem visually\n"
            "3. PROBLEM_2 (8-12s): Make it worse. 'And it gets worse...'\n"
            "4. SOLUTION_REVEAL (12-17s): 'Until I found THIS' — product reveal\n"
            "5. DEMO (17-22s): Quick product demonstration showing it works\n"
            "6. CTA (22-25s): Call to action\n\n"
            "For each section provide: voiceover, visual, text_overlay\n"
            "Also provide: caption, hashtags (array), music_mood\n"
            "Return as JSON."
        ),
    },
}


class TikTokVideoService:
    """Faceless video script generation and content pipeline management."""

    def _generate_id(self, prefix: str = "vs") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    # ============================================
    # TEMPLATES
    # ============================================

    def list_templates(self) -> List[VideoTemplateInfo]:
        """List all available faceless video templates."""
        return [
            VideoTemplateInfo(
                type=VideoTemplateType(key),
                name=tpl["name"],
                description=tpl["description"],
                duration=tpl["duration"],
                sections=tpl["sections"],
            )
            for key, tpl in FACELESS_TEMPLATES.items()
        ]

    # ============================================
    # SCRIPT GENERATION
    # ============================================

    async def generate_video_script(
        self,
        product_id: str,
        template_type: VideoTemplateType = VideoTemplateType.VOICEOVER_BROLL,
    ) -> Optional[VideoScript]:
        """Generate a faceless video script for a product using LangChain."""
        # Load product
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            product = result.scalar_one_or_none()
            if not product:
                logger.warning("tiktok_video_product_not_found", product_id=product_id)
                return None

        template = FACELESS_TEMPLATES.get(template_type.value)
        if not template:
            logger.warning("tiktok_video_template_not_found", template_type=template_type)
            return None

        # Build prompt from template
        prompt = template["prompt_template"].format(
            product_name=product.name,
            niche=product.niche or "general",
            description=(product.description or "")[:500],
            duration=template["duration"],
        )

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = get_zero_chat_model(task_type="analysis", temperature=0.7)
            llm_response = await llm.ainvoke([
                SystemMessage(content=(
                    "You are a TikTok content creator specializing in faceless viral videos. "
                    "You create scripts that are engaging, scroll-stopping, and optimized for "
                    "the TikTok algorithm. Return ONLY valid JSON."
                )),
                HumanMessage(content=prompt),
            ])

            raw = llm_response.content if llm_response else ""
            script_data = self._parse_script_json(raw, template)

        except Exception as e:
            logger.error("tiktok_video_script_generation_failed", error=str(e))
            # Create a basic placeholder script
            script_data = {
                "hook_text": f"You NEED this {product.niche or ''} product!",
                "body_sections": [{"section": s, "text": f"[{s}] content needed"} for s in template["sections"]],
                "cta_text": "Link in bio!",
                "text_overlays": [],
                "voiceover_script": "",
                "caption": f"Must-have {product.niche or 'product'} find!",
                "hashtags": ["fyp", "tiktokshop", product.niche or "trending"],
            }

        # Store script
        script_id = self._generate_id()
        async with get_session() as session:
            row = VideoScriptModel(
                id=script_id,
                product_id=product_id,
                topic_id=product.linked_content_topic_id,
                template_type=template_type.value,
                hook_text=script_data.get("hook_text", ""),
                body_json=script_data.get("body_sections", []),
                cta_text=script_data.get("cta_text", ""),
                text_overlays=script_data.get("text_overlays", []),
                voiceover_script=script_data.get("voiceover_script", ""),
                duration_seconds=template["duration"],
                status="draft",
            )
            session.add(row)

        logger.info("tiktok_video_script_created", script_id=script_id, template=template_type.value)
        return await self.get_script(script_id)

    def _parse_script_json(self, raw: str, template: Dict) -> Dict[str, Any]:
        """Parse LLM output into script structure."""
        try:
            # Try to extract JSON from response
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
            else:
                data = json.loads(raw)

            sections = data.get("sections", [])
            hook_text = ""
            body_sections = []
            voiceover_parts = []

            for section in sections:
                if isinstance(section, dict):
                    name = section.get("section", section.get("name", ""))
                    if "hook" in name.lower():
                        hook_text = section.get("voiceover", section.get("text", ""))
                    body_sections.append(section)
                    vo = section.get("voiceover", "")
                    if vo:
                        voiceover_parts.append(vo)

            if not hook_text and body_sections:
                first = body_sections[0]
                hook_text = first.get("voiceover", first.get("text", ""))

            text_overlays = []
            for s in sections:
                if isinstance(s, dict):
                    overlay = s.get("text_overlay", s.get("text", ""))
                    if overlay:
                        text_overlays.append(overlay)

            return {
                "hook_text": hook_text,
                "body_sections": body_sections,
                "cta_text": data.get("caption", "Link in bio!"),
                "text_overlays": text_overlays,
                "voiceover_script": "\n".join(voiceover_parts),
                "caption": data.get("caption", ""),
                "hashtags": data.get("hashtags", []),
            }

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("tiktok_video_script_parse_failed", error=str(e))
            return {
                "hook_text": raw[:100] if raw else "",
                "body_sections": [{"raw": raw[:500]}] if raw else [],
                "cta_text": "Link in bio!",
                "text_overlays": [],
                "voiceover_script": raw[:500] if raw else "",
            }

    # ============================================
    # SCRIPT CRUD
    # ============================================

    async def list_scripts(
        self,
        product_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[VideoScript]:
        async with get_session() as session:
            query = select(VideoScriptModel).order_by(VideoScriptModel.created_at.desc())
            if product_id:
                query = query.where(VideoScriptModel.product_id == product_id)
            if status:
                query = query.where(VideoScriptModel.status == status)
            query = query.limit(limit)
            result = await session.execute(query)
            return [self._script_to_pydantic(r) for r in result.scalars().all()]

    async def get_script(self, script_id: str) -> Optional[VideoScript]:
        async with get_session() as session:
            result = await session.execute(
                select(VideoScriptModel).where(VideoScriptModel.id == script_id)
            )
            row = result.scalar_one_or_none()
            return self._script_to_pydantic(row) if row else None

    async def update_script(self, script_id: str, updates: VideoScriptUpdate) -> Optional[VideoScript]:
        async with get_session() as session:
            result = await session.execute(
                select(VideoScriptModel).where(VideoScriptModel.id == script_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            update_data = updates.model_dump(exclude_unset=True)
            if "status" in update_data and update_data["status"]:
                update_data["status"] = update_data["status"].value
            if "body_sections" in update_data:
                update_data["body_json"] = update_data.pop("body_sections")

            for key, value in update_data.items():
                if hasattr(row, key):
                    setattr(row, key, value)

            await session.flush()
            return self._script_to_pydantic(row)

    # ============================================
    # CONTENT QUEUE
    # ============================================

    async def queue_for_generation(self, script_id: str) -> Optional[ContentQueueItem]:
        """Send a script to AIContentTools for video generation."""
        script = await self.get_script(script_id)
        if not script:
            return None

        # Update script status
        await self.update_script(script_id, VideoScriptUpdate(status=VideoScriptStatus.QUEUED))

        # Create queue item
        queue_id = self._generate_id("cq")
        act_job_id = None

        try:
            from app.services.ai_content_tools_client import get_ai_content_tools_client
            client = get_ai_content_tools_client()

            # Build the generation prompt from script
            generation_prompt = self._build_generation_prompt(script)

            result = await client.generate_content(
                workflow_type="text_to_video",
                prompt=generation_prompt,
                caption=script.cta_text,
            )
            act_job_id = result.get("job_id") if result else None

        except Exception as e:
            logger.warning("tiktok_video_act_queue_failed", error=str(e))

        # Store queue item
        async with get_session() as session:
            row = ContentQueueModel(
                id=queue_id,
                script_id=script_id,
                product_id=script.product_id,
                generation_type="text_to_video",
                act_job_id=act_job_id,
                status="queued" if act_job_id else "failed",
                error_message=None if act_job_id else "AIContentTools unavailable",
            )
            session.add(row)

        return await self.get_queue_item(queue_id)

    async def check_generation_status(self, queue_id: str) -> Optional[ContentQueueItem]:
        """Check AIContentTools for generation completion."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
            )
            row = result.scalar_one_or_none()
            if not row or not row.act_job_id:
                return self._queue_to_pydantic(row) if row else None

            if row.status in ("completed", "failed"):
                return self._queue_to_pydantic(row)

            try:
                from app.services.ai_content_tools_client import get_ai_content_tools_client
                client = get_ai_content_tools_client()
                status = await client.get_job_status(row.act_job_id)

                if status and status.get("status") == "completed":
                    row.status = "completed"
                    row.act_generation_id = status.get("generation_id")
                    row.completed_at = datetime.now(timezone.utc)

                    # Update script status
                    script_result = await session.execute(
                        select(VideoScriptModel).where(VideoScriptModel.id == row.script_id)
                    )
                    script_row = script_result.scalar_one_or_none()
                    if script_row:
                        script_row.status = "generated"
                        script_row.generated_at = datetime.now(timezone.utc)

                elif status and status.get("status") == "failed":
                    row.status = "failed"
                    row.error_message = status.get("error", "Generation failed")

                elif status and status.get("status") in ("processing", "queued"):
                    row.status = "generating"

                await session.flush()

            except Exception as e:
                logger.warning("tiktok_video_status_check_failed", error=str(e))

            return self._queue_to_pydantic(row)

    async def get_queue_item(self, queue_id: str) -> Optional[ContentQueueItem]:
        async with get_session() as session:
            result = await session.execute(
                select(ContentQueueModel).where(ContentQueueModel.id == queue_id)
            )
            row = result.scalar_one_or_none()
            return self._queue_to_pydantic(row) if row else None

    async def list_content_queue(
        self, status: Optional[str] = None, limit: int = 50
    ) -> List[ContentQueueItem]:
        async with get_session() as session:
            query = select(ContentQueueModel).order_by(ContentQueueModel.created_at.desc())
            if status:
                query = query.where(ContentQueueModel.status == status)
            query = query.limit(limit)
            result = await session.execute(query)
            return [self._queue_to_pydantic(r) for r in result.scalars().all()]

    async def get_queue_stats(self) -> ContentQueueStats:
        async with get_session() as session:
            queued = await session.execute(
                select(sql_func.count()).select_from(ContentQueueModel).where(
                    ContentQueueModel.status == "queued"
                )
            )
            generating = await session.execute(
                select(sql_func.count()).select_from(ContentQueueModel).where(
                    ContentQueueModel.status == "generating"
                )
            )
            completed = await session.execute(
                select(sql_func.count()).select_from(ContentQueueModel).where(
                    ContentQueueModel.status == "completed"
                )
            )
            failed = await session.execute(
                select(sql_func.count()).select_from(ContentQueueModel).where(
                    ContentQueueModel.status == "failed"
                )
            )
            total_scripts = await session.execute(
                select(sql_func.count()).select_from(VideoScriptModel)
            )

            # Scripts by template
            tpl_result = await session.execute(
                select(VideoScriptModel.template_type, sql_func.count().label("cnt"))
                .group_by(VideoScriptModel.template_type)
            )
            scripts_by_template = {r[0]: r[1] for r in tpl_result.all()}

            return ContentQueueStats(
                total_queued=queued.scalar() or 0,
                generating=generating.scalar() or 0,
                completed=completed.scalar() or 0,
                failed=failed.scalar() or 0,
                total_scripts=total_scripts.scalar() or 0,
                scripts_by_template=scripts_by_template,
            )

    # ============================================
    # HELPERS
    # ============================================

    def _build_generation_prompt(self, script: VideoScript) -> str:
        """Build the prompt to send to AIContentTools from a video script."""
        parts = [f"Create a faceless TikTok video ({script.duration_seconds}s):"]
        parts.append(f"\nHook: {script.hook_text}")

        if script.voiceover_script:
            parts.append(f"\nVoiceover:\n{script.voiceover_script}")

        if script.text_overlays:
            parts.append(f"\nText overlays: {', '.join(script.text_overlays)}")

        parts.append(f"\nCTA: {script.cta_text}")
        parts.append("\nStyle: Faceless, no person on camera. Use product shots, B-roll, text overlays.")

        return "\n".join(parts)

    def _script_to_pydantic(self, row: VideoScriptModel) -> VideoScript:
        return VideoScript(
            id=row.id,
            product_id=row.product_id,
            topic_id=row.topic_id,
            template_type=row.template_type,
            hook_text=row.hook_text or "",
            body_sections=row.body_json or [],
            cta_text=row.cta_text or "",
            text_overlays=row.text_overlays or [],
            voiceover_script=row.voiceover_script or "",
            duration_seconds=row.duration_seconds or 30,
            status=row.status or "draft",
            created_at=row.created_at or datetime.utcnow(),
            generated_at=row.generated_at,
        )

    def _queue_to_pydantic(self, row: ContentQueueModel) -> ContentQueueItem:
        return ContentQueueItem(
            id=row.id,
            script_id=row.script_id,
            product_id=row.product_id,
            generation_type=row.generation_type or "text_to_video",
            act_job_id=row.act_job_id,
            act_generation_id=row.act_generation_id,
            status=row.status or "queued",
            error_message=row.error_message,
            created_at=row.created_at or datetime.utcnow(),
            completed_at=row.completed_at,
        )


@lru_cache()
def get_tiktok_video_service() -> TikTokVideoService:
    """Get cached TikTok Video service instance."""
    return TikTokVideoService()
