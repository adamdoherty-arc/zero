"""
Content Agent Service.

Manages content topics with curated examples, LLM-generated rules that improve
over time, and orchestrates AIContentTools for content generation/publishing.
Integrates with Legion for content production tasks and AIContentTools improvement tasks.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog
import uuid

from sqlalchemy import select, update, delete, func as sql_func

from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings
from app.db.models import (
    ContentTopicModel, ContentExampleModel, ContentPerformanceModel,
    ServiceConfigModel,
)
from app.models.content_agent import (
    ContentTopic, ContentTopicCreate, ContentTopicUpdate,
    ContentTopicStatus, ContentExample, ContentExampleCreate,
    ContentGenerateRequest, ContentGenerateResponse,
    ContentPerformanceRecord, ContentAgentStats,
    RuleGenerateRequest, RuleUpdateRequest,
)
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()

ZERO_PROJECT_ID = get_settings().zero_legion_project_id

RULE_GENERATION_SYSTEM_PROMPT = """You are a content strategist analyzing high-performing social media content.
Extract actionable rules from the provided examples. Each rule should be specific and measurable.
Focus on: hooks, captions, formats, hashtag patterns, posting strategies, and engagement techniques.
Return ONLY a JSON array of objects with keys: id, text, source, effectiveness_score.
Set source to "llm" and effectiveness_score to 50.0 for new rules."""

IMPROVEMENT_SYSTEM_PROMPT = """You are a content performance analyst.
Analyze which content rules led to high or low engagement.
Suggest rule modifications based on performance data.
Return ONLY valid JSON."""


class ContentAgentService:
    """Content Agent: manages topics, examples, rules, and AIContentTools orchestration."""

    def _generate_id(self, prefix: str = "ct") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    # ============================================
    # TOPIC MANAGEMENT
    # ============================================

    async def list_topics(
        self,
        status: Optional[str] = None,
        niche: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 50,
    ) -> List[ContentTopic]:
        async with get_session() as session:
            query = select(ContentTopicModel).order_by(
                ContentTopicModel.avg_performance_score.desc()
            )
            if status:
                query = query.where(ContentTopicModel.status == status)
            if niche:
                query = query.where(ContentTopicModel.niche == niche)
            if platform:
                query = query.where(ContentTopicModel.platform == platform)
            query = query.limit(limit)

            result = await session.execute(query)
            rows = result.scalars().all()
            return [self._topic_to_pydantic(r) for r in rows]

    async def get_topic(self, topic_id: str) -> Optional[ContentTopic]:
        async with get_session() as session:
            result = await session.execute(
                select(ContentTopicModel).where(ContentTopicModel.id == topic_id)
            )
            row = result.scalar_one_or_none()
            return self._topic_to_pydantic(row) if row else None

    async def create_topic(self, data: ContentTopicCreate) -> ContentTopic:
        topic_id = self._generate_id()
        async with get_session() as session:
            row = ContentTopicModel(
                id=topic_id,
                name=data.name,
                description=data.description,
                niche=data.niche,
                platform=data.platform,
                tiktok_product_id=data.tiktok_product_id,
                content_style=data.content_style.value if data.content_style else None,
                target_audience=data.target_audience,
                tone_guidelines=data.tone_guidelines,
                hashtag_strategy=data.hashtag_strategy or [],
                rules=[],
            )
            session.add(row)
            return self._topic_to_pydantic(row)

    async def update_topic(
        self, topic_id: str, updates: ContentTopicUpdate
    ) -> Optional[ContentTopic]:
        async with get_session() as session:
            result = await session.execute(
                select(ContentTopicModel).where(ContentTopicModel.id == topic_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            update_data = updates.model_dump(exclude_unset=True)
            if "status" in update_data and update_data["status"]:
                update_data["status"] = update_data["status"].value
            if "content_style" in update_data and update_data["content_style"]:
                update_data["content_style"] = update_data["content_style"].value

            for key, value in update_data.items():
                setattr(row, key, value)

            return self._topic_to_pydantic(row)

    async def delete_topic(self, topic_id: str) -> bool:
        async with get_session() as session:
            result = await session.execute(
                delete(ContentTopicModel).where(ContentTopicModel.id == topic_id)
            )
            return result.rowcount > 0

    # ============================================
    # EXAMPLE MANAGEMENT
    # ============================================

    async def list_examples(
        self, topic_id: str, limit: int = 50
    ) -> List[ContentExample]:
        async with get_session() as session:
            result = await session.execute(
                select(ContentExampleModel)
                .where(ContentExampleModel.topic_id == topic_id)
                .order_by(ContentExampleModel.performance_score.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [self._example_to_pydantic(r) for r in rows]

    async def add_example(self, data: ContentExampleCreate) -> ContentExample:
        example_id = self._generate_id("ce")

        # Compute performance score from engagement metrics
        perf_score = self._compute_example_performance(
            views=data.views, likes=data.likes,
            comments=data.comments, shares=data.shares,
        )

        async with get_session() as session:
            row = ContentExampleModel(
                id=example_id,
                topic_id=data.topic_id,
                title=data.title,
                caption=data.caption,
                script=data.script,
                url=data.url,
                platform=data.platform,
                views=data.views,
                likes=data.likes,
                comments=data.comments,
                shares=data.shares,
                performance_score=perf_score,
                source=data.source,
            )
            session.add(row)

            # Update topic example count
            topic_result = await session.execute(
                select(ContentTopicModel).where(ContentTopicModel.id == data.topic_id)
            )
            topic = topic_result.scalar_one_or_none()
            if topic:
                topic.examples_count = (topic.examples_count or 0) + 1

            # Generate embedding
            try:
                from app.infrastructure.ollama_client import get_ollama_client
                client = get_ollama_client()
                embed_text = " ".join(filter(None, [data.title, data.caption, data.script]))
                if embed_text:
                    embedding = await client.embed_safe(embed_text)
                    if embedding:
                        row.embedding = embedding
            except Exception:
                pass

            return self._example_to_pydantic(row)

    async def delete_example(self, example_id: str) -> bool:
        async with get_session() as session:
            # Get topic_id before deletion
            result = await session.execute(
                select(ContentExampleModel).where(ContentExampleModel.id == example_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return False

            topic_id = row.topic_id
            await session.execute(
                delete(ContentExampleModel).where(ContentExampleModel.id == example_id)
            )

            # Update topic example count
            topic_result = await session.execute(
                select(ContentTopicModel).where(ContentTopicModel.id == topic_id)
            )
            topic = topic_result.scalar_one_or_none()
            if topic and topic.examples_count > 0:
                topic.examples_count -= 1

            return True

    def _compute_example_performance(
        self, views: Optional[int], likes: Optional[int],
        comments: Optional[int], shares: Optional[int],
    ) -> float:
        """Compute a performance score from engagement metrics."""
        if not views or views == 0:
            return 50.0

        engagement = (
            (likes or 0) * 1.0
            + (comments or 0) * 3.0
            + (shares or 0) * 5.0
        )
        rate = engagement / views
        # Normalize: 0.05 engagement rate = 50, 0.15 = 80, 0.30+ = 95
        score = min(95, 30 + rate * 300)
        return round(max(10, score), 1)

    # ============================================
    # RULE ENGINE
    # ============================================

    async def generate_rules(
        self, topic_id: str, focus: Optional[str] = None
    ) -> List[dict]:
        """Generate content rules from top-performing examples using LLM."""
        topic = await self.get_topic(topic_id)
        if not topic:
            return []

        # Load top examples
        examples = await self.list_examples(topic_id, limit=20)
        if not examples:
            logger.info("no_examples_for_rules", topic_id=topic_id)
            return topic.rules

        # Build prompt
        examples_text = ""
        for i, ex in enumerate(examples[:10], 1):
            parts = []
            if ex.caption:
                parts.append(f"Caption: {ex.caption[:200]}")
            if ex.script:
                parts.append(f"Script: {ex.script[:300]}")
            if ex.title:
                parts.append(f"Title: {ex.title[:100]}")
            parts.append(f"Performance: {ex.performance_score:.0f}/100")
            examples_text += f"\nExample {i}:\n" + "\n".join(parts) + "\n"

        existing_rules_text = ""
        user_rules = [r for r in topic.rules if r.get("source") == "user"]
        if user_rules:
            existing_rules_text = "\n\nUser-defined rules to preserve:\n"
            for r in user_rules:
                existing_rules_text += f"- {r['text']}\n"

        focus_text = f"\nFocus area: {focus}" if focus else ""

        prompt = (
            f"Content topic: {topic.name}\n"
            f"Niche: {topic.niche}\n"
            f"Platform: {topic.platform}\n"
            f"Style: {topic.content_style or 'mixed'}\n"
            f"{focus_text}\n\n"
            f"Top-performing content examples:\n{examples_text}"
            f"{existing_rules_text}\n\n"
            f"Extract 5-10 actionable content rules from these examples.\n"
            f"Return ONLY a JSON array."
        )

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from app.infrastructure.langchain_adapter import get_zero_chat_model

            llm = get_zero_chat_model(task_type="analysis", temperature=0.3)
            llm_response = await llm.ainvoke([
                SystemMessage(content=RULE_GENERATION_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            result = llm_response.content if llm_response else None

            if result:
                try:
                    new_rules = json.loads(result)
                    if isinstance(new_rules, list):
                        # Ensure each rule has required fields
                        for rule in new_rules:
                            if "id" not in rule:
                                rule["id"] = self._generate_id("rule")
                            if "source" not in rule:
                                rule["source"] = "llm"
                            if "effectiveness_score" not in rule:
                                rule["effectiveness_score"] = 50.0
                            if "times_applied" not in rule:
                                rule["times_applied"] = 0

                        # Merge: keep user rules, replace LLM rules
                        merged = list(user_rules) + new_rules

                        # Store back
                        async with get_session() as session:
                            db_result = await session.execute(
                                select(ContentTopicModel).where(
                                    ContentTopicModel.id == topic_id
                                )
                            )
                            row = db_result.scalar_one_or_none()
                            if row:
                                row.rules = merged

                        logger.info("rules_generated", topic_id=topic_id, count=len(new_rules))
                        return merged

                except json.JSONDecodeError:
                    logger.warning("rules_json_parse_fail", topic_id=topic_id)

        except Exception as e:
            logger.error("rules_generation_failed", topic_id=topic_id, error=str(e))

        return topic.rules

    async def update_rule(self, req: RuleUpdateRequest) -> Optional[ContentTopic]:
        """User edits a specific rule text. Marks source as 'user'."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentTopicModel).where(ContentTopicModel.id == req.topic_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            rules = list(row.rules or [])
            for rule in rules:
                if rule.get("id") == req.rule_id:
                    rule["text"] = req.text
                    rule["source"] = "user"
                    break
            else:
                return None

            row.rules = rules
            return self._topic_to_pydantic(row)

    async def delete_rule(self, topic_id: str, rule_id: str) -> Optional[ContentTopic]:
        """Delete a rule from a topic."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentTopicModel).where(ContentTopicModel.id == topic_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            rules = [r for r in (row.rules or []) if r.get("id") != rule_id]
            row.rules = rules
            return self._topic_to_pydantic(row)

    # ============================================
    # CONTENT GENERATION (via AIContentTools)
    # ============================================

    async def generate_content(
        self, req: ContentGenerateRequest
    ) -> ContentGenerateResponse:
        """Generate content via AIContentTools."""
        topic = await self.get_topic(req.topic_id)
        if not topic:
            return ContentGenerateResponse(topic_id=req.topic_id, status="error_topic_not_found")

        from app.services.ai_content_tools_client import get_ai_content_tools_client
        act = get_ai_content_tools_client()

        # Build prompt from rules + topic info
        rules_text = "\n".join(
            f"- {r['text']}" for r in topic.rules if r.get("text")
        ) or "No specific rules yet."

        prompt = (
            f"Create {req.content_type} content for: {topic.name}\n"
            f"Niche: {topic.niche}\n"
            f"Platform: {topic.platform}\n"
            f"Style: {topic.content_style or 'mixed'}\n"
            f"Target audience: {topic.target_audience or 'general'}\n"
            f"Tone: {topic.tone_guidelines or 'engaging and authentic'}\n\n"
            f"Content rules to follow:\n{rules_text}"
        )
        if req.extra_prompt:
            prompt += f"\n\nAdditional instructions: {req.extra_prompt}"

        job_ids = []
        gen_ids = []
        rule_ids = [r.get("id", "") for r in topic.rules if r.get("text")]

        for _ in range(req.count):
            try:
                result = await act.generate_content(
                    workflow_type="text_to_image" if req.content_type == "image" else "full_production",
                    prompt=prompt,
                    persona_id=req.persona_id,
                    caption=f"#{' #'.join(topic.hashtag_strategy[:5])}" if topic.hashtag_strategy else None,
                    hashtags=topic.hashtag_strategy,
                )
                if result:
                    job_id = result.get("job_id") or result.get("id", "")
                    gen_id = result.get("generation_id") or job_id
                    job_ids.append(job_id)
                    gen_ids.append(gen_id)

                    # Store performance record
                    perf_id = self._generate_id("cp")
                    async with get_session() as session:
                        session.add(ContentPerformanceModel(
                            id=perf_id,
                            topic_id=topic.id,
                            tiktok_product_id=topic.tiktok_product_id,
                            act_generation_id=gen_id,
                            act_persona_id=req.persona_id,
                            platform=topic.platform,
                            content_type=req.content_type,
                            rules_applied=rule_ids,
                        ))

            except Exception as e:
                logger.error("content_generation_failed", error=str(e))

        # Update generated count
        async with get_session() as session:
            result = await session.execute(
                select(ContentTopicModel).where(ContentTopicModel.id == topic.id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.content_generated_count = (row.content_generated_count or 0) + len(job_ids)

        return ContentGenerateResponse(
            job_ids=job_ids,
            act_generation_ids=gen_ids,
            topic_id=topic.id,
            status="queued" if job_ids else "no_jobs_created",
        )

    # ============================================
    # PERFORMANCE SYNC
    # ============================================

    async def sync_performance_metrics(self, topic_id: Optional[str] = None) -> int:
        """Sync performance metrics from AIContentTools."""
        from app.services.ai_content_tools_client import get_ai_content_tools_client
        act = get_ai_content_tools_client()

        updated = 0
        async with get_session() as session:
            query = select(ContentPerformanceModel).where(
                ContentPerformanceModel.feedback_processed == False  # noqa: E712
            )
            if topic_id:
                query = query.where(ContentPerformanceModel.topic_id == topic_id)
            query = query.limit(100)

            result = await session.execute(query)
            records = result.scalars().all()

            for record in records:
                if not record.act_generation_id:
                    continue
                try:
                    perf_data = await act.get_performance(
                        generation_id=record.act_generation_id
                    )
                    if perf_data and isinstance(perf_data, list) and len(perf_data) > 0:
                        p = perf_data[0]
                        record.views = p.get("views", 0)
                        record.likes = p.get("likes", 0)
                        record.comments = p.get("comments", 0)
                        record.shares = p.get("shares", 0)
                        record.saves = p.get("saves", 0)

                        total_eng = record.likes + record.comments * 3 + record.shares * 5
                        record.engagement_rate = (total_eng / record.views * 100) if record.views else 0
                        record.performance_score = min(95, 30 + record.engagement_rate * 5)
                        record.synced_at = datetime.now(timezone.utc)
                        updated += 1
                except Exception as e:
                    logger.debug("perf_sync_skip", gen_id=record.act_generation_id, error=str(e))

        logger.info("content_perf_synced", updated=updated)
        return updated

    # ============================================
    # SELF-IMPROVEMENT LOOP
    # ============================================

    async def run_improvement_cycle(self, topic_id: Optional[str] = None) -> Dict[str, Any]:
        """Run the self-improvement cycle for content rules."""
        topics = []
        if topic_id:
            topic = await self.get_topic(topic_id)
            if topic:
                topics = [topic]
        else:
            topics = await self.list_topics(status="active")

        results = {
            "topics_processed": 0,
            "rules_updated": 0,
            "rules_regenerated": 0,
            "performance_synced": 0,
        }

        for topic in topics:
            try:
                # 1. Sync performance
                synced = await self.sync_performance_metrics(topic.id)
                results["performance_synced"] += synced

                # 2. Load unprocessed performance records
                async with get_session() as session:
                    perf_result = await session.execute(
                        select(ContentPerformanceModel)
                        .where(ContentPerformanceModel.topic_id == topic.id)
                        .where(ContentPerformanceModel.feedback_processed == False)  # noqa: E712
                        .where(ContentPerformanceModel.views > 0)
                    )
                    perf_records = perf_result.scalars().all()

                if not perf_records:
                    continue

                # 3. Update rule effectiveness
                topic_obj = await self.get_topic(topic.id)
                if not topic_obj:
                    continue

                rules = list(topic_obj.rules or [])
                for rule in rules:
                    rule_id = rule.get("id", "")
                    scores_for_rule = []
                    for pr in perf_records:
                        if rule_id in (pr.rules_applied or []):
                            scores_for_rule.append(pr.performance_score)

                    if scores_for_rule:
                        avg_perf = sum(scores_for_rule) / len(scores_for_rule)
                        # Exponential moving average
                        old_eff = rule.get("effectiveness_score", 50.0)
                        rule["effectiveness_score"] = round(old_eff * 0.6 + avg_perf * 0.4, 1)
                        rule["times_applied"] = rule.get("times_applied", 0) + len(scores_for_rule)
                        results["rules_updated"] += 1

                # 4. Regenerate rules if any are underperforming
                weak_rules = [r for r in rules if r.get("effectiveness_score", 50) < 30]
                if weak_rules:
                    await self.generate_rules(topic.id, focus="replace underperforming rules")
                    results["rules_regenerated"] += 1
                else:
                    # Store updated effectiveness scores
                    async with get_session() as session:
                        db_result = await session.execute(
                            select(ContentTopicModel).where(
                                ContentTopicModel.id == topic.id
                            )
                        )
                        row = db_result.scalar_one_or_none()
                        if row:
                            row.rules = rules

                # 5. Mark feedback processed
                async with get_session() as session:
                    await session.execute(
                        update(ContentPerformanceModel)
                        .where(ContentPerformanceModel.topic_id == topic.id)
                        .where(ContentPerformanceModel.feedback_processed == False)  # noqa: E712
                        .values(feedback_processed=True)
                    )

                # 6. Update avg performance score
                async with get_session() as session:
                    avg_result = await session.execute(
                        select(sql_func.avg(ContentPerformanceModel.performance_score))
                        .where(ContentPerformanceModel.topic_id == topic.id)
                        .where(ContentPerformanceModel.views > 0)
                    )
                    avg_score = avg_result.scalar() or 0
                    topic_result = await session.execute(
                        select(ContentTopicModel).where(ContentTopicModel.id == topic.id)
                    )
                    row = topic_result.scalar_one_or_none()
                    if row:
                        row.avg_performance_score = round(avg_score, 1)

                results["topics_processed"] += 1

            except Exception as e:
                logger.error("improvement_cycle_failed", topic_id=topic.id, error=str(e))

        logger.info("content_improvement_cycle_complete", **results)
        return results

    async def research_content_trends(self, topic_id: str) -> Dict[str, Any]:
        """Research trending content for a topic using SearXNG + LLM."""
        topic = await self.get_topic(topic_id)
        if not topic:
            return {"error": "Topic not found"}

        searxng = get_searxng_service()
        queries = [
            f"tiktok {topic.niche} content trends 2026",
            f"viral {topic.niche} tiktok videos hooks",
            f"best {topic.niche} tiktok content format",
        ]

        all_results = []
        for query in queries:
            try:
                results = await searxng.search(query, num_results=5)
                all_results.extend(results)
            except Exception:
                pass

        if not all_results:
            return {"trends": [], "examples_added": 0}

        # LLM analysis of trends
        snippets = "\n".join(
            f"- {r.title}: {r.snippet[:200]}" for r in all_results[:10]
            if hasattr(r, "title") and hasattr(r, "snippet")
        )

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from app.infrastructure.langchain_adapter import get_zero_chat_model

            llm = get_zero_chat_model(task_type="analysis", temperature=0.3)
            llm_response = await llm.ainvoke([
                SystemMessage(content="You are a TikTok content trend analyst. Be concise."),
                HumanMessage(content=(
                    f"Analyze these content trends for {topic.niche} TikTok:\n{snippets}\n\n"
                    f"What hooks, formats, and strategies are trending? "
                    f"Return a brief summary."
                )),
            ])
            analysis = llm_response.content if llm_response else None
        except Exception:
            analysis = None

        # Add top results as scraped examples
        examples_added = 0
        for r in all_results[:3]:
            try:
                await self.add_example(ContentExampleCreate(
                    topic_id=topic_id,
                    title=r.title if hasattr(r, "title") else "",
                    caption=r.snippet[:500] if hasattr(r, "snippet") else "",
                    url=r.url if hasattr(r, "url") else "",
                    platform=topic.platform,
                    source="scraped",
                ))
                examples_added += 1
            except Exception:
                pass

        return {
            "topic": topic.name,
            "trends_found": len(all_results),
            "examples_added": examples_added,
            "analysis": analysis,
        }

    async def run_competitor_analysis(self, topic_id: str) -> Dict[str, Any]:
        """Run competitor analysis for a content topic."""
        topic = await self.get_topic(topic_id)
        if not topic:
            return {"error": "Topic not found"}

        searxng = get_searxng_service()
        product_name = topic.name.replace("TikTok: ", "")

        results = await searxng.research_topic(
            f"top tiktok {topic.niche} content creators {product_name}",
            aspects=["popular creators", "content formats", "engagement strategies",
                     "caption styles", "hashtag strategies"],
        )

        # LLM analysis
        formatted = searxng.format_research_for_llm(results)
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from app.infrastructure.langchain_adapter import get_zero_chat_model

            llm = get_zero_chat_model(task_type="analysis", temperature=0.3)
            llm_response = await llm.ainvoke([
                SystemMessage(content="You are a competitive content analyst. Be specific and actionable."),
                HumanMessage(content=(
                    f"Analyze competitor content for {topic.name}:\n{formatted}\n\n"
                    f"What can we learn from successful competitors? "
                    f"Focus on hooks, formats, and engagement tactics."
                )),
            ])
            analysis = llm_response.content if llm_response else None
        except Exception:
            analysis = None

        return {
            "topic": topic.name,
            "competitors_analyzed": len(results.get("all_results", [])),
            "analysis": analysis,
        }

    # ============================================
    # LEGION INTEGRATION
    # ============================================

    async def create_legion_content_task(
        self, topic_id: str, task_type: str = "review_generated"
    ) -> Dict[str, Any]:
        """Create a Legion task for content work."""
        topic = await self.get_topic(topic_id)
        if not topic:
            return {"error": "Topic not found"}

        try:
            from app.services.legion_client import get_legion_client
            legion = get_legion_client()

            if not await legion.health_check():
                return {"error": "Legion unavailable"}

            sprint = await self._get_or_create_content_sprint(legion)
            if not sprint:
                return {"error": "Could not create sprint"}

            task_titles = {
                "review_generated": f"[Content] Review generated content for: {topic.name[:150]}",
                "create_content": f"[Content] Create new content for: {topic.name[:150]}",
                "improve_rules": f"[Content] Improve content rules for: {topic.name[:150]}",
            }

            task = await legion.create_task(sprint["id"], {
                "title": task_titles.get(task_type, f"[Content] {topic.name[:200]}"),
                "description": (
                    f"Topic: {topic.name}\n"
                    f"Niche: {topic.niche}\n"
                    f"Platform: {topic.platform}\n"
                    f"Rules: {len(topic.rules)}\n"
                    f"Examples: {topic.examples_count}"
                ),
                "prompt": f"Work on content for topic '{topic.name}' in the {topic.niche} niche.",
                "priority": 3,
            })
            return task or {"error": "Task creation failed"}
        except Exception as e:
            return {"error": str(e)}

    async def create_legion_improvement_task(
        self, feature_desc: str
    ) -> Dict[str, Any]:
        """Create a Legion task to improve AIContentTools."""
        try:
            from app.services.legion_client import get_legion_client
            legion = get_legion_client()

            if not await legion.health_check():
                return {"error": "Legion unavailable"}

            sprint = await self._get_or_create_act_improvement_sprint(legion)
            if not sprint:
                return {"error": "Could not create sprint"}

            task = await legion.create_task(sprint["id"], {
                "title": f"[ACT Improvement] {feature_desc[:200]}",
                "description": f"Improvement for AIContentTools: {feature_desc}",
                "prompt": f"Implement this improvement in AIContentTools: {feature_desc}",
                "priority": 3,
            })
            return task or {"error": "Task creation failed"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_or_create_content_sprint(self, legion) -> Optional[Dict]:
        try:
            sprints = await legion.list_sprints()
            if isinstance(sprints, list):
                for s in sprints:
                    if "content" in s.get("name", "").lower() and s.get("status") in ("active", "planned"):
                        return s

            today = datetime.now().strftime("%Y-%m-%d")
            return await legion.create_sprint({
                "project_id": ZERO_PROJECT_ID,
                "name": f"Content Production - {today}",
                "status": "planned",
            })
        except Exception as e:
            logger.error("content_sprint_creation_failed", error=str(e))
            return None

    async def _get_or_create_act_improvement_sprint(self, legion) -> Optional[Dict]:
        try:
            sprints = await legion.list_sprints()
            if isinstance(sprints, list):
                for s in sprints:
                    if "aicontenttools" in s.get("name", "").lower() and s.get("status") in ("active", "planned"):
                        return s

            today = datetime.now().strftime("%Y-%m-%d")
            return await legion.create_sprint({
                "project_id": ZERO_PROJECT_ID,
                "name": f"AIContentTools Improvements - {today}",
                "status": "planned",
            })
        except Exception as e:
            logger.error("act_improvement_sprint_failed", error=str(e))
            return None

    # ============================================
    # HELPERS
    # ============================================

    def _topic_to_pydantic(self, row: ContentTopicModel) -> ContentTopic:
        return ContentTopic(
            id=row.id,
            name=row.name,
            description=row.description,
            niche=row.niche or "general",
            platform=row.platform or "tiktok",
            tiktok_product_id=row.tiktok_product_id,
            rules=row.rules or [],
            content_style=row.content_style,
            target_audience=row.target_audience,
            tone_guidelines=row.tone_guidelines,
            hashtag_strategy=row.hashtag_strategy or [],
            status=row.status or "active",
            examples_count=row.examples_count or 0,
            avg_performance_score=row.avg_performance_score or 0.0,
            content_generated_count=row.content_generated_count or 0,
            created_at=row.created_at or datetime.utcnow(),
            updated_at=row.updated_at,
        )

    def _example_to_pydantic(self, row: ContentExampleModel) -> ContentExample:
        return ContentExample(
            id=row.id,
            topic_id=row.topic_id,
            title=row.title,
            caption=row.caption,
            script=row.script,
            url=row.url,
            platform=row.platform or "tiktok",
            views=row.views,
            likes=row.likes,
            comments=row.comments,
            shares=row.shares,
            performance_score=row.performance_score or 50.0,
            source=row.source or "manual",
            rule_contributions=row.rule_contributions or [],
            added_at=row.added_at or datetime.utcnow(),
        )

    # ============================================
    # STATS
    # ============================================

    async def get_stats(self) -> Dict[str, Any]:
        async with get_session() as session:
            total_topics = (await session.execute(
                select(sql_func.count()).select_from(ContentTopicModel)
            )).scalar() or 0

            active_topics = (await session.execute(
                select(sql_func.count()).select_from(ContentTopicModel)
                .where(ContentTopicModel.status == "active")
            )).scalar() or 0

            total_examples = (await session.execute(
                select(sql_func.count()).select_from(ContentExampleModel)
            )).scalar() or 0

            total_generated = (await session.execute(
                select(sql_func.sum(ContentTopicModel.content_generated_count))
            )).scalar() or 0

            avg_perf = (await session.execute(
                select(sql_func.avg(ContentPerformanceModel.performance_score))
                .where(ContentPerformanceModel.views > 0)
            )).scalar() or 0

            # Count total rules across all topics
            topics = (await session.execute(select(ContentTopicModel))).scalars().all()
            rules_count = sum(len(t.rules or []) for t in topics)

            # Top performing topic
            top_topic_row = (await session.execute(
                select(ContentTopicModel)
                .where(ContentTopicModel.avg_performance_score > 0)
                .order_by(ContentTopicModel.avg_performance_score.desc())
                .limit(1)
            )).scalar_one_or_none()

            # Platform breakdown
            by_platform = {}
            for t in topics:
                p = t.platform or "unknown"
                by_platform[p] = by_platform.get(p, 0) + 1

            return {
                "total_topics": total_topics,
                "active_topics": active_topics,
                "total_examples": total_examples,
                "total_generated": total_generated,
                "total_rules": rules_count,
                "avg_performance_score": round(avg_perf, 1),
                "top_performing_topic": top_topic_row.name if top_topic_row else None,
                "by_platform": by_platform,
            }


@lru_cache()
def get_content_agent_service() -> ContentAgentService:
    """Get cached Content Agent service instance."""
    return ContentAgentService()
