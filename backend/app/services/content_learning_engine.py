"""
Content Learning Engine for Zero Brain.

Content-specific learning that integrates with the existing content pipeline.
Tracks what works for TikTok/content creation, runs A/B experiments,
and feeds learnings back into content generation.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from functools import lru_cache

import structlog
from sqlalchemy import select, update, func as sql_func

from app.infrastructure.database import get_session
from app.db.models import (
    ContentPerformanceModel, ContentExperimentModel,
    ContentTopicModel, TikTokProductModel,
)
from app.models.brain import ContentExperiment

logger = structlog.get_logger(__name__)


class ContentLearningEngine:
    """Content-specific learning. Tracks what works and runs experiments."""

    def _gen_id(self, prefix: str = "ce") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    async def process_content_outcomes(self) -> Dict[str, Any]:
        """Process recent content performance data into brain outcomes.

        Called hourly by scheduler. Extracts learnings and stores as episodic memories.
        """
        try:
            from app.services.outcome_learning_service import get_outcome_learning_service
            from app.services.episodic_memory_service import get_episodic_memory_service

            outcome_svc = get_outcome_learning_service()
            memory_svc = get_episodic_memory_service()

            since = datetime.now(timezone.utc) - timedelta(hours=2)
            async with get_session() as session:
                query = (
                    select(ContentPerformanceModel)
                    .where(ContentPerformanceModel.synced_at >= since)
                    .order_by(ContentPerformanceModel.synced_at.desc())
                    .limit(50)
                )
                result = await session.execute(query)
                records = result.scalars().all()

            processed = 0
            for record in records:
                engagement = float(record.engagement_rate or 0)
                # Map engagement to 0-100 score
                score = min(100, engagement * 1000)  # 0.10 engagement = 100

                await outcome_svc.record_outcome(
                    domain="content",
                    action_type="content_published",
                    action_id=record.id,
                    strategy_used=record.content_type if hasattr(record, 'content_type') else "unknown",
                    actual_score=score,
                    metrics={
                        "engagement_rate": engagement,
                        "views": getattr(record, "views", 0),
                        "likes": getattr(record, "likes", 0),
                        "shares": getattr(record, "shares", 0),
                    },
                )
                processed += 1

            # Store summary as episodic memory
            if processed > 0:
                await memory_svc.store_direct(
                    content=f"Processed {processed} content performance records. "
                            f"Avg engagement: {sum(float(r.engagement_rate or 0) for r in records) / len(records):.4f}",
                    source_type="content_learning",
                    namespace="content",
                    importance=40,
                    tags=["content", "performance", "batch"],
                )

            logger.info("content_outcomes_processed", count=processed)
            return {"processed": processed}

        except (ValueError, KeyError, TypeError, ImportError) as e:
            logger.error("content_outcome_processing_failed", error=str(e))
            return {"processed": 0, "error": str(e)}

    async def register_prompt_evolution(
        self, carousel_id: str, original_prompt: str, ai_score: float
    ) -> Dict[str, Any]:
        """Register a carousel's prompt for evolution tracking.

        High-scoring prompts (>8.0) get marked as 'winning' templates.
        Low-scoring prompts (<5.0) get flagged for revision.
        """
        category = (
            "winning" if ai_score >= 8.0
            else "needs_revision" if ai_score < 5.0
            else "neutral"
        )
        logger.info(
            "prompt_evolution_registered",
            carousel_id=carousel_id,
            score=ai_score,
            category=category,
        )

        # Store as episodic memory if winning
        if category == "winning":
            try:
                from app.services.episodic_memory_service import get_episodic_memory_service
                memory_svc = get_episodic_memory_service()
                await memory_svc.store_direct(
                    content=f"Winning carousel prompt (score={ai_score:.1f}): {original_prompt[:500]}",
                    source_type="prompt_evolution",
                    namespace="content",
                    importance=70,
                    tags=["winning_prompt", "carousel", f"score_{int(ai_score)}"],
                )
            except (ValueError, KeyError, TypeError, ImportError) as e:
                logger.debug("prompt_evolution_memory_failed", error=str(e))

        return {"carousel_id": carousel_id, "category": category, "score": ai_score}

    async def get_product_performance_insights(self) -> Dict[str, Any]:
        """Which product categories perform best? Which template types?"""
        try:
            since = datetime.now(timezone.utc) - timedelta(days=30)
            async with get_session() as session:
                # Performance by content topic
                topic_q = (
                    select(
                        ContentTopicModel.niche,
                        sql_func.count(ContentPerformanceModel.id).label("count"),
                        sql_func.avg(ContentPerformanceModel.engagement_rate).label("avg_eng"),
                    )
                    .join(ContentTopicModel, ContentPerformanceModel.topic_id == ContentTopicModel.id, isouter=True)
                    .where(ContentPerformanceModel.synced_at >= since)
                    .group_by(ContentTopicModel.niche)
                    .order_by(sql_func.avg(ContentPerformanceModel.engagement_rate).desc())
                    .limit(10)
                )
                topic_result = await session.execute(topic_q)
                by_niche = [
                    {"niche": r.niche or "unknown", "count": r.count,
                     "avg_engagement": round(float(r.avg_eng or 0), 4)}
                    for r in topic_result.all()
                ]

            return {
                "by_niche": by_niche,
                "period_days": 30,
            }

        except (ValueError, KeyError, TypeError) as e:
            logger.error("product_insights_failed", error=str(e))
            return {"by_niche": [], "error": str(e)}

    async def get_content_strategy_leaderboard(self) -> List[Dict]:
        """Rank content strategies by avg performance."""
        try:
            from app.services.outcome_learning_service import get_outcome_learning_service
            svc = get_outcome_learning_service()
            metrics = await svc.get_strategy_metrics(domain="content", days=30)
            return [
                {
                    "strategy": m.strategy,
                    "uses": m.total_uses,
                    "win_rate": round(m.win_rate, 3),
                    "avg_score": round(m.avg_score, 2),
                }
                for m in metrics
            ]
        except (ValueError, KeyError, TypeError, ImportError) as e:
            logger.error("strategy_leaderboard_failed", error=str(e))
            return []

    async def run_content_experiment(
        self,
        experiment_type: str,
        hypothesis: str,
        control_config: Dict[str, Any],
        variant_config: Dict[str, Any],
        name: Optional[str] = None,
        sample_size_target: int = 10,
    ) -> ContentExperiment:
        """Start a content A/B test."""
        exp_id = self._gen_id("ce")
        now = datetime.now(timezone.utc)

        async with get_session() as session:
            model = ContentExperimentModel(
                id=exp_id,
                name=name or f"{experiment_type} experiment",
                hypothesis=hypothesis,
                experiment_type=experiment_type,
                control_config=control_config,
                variant_config=variant_config,
                status="active",
                sample_size_target=sample_size_target,
                control_results=[],
                variant_results=[],
                created_at=now,
            )
            session.add(model)
            await session.commit()

        logger.info("content_experiment_started",
                    id=exp_id, type=experiment_type, hypothesis=hypothesis[:100])

        return ContentExperiment(
            id=exp_id, name=name or f"{experiment_type} experiment",
            hypothesis=hypothesis, experiment_type=experiment_type,
            control_config=control_config, variant_config=variant_config,
            status="active", sample_size_target=sample_size_target,
            created_at=now,
        )

    async def check_experiments(self) -> List[Dict]:
        """Check active experiments for completion."""
        try:
            async with get_session() as session:
                query = select(ContentExperimentModel).where(
                    ContentExperimentModel.status == "active"
                )
                result = await session.execute(query)
                experiments = result.scalars().all()

            completed = []
            for exp in experiments:
                control_n = len(exp.control_results or [])
                variant_n = len(exp.variant_results or [])
                target = exp.sample_size_target or 10

                if control_n >= target and variant_n >= target:
                    # Enough data — determine winner
                    control_scores = [r.get("score", 0) for r in (exp.control_results or [])]
                    variant_scores = [r.get("score", 0) for r in (exp.variant_results or [])]

                    control_avg = sum(control_scores) / len(control_scores) if control_scores else 0
                    variant_avg = sum(variant_scores) / len(variant_scores) if variant_scores else 0

                    diff = variant_avg - control_avg
                    if abs(diff) < 5:
                        winner = "inconclusive"
                        conclusion = f"No significant difference (control: {control_avg:.1f}, variant: {variant_avg:.1f})"
                    elif diff > 0:
                        winner = "variant"
                        conclusion = f"Variant wins by {diff:.1f} points (variant: {variant_avg:.1f} vs control: {control_avg:.1f})"
                    else:
                        winner = "control"
                        conclusion = f"Control wins by {abs(diff):.1f} points (control: {control_avg:.1f} vs variant: {variant_avg:.1f})"

                    now = datetime.now(timezone.utc)
                    async with get_session() as session:
                        await session.execute(
                            update(ContentExperimentModel)
                            .where(ContentExperimentModel.id == exp.id)
                            .values(
                                status="completed",
                                winner=winner,
                                conclusion=conclusion,
                                completed_at=now,
                            )
                        )
                        await session.commit()

                    completed.append({
                        "id": exp.id, "name": exp.name,
                        "winner": winner, "conclusion": conclusion,
                    })

                    logger.info("content_experiment_completed",
                              id=exp.id, winner=winner)

            return completed

        except (ValueError, KeyError, TypeError) as e:
            logger.error("check_experiments_failed", error=str(e))
            return []

    async def get_experiments(
        self,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[ContentExperiment]:
        """List content experiments."""
        try:
            async with get_session() as session:
                query = select(ContentExperimentModel).order_by(
                    ContentExperimentModel.created_at.desc()
                ).limit(limit)
                if status:
                    query = query.where(ContentExperimentModel.status == status)

                result = await session.execute(query)
                rows = result.scalars().all()

                return [
                    ContentExperiment(
                        id=r.id, name=r.name, hypothesis=r.hypothesis,
                        experiment_type=r.experiment_type,
                        control_config=r.control_config,
                        variant_config=r.variant_config,
                        status=r.status,
                        sample_size_target=r.sample_size_target,
                        control_results=r.control_results or [],
                        variant_results=r.variant_results or [],
                        conclusion=r.conclusion,
                        winner=r.winner,
                        created_at=r.created_at,
                        completed_at=r.completed_at,
                    )
                    for r in rows
                ]
        except (ValueError, KeyError, TypeError) as e:
            logger.error("get_experiments_failed", error=str(e))
            return []

    async def get_posting_time_analysis(self) -> Dict[str, Any]:
        """Analyze content performance by hour to find optimal posting windows."""
        try:
            since = datetime.now(timezone.utc) - timedelta(days=30)
            async with get_session() as session:
                query = (
                    select(
                        sql_func.extract("hour", ContentPerformanceModel.synced_at).label("hour"),
                        sql_func.count().label("count"),
                        sql_func.avg(ContentPerformanceModel.engagement_rate).label("avg_eng"),
                    )
                    .where(ContentPerformanceModel.synced_at >= since)
                    .group_by(sql_func.extract("hour", ContentPerformanceModel.synced_at))
                    .order_by(sql_func.avg(ContentPerformanceModel.engagement_rate).desc())
                )
                result = await session.execute(query)
                by_hour = [
                    {"hour": int(r.hour), "count": r.count,
                     "avg_engagement": round(float(r.avg_eng or 0), 4)}
                    for r in result.all()
                ]

            return {"by_hour": by_hour, "period_days": 30}

        except (ValueError, KeyError, TypeError) as e:
            logger.error("posting_time_analysis_failed", error=str(e))
            return {"by_hour": [], "error": str(e)}

    async def count_active_experiments(self) -> int:
        """Count active experiments."""
        try:
            async with get_session() as session:
                q = select(sql_func.count(ContentExperimentModel.id)).where(
                    ContentExperimentModel.status == "active"
                )
                return (await session.execute(q)).scalar() or 0
        except (ValueError, KeyError, TypeError):
            return 0


@lru_cache()
def get_content_learning_engine() -> ContentLearningEngine:
    return ContentLearningEngine()
