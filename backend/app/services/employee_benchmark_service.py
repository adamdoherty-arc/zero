"""
Employee Benchmark Service for Zero Brain.

10-dimension scoring system for Zero as an autonomous employee.
Tracks performance over time and auto-spawns improvement cycles.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from functools import lru_cache

import structlog
from sqlalchemy import select, delete, func as sql_func

from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client
from app.db.models import (
    BenchmarkScoreModel, BenchmarkHistoryModel,
    ContentPerformanceModel, DeepResearchReportModel,
    AgentTaskModel, SchedulerAuditLogModel, LlmUsageModel,
    ExperimentModel, CouncilDecisionModel, ContentExperimentModel,
    EpisodicMemoryModel, NoteModel,
)
from app.models.brain import BenchmarkScore, BenchmarkSnapshot

logger = structlog.get_logger(__name__)

# Dimension definitions: name -> (weight, is_llm_evaluated)
DIMENSIONS = {
    "content_quality":          (0.15, False),
    "learning_velocity":        (0.15, False),
    "research_depth":           (0.12, True),
    "task_execution":           (0.12, False),
    "system_health":            (0.10, False),
    "experiment_rigor":         (0.10, False),
    "cost_efficiency":          (0.08, False),
    "communication_quality":    (0.08, True),
    "calibration_accuracy":     (0.05, False),
    "knowledge_growth":         (0.05, False),
}


class EmployeeBenchmarkService:
    """10-dimension scoring for Zero as an autonomous employee."""

    def _gen_id(self) -> str:
        return f"bs-{uuid.uuid4().hex[:12]}"

    async def run_benchmark(self) -> BenchmarkSnapshot:
        """Score all 10 dimensions, persist, return snapshot."""
        scores: Dict[str, BenchmarkScore] = {}
        now = datetime.now(timezone.utc)

        for dim, (weight, _) in DIMENSIONS.items():
            try:
                scorer = getattr(self, f"_score_{dim}")
                score, details = await scorer()
                scores[dim] = BenchmarkScore(
                    dimension=dim, score=score, weight=weight,
                    details=details, computed_at=now,
                )
            except Exception as e:
                logger.warning(f"benchmark_{dim}_failed", error=str(e))
                scores[dim] = BenchmarkScore(
                    dimension=dim, score=50.0, weight=weight,
                    details={"error": str(e)}, computed_at=now,
                )

        # Calculate overall weighted score
        overall = sum(s.score * s.weight for s in scores.values())
        weakest = min(scores, key=lambda d: scores[d].score)

        # Generate improvement action for weakest dimension
        improvement_action = await self._generate_improvement_action(
            weakest, scores[weakest].score, scores[weakest].details
        )

        # Persist current scores
        async with get_session() as session:
            # Clear old benchmark scores
            await session.execute(delete(BenchmarkScoreModel))
            for dim, bs in scores.items():
                session.add(BenchmarkScoreModel(
                    id=self._gen_id(),
                    dimension=dim,
                    score=bs.score,
                    weight=bs.weight,
                    details=bs.details,
                    computed_at=now,
                ))
            # Add to history
            dim_scores_dict = {d: s.score for d, s in scores.items()}
            session.add(BenchmarkHistoryModel(
                overall_score=round(overall, 2),
                dimension_scores=dim_scores_dict,
                weakest_dimension=weakest,
                improvement_action=improvement_action,
                snapshot_at=now,
            ))
            await session.commit()

        snapshot = BenchmarkSnapshot(
            overall_score=round(overall, 2),
            dimension_scores={d: s.score for d, s in scores.items()},
            weakest_dimension=weakest,
            improvement_action=improvement_action,
            snapshot_at=now,
        )

        logger.info("benchmark_complete",
                    overall=snapshot.overall_score, weakest=weakest,
                    weakest_score=scores[weakest].score)
        return snapshot

    async def _score_content_quality(self) -> tuple[float, dict]:
        """Score based on content performance data."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        async with get_session() as session:
            # Count content generated
            total_q = select(sql_func.count(ContentPerformanceModel.id)).where(
                ContentPerformanceModel.created_at >= since
            )
            total = (await session.execute(total_q)).scalar() or 0

            # Average engagement
            avg_q = select(sql_func.avg(ContentPerformanceModel.engagement_rate)).where(
                ContentPerformanceModel.created_at >= since
            )
            avg_engagement = float((await session.execute(avg_q)).scalar() or 0)

        # Scoring: 0 content = 20, 1-5 = 40, 5-20 = 60, 20+ = 80, + engagement bonus
        if total == 0:
            score = 20.0
        elif total < 5:
            score = 40.0
        elif total < 20:
            score = 60.0
        else:
            score = 80.0

        # Engagement bonus (up to 20 points)
        score += min(20, avg_engagement * 200)

        return min(100, score), {
            "content_count_30d": total,
            "avg_engagement": round(avg_engagement, 4),
        }

    async def _score_learning_velocity(self) -> tuple[float, dict]:
        """Compare benchmark improvement rate over recent snapshots."""
        async with get_session() as session:
            query = (
                select(BenchmarkHistoryModel.overall_score)
                .order_by(BenchmarkHistoryModel.snapshot_at.desc())
                .limit(5)
            )
            result = await session.execute(query)
            recent = [r[0] for r in result.all()]

        if len(recent) < 2:
            return 50.0, {"snapshots": len(recent), "trend": "insufficient_data"}

        # Calculate trend
        first = recent[-1]  # oldest
        last = recent[0]  # newest
        delta = last - first

        if delta > 10:
            score = 90.0
            trend = "strong_improvement"
        elif delta > 5:
            score = 75.0
            trend = "improving"
        elif delta > 0:
            score = 60.0
            trend = "slight_improvement"
        elif delta > -5:
            score = 45.0
            trend = "stable"
        else:
            score = 25.0
            trend = "declining"

        return score, {"snapshots": len(recent), "delta": round(delta, 2), "trend": trend}

    async def _score_research_depth(self) -> tuple[float, dict]:
        """Count completed research reports. LLM grades top ones."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        async with get_session() as session:
            count_q = select(sql_func.count(DeepResearchReportModel.id)).where(
                DeepResearchReportModel.created_at >= since,
                DeepResearchReportModel.status == "completed",
            )
            completed = (await session.execute(count_q)).scalar() or 0

        # Base score from completion count
        if completed == 0:
            score = 25.0
        elif completed < 3:
            score = 50.0
        elif completed < 10:
            score = 70.0
        else:
            score = 85.0

        return score, {"completed_reports_30d": completed}

    async def _score_task_execution(self) -> tuple[float, dict]:
        """Task completion rate from agent_tasks."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        async with get_session() as session:
            total_q = select(sql_func.count(AgentTaskModel.id)).where(
                AgentTaskModel.created_at >= since
            )
            total = (await session.execute(total_q)).scalar() or 0

            completed_q = select(sql_func.count(AgentTaskModel.id)).where(
                AgentTaskModel.created_at >= since,
                AgentTaskModel.status == "completed",
            )
            completed = (await session.execute(completed_q)).scalar() or 0

        if total == 0:
            return 50.0, {"total": 0, "completed": 0, "rate": 0}

        rate = completed / total
        score = rate * 100

        return min(100, score), {
            "total_30d": total, "completed": completed,
            "rate": round(rate, 3),
        }

    async def _score_system_health(self) -> tuple[float, dict]:
        """Scheduler job success rate in last 24h."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        async with get_session() as session:
            total_q = select(sql_func.count(SchedulerAuditLogModel.id)).where(
                SchedulerAuditLogModel.started_at >= since
            )
            total = (await session.execute(total_q)).scalar() or 0

            success_q = select(sql_func.count(SchedulerAuditLogModel.id)).where(
                SchedulerAuditLogModel.started_at >= since,
                SchedulerAuditLogModel.status == "completed",
            )
            success = (await session.execute(success_q)).scalar() or 0

        if total == 0:
            return 50.0, {"total_24h": 0, "success": 0}

        rate = success / total
        score = rate * 100

        return min(100, score), {
            "jobs_24h": total, "successful": success,
            "success_rate": round(rate, 3),
        }

    async def _score_experiment_rigor(self) -> tuple[float, dict]:
        """Experiments + council decisions completion rate."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        async with get_session() as session:
            # AI Company experiments
            exp_total_q = select(sql_func.count(ExperimentModel.id)).where(
                ExperimentModel.created_at >= since
            )
            exp_total = (await session.execute(exp_total_q)).scalar() or 0

            exp_completed_q = select(sql_func.count(ExperimentModel.id)).where(
                ExperimentModel.created_at >= since,
                ExperimentModel.conclusion.isnot(None),
            )
            exp_completed = (await session.execute(exp_completed_q)).scalar() or 0

            # Content experiments
            ce_total_q = select(sql_func.count(ContentExperimentModel.id)).where(
                ContentExperimentModel.created_at >= since
            )
            ce_total = (await session.execute(ce_total_q)).scalar() or 0

            # Council decisions
            council_q = select(sql_func.count(CouncilDecisionModel.id)).where(
                CouncilDecisionModel.created_at >= since
            )
            council_count = (await session.execute(council_q)).scalar() or 0

        total = exp_total + ce_total
        completed = exp_completed

        if total == 0 and council_count == 0:
            score = 30.0  # No experiments = low rigor
        elif total == 0:
            score = 50.0
        else:
            rate = completed / total if total > 0 else 0
            score = 40 + (rate * 40) + min(20, council_count * 5)

        return min(100, score), {
            "experiments_30d": exp_total, "completed": exp_completed,
            "content_experiments": ce_total, "council_decisions": council_count,
        }

    async def _score_cost_efficiency(self) -> tuple[float, dict]:
        """LLM cost vs output ratio."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        async with get_session() as session:
            cost_q = select(sql_func.sum(LlmUsageModel.cost_usd)).where(
                LlmUsageModel.created_at >= since
            )
            total_cost = float((await session.execute(cost_q)).scalar() or 0)

            calls_q = select(sql_func.count(LlmUsageModel.id)).where(
                LlmUsageModel.created_at >= since
            )
            total_calls = (await session.execute(calls_q)).scalar() or 0

        if total_calls == 0:
            return 50.0, {"cost_30d": 0, "calls": 0}

        cost_per_call = total_cost / total_calls if total_calls > 0 else 0

        # Score: very efficient < $0.01/call, moderate < $0.05, expensive > $0.10
        if cost_per_call < 0.01:
            score = 90.0
        elif cost_per_call < 0.03:
            score = 75.0
        elif cost_per_call < 0.05:
            score = 60.0
        elif cost_per_call < 0.10:
            score = 45.0
        else:
            score = 30.0

        return score, {
            "total_cost_30d": round(total_cost, 4),
            "total_calls": total_calls,
            "cost_per_call": round(cost_per_call, 5),
        }

    async def _score_communication_quality(self) -> tuple[float, dict]:
        """Score based on briefing generation and notification activity."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        async with get_session() as session:
            # Count successful briefing jobs
            briefing_q = select(sql_func.count(SchedulerAuditLogModel.id)).where(
                SchedulerAuditLogModel.started_at >= since,
                SchedulerAuditLogModel.job_name == "morning_briefing",
                SchedulerAuditLogModel.status == "completed",
            )
            briefings = (await session.execute(briefing_q)).scalar() or 0

        # 30 days should have ~30 briefings
        rate = min(1.0, briefings / 30)
        score = 40 + (rate * 60)

        return min(100, score), {"briefings_30d": briefings, "expected": 30}

    async def _score_calibration_accuracy(self) -> tuple[float, dict]:
        """Use outcome learning service calibration data."""
        try:
            from app.services.outcome_learning_service import get_outcome_learning_service
            svc = get_outcome_learning_service()
            report = await svc.get_calibration_report(days=30)

            if not report:
                return 50.0, {"status": "no_data"}

            total_records = sum(b.count for b in report)
            if total_records < 5:
                return 50.0, {"status": "insufficient_data", "records": total_records}

            # Overall MAE
            weighted_mae = sum(b.mae * b.count for b in report) / total_records if total_records > 0 else 50
            # Lower MAE = better calibration. MAE of 0 = perfect, 50+ = terrible
            score = max(0, 100 - (weighted_mae * 2))

            return score, {
                "mae": round(weighted_mae, 2),
                "total_records": total_records,
            }
        except Exception as e:
            return 50.0, {"error": str(e)}

    async def _score_knowledge_growth(self) -> tuple[float, dict]:
        """New episodic memories + notes in last 30 days vs prior 30."""
        now = datetime.now(timezone.utc)
        recent_start = now - timedelta(days=30)
        prior_start = now - timedelta(days=60)

        async with get_session() as session:
            # Recent memories
            recent_mem_q = select(sql_func.count(EpisodicMemoryModel.id)).where(
                EpisodicMemoryModel.created_at >= recent_start
            )
            recent_memories = (await session.execute(recent_mem_q)).scalar() or 0

            # Prior memories
            prior_mem_q = select(sql_func.count(EpisodicMemoryModel.id)).where(
                EpisodicMemoryModel.created_at >= prior_start,
                EpisodicMemoryModel.created_at < recent_start,
            )
            prior_memories = (await session.execute(prior_mem_q)).scalar() or 0

            # Recent notes
            recent_notes_q = select(sql_func.count(NoteModel.id)).where(
                NoteModel.created_at >= recent_start
            )
            recent_notes = (await session.execute(recent_notes_q)).scalar() or 0

        recent_total = recent_memories + recent_notes
        if recent_total == 0:
            score = 20.0
        elif recent_total < 10:
            score = 40.0
        elif recent_total < 50:
            score = 60.0
        else:
            score = 80.0

        # Growth bonus
        if prior_memories > 0 and recent_memories > prior_memories:
            score = min(100, score + 10)

        return score, {
            "recent_memories": recent_memories,
            "prior_memories": prior_memories,
            "recent_notes": recent_notes,
        }

    async def _generate_improvement_action(
        self, dimension: str, score: float, details: dict
    ) -> Optional[str]:
        """Generate an improvement action for the weakest dimension."""
        try:
            llm = get_unified_llm_client()
            result = await llm.chat(
                prompt=(
                    f"Zero's weakest dimension is '{dimension}' with score {score:.1f}/100. "
                    f"Details: {details}. "
                    f"Suggest ONE specific, actionable improvement in 1-2 sentences."
                ),
                task_type="analysis",
                temperature=0.2,
                max_tokens=200,
            )
            return result.strip() if result else None
        except Exception:
            return None

    async def get_latest(self) -> Optional[BenchmarkSnapshot]:
        """Return most recent benchmark snapshot."""
        try:
            async with get_session() as session:
                query = (
                    select(BenchmarkHistoryModel)
                    .order_by(BenchmarkHistoryModel.snapshot_at.desc())
                    .limit(1)
                )
                result = await session.execute(query)
                row = result.scalar_one_or_none()
                if not row:
                    return None

                return BenchmarkSnapshot(
                    overall_score=row.overall_score,
                    dimension_scores=row.dimension_scores,
                    weakest_dimension=row.weakest_dimension,
                    improvement_action=row.improvement_action,
                    snapshot_at=row.snapshot_at,
                )
        except Exception as e:
            logger.error("get_latest_benchmark_failed", error=str(e))
            return None

    async def get_history(self, limit: int = 20) -> List[BenchmarkSnapshot]:
        """Return benchmark history for trend charting."""
        try:
            async with get_session() as session:
                query = (
                    select(BenchmarkHistoryModel)
                    .order_by(BenchmarkHistoryModel.snapshot_at.desc())
                    .limit(limit)
                )
                result = await session.execute(query)
                rows = result.scalars().all()

                return [
                    BenchmarkSnapshot(
                        overall_score=r.overall_score,
                        dimension_scores=r.dimension_scores,
                        weakest_dimension=r.weakest_dimension,
                        improvement_action=r.improvement_action,
                        snapshot_at=r.snapshot_at,
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.error("get_benchmark_history_failed", error=str(e))
            return []


@lru_cache()
def get_employee_benchmark_service() -> EmployeeBenchmarkService:
    return EmployeeBenchmarkService()
