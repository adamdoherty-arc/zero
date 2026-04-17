"""
Zero Brain Service — Central Intelligence Hub.

Coordinates all brain subsystems: episodic memory, outcome learning,
prompt evolution, benchmarking, content learning, and reflection.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from functools import lru_cache

import structlog
from sqlalchemy import select, func as sql_func

from app.infrastructure.database import get_session
from app.db.models import LearningCycleModel
from app.models.brain import (
    BrainStatus, BenchmarkScore, BenchmarkSnapshot,
    EpisodicMemory, MemorySearchResult, LearningCycle,
    ContentExperiment, OutcomeRecord, PromptVariant,
)
from app.services.episodic_memory_service import get_episodic_memory_service
from app.services.outcome_learning_service import get_outcome_learning_service
from app.services.prompt_evolution_service import get_prompt_evolution_service
from app.services.employee_benchmark_service import get_employee_benchmark_service
from app.services.content_learning_engine import get_content_learning_engine
from app.services.reflection_service import get_reflection_service

logger = structlog.get_logger(__name__)


class ZeroBrainService:
    """Central intelligence hub. Coordinates all brain subsystems."""

    @property
    def _memory(self):
        return get_episodic_memory_service()

    @property
    def _outcomes(self):
        return get_outcome_learning_service()

    @property
    def _prompts(self):
        return get_prompt_evolution_service()

    @property
    def _benchmark(self):
        return get_employee_benchmark_service()

    @property
    def _content(self):
        return get_content_learning_engine()

    @property
    def _reflection(self):
        return get_reflection_service()

    def _gen_id(self) -> str:
        return f"lc-{uuid.uuid4().hex[:12]}"

    # ========================================
    # STATUS
    # ========================================

    async def get_status(self) -> BrainStatus:
        """Full brain status: benchmark scores, memory count, active experiments."""
        # Get latest benchmark
        latest = await self._benchmark.get_latest()

        # Get counts
        memory_count = await self._memory.count()
        outcome_count = await self._outcomes.count()
        prompt_count = await self._prompts.count()
        experiment_count = await self._content.count_active_experiments()

        # Get last cycle times
        last_benchmark_at = None
        last_cycle_at = None
        try:
            async with get_session() as session:
                bm_q = (
                    select(LearningCycleModel.completed_at)
                    .where(LearningCycleModel.cycle_type == "benchmark")
                    .where(LearningCycleModel.status == "completed")
                    .order_by(LearningCycleModel.completed_at.desc())
                    .limit(1)
                )
                bm_result = await session.execute(bm_q)
                bm_row = bm_result.scalar_one_or_none()
                last_benchmark_at = bm_row

                lc_q = (
                    select(LearningCycleModel.completed_at)
                    .where(LearningCycleModel.cycle_type == "learning")
                    .where(LearningCycleModel.status == "completed")
                    .order_by(LearningCycleModel.completed_at.desc())
                    .limit(1)
                )
                lc_result = await session.execute(lc_q)
                lc_row = lc_result.scalar_one_or_none()
                last_cycle_at = lc_row
        except Exception:
            pass

        # Build dimension scores
        dimension_scores = {}
        if latest:
            now = datetime.now(timezone.utc)
            from app.services.employee_benchmark_service import DIMENSIONS
            for dim, (weight, _) in DIMENSIONS.items():
                score_val = latest.dimension_scores.get(dim, 50.0)
                dimension_scores[dim] = BenchmarkScore(
                    dimension=dim, score=score_val, weight=weight,
                    details={}, computed_at=now,
                )

        return BrainStatus(
            overall_score=latest.overall_score if latest else 0,
            dimension_scores=dimension_scores,
            weakest_dimension=latest.weakest_dimension if latest else "unknown",
            total_memories=memory_count,
            total_outcomes=outcome_count,
            total_prompt_variants=prompt_count,
            active_experiments=experiment_count,
            last_benchmark_at=last_benchmark_at,
            last_learning_cycle_at=last_cycle_at,
        )

    # ========================================
    # LEARNING CYCLE
    # ========================================

    async def run_learning_cycle(self) -> LearningCycle:
        """Orchestrate a full learning cycle."""
        cycle_id = self._gen_id()
        now = datetime.now(timezone.utc)

        # Create cycle record
        async with get_session() as session:
            session.add(LearningCycleModel(
                id=cycle_id, cycle_type="learning", status="running",
                started_at=now,
            ))
            await session.commit()

        results = {}
        improvements = []

        try:
            # 1. Process content outcomes
            content_result = await self._content.process_content_outcomes()
            results["content_outcomes"] = content_result

            # 2. Check experiments
            exp_results = await self._content.check_experiments()
            results["experiments_completed"] = len(exp_results)
            if exp_results:
                improvements.extend(exp_results)

            # 3. Extract learnings from recent outcomes
            learnings = await self._outcomes.extract_learnings(days=1)
            results["learnings_extracted"] = len(learnings)

            # 4. Cleanup expired memories
            cleaned = await self._memory.cleanup_expired()
            results["memories_cleaned"] = cleaned

            # Mark completed
            async with get_session() as session:
                cycle = await session.get(LearningCycleModel, cycle_id)
                if cycle:
                    cycle.status = "completed"
                    cycle.results = results
                    cycle.improvements = improvements
                    cycle.completed_at = datetime.now(timezone.utc)
                    await session.commit()

            logger.info("learning_cycle_complete", id=cycle_id, results=results)

            return LearningCycle(
                id=cycle_id, cycle_type="learning", status="completed",
                results=results, improvements=improvements,
                started_at=now, completed_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error("learning_cycle_failed", id=cycle_id, error=str(e))
            async with get_session() as session:
                cycle = await session.get(LearningCycleModel, cycle_id)
                if cycle:
                    cycle.status = "failed"
                    cycle.error = str(e)
                    cycle.completed_at = datetime.now(timezone.utc)
                    await session.commit()

            return LearningCycle(
                id=cycle_id, cycle_type="learning", status="failed",
                results=results, error=str(e),
                started_at=now, completed_at=datetime.now(timezone.utc),
            )

    # ========================================
    # BENCHMARK
    # ========================================

    async def run_benchmark(self) -> BenchmarkSnapshot:
        """Run full 10-dimension benchmark."""
        cycle_id = self._gen_id()
        now = datetime.now(timezone.utc)

        async with get_session() as session:
            session.add(LearningCycleModel(
                id=cycle_id, cycle_type="benchmark", status="running",
                started_at=now,
            ))
            await session.commit()

        try:
            snapshot = await self._benchmark.run_benchmark()

            async with get_session() as session:
                cycle = await session.get(LearningCycleModel, cycle_id)
                if cycle:
                    cycle.status = "completed"
                    cycle.results = {
                        "overall_score": snapshot.overall_score,
                        "weakest": snapshot.weakest_dimension,
                    }
                    cycle.completed_at = datetime.now(timezone.utc)
                    await session.commit()

            return snapshot

        except Exception as e:
            async with get_session() as session:
                cycle = await session.get(LearningCycleModel, cycle_id)
                if cycle:
                    cycle.status = "failed"
                    cycle.error = str(e)
                    cycle.completed_at = datetime.now(timezone.utc)
                    await session.commit()
            raise

    # ========================================
    # IMPROVEMENT
    # ========================================

    async def run_improvement(self, dimension: Optional[str] = None) -> Dict[str, Any]:
        """Auto-improve weakest dimension (or specified one)."""
        latest = await self._benchmark.get_latest()
        if not latest:
            return {"status": "no_benchmark_yet", "action": "Run benchmark first"}

        target = dimension or latest.weakest_dimension
        score = latest.dimension_scores.get(target, 50)

        # Store as episodic memory for tracking
        await self._memory.store_direct(
            content=f"Improvement cycle targeting '{target}' dimension (score: {score:.1f}). "
                    f"Action: {latest.improvement_action or 'none specified'}",
            source_type="brain_improvement",
            namespace="system",
            importance=70,
            tags=["improvement", target],
        )

        return {
            "target_dimension": target,
            "current_score": score,
            "improvement_action": latest.improvement_action,
            "status": "improvement_logged",
        }

    # ========================================
    # PROMPT ENRICHMENT
    # ========================================

    async def enrich_task_prompt(
        self,
        task_description: str,
        domain: str = "general",
    ) -> str:
        """Before any LLM task: inject episodic memory + best prompt variant + learnings."""
        parts = []

        # 1. Episodic memory context
        memory_context = await self._memory.enrich_prompt(
            task_description, namespace=domain, limit=3
        )
        if memory_context:
            parts.append(memory_context)

        # 2. Recent learnings
        learnings = await self._outcomes.extract_learnings(domain=domain, days=7, limit=3)
        if learnings:
            parts.append("## Recent Learnings")
            for l in learnings:
                parts.append(f"- {l}")

        # 3. Best strategy hint
        best = await self._outcomes.get_best_strategy(domain=domain, action_type="general")
        if best:
            parts.append(f"\n## Recommended Strategy: {best}")

        return "\n\n".join(parts) if parts else ""

    # ========================================
    # INTERACTION OUTCOME RECORDING
    # ========================================

    async def record_interaction_outcome(
        self,
        domain: str,
        action_type: str,
        action_id: Optional[str] = None,
        strategy_used: Optional[str] = None,
        predicted_score: Optional[float] = None,
        actual_score: Optional[float] = None,
        metrics: Optional[Dict[str, Any]] = None,
        text_for_memory: Optional[str] = None,
    ) -> None:
        """Record an outcome and optionally extract episodic memory."""
        await self._outcomes.record_outcome(
            domain=domain, action_type=action_type,
            action_id=action_id, strategy_used=strategy_used,
            predicted_score=predicted_score, actual_score=actual_score,
            metrics=metrics,
        )

        # Extract episodic memory if text provided
        if text_for_memory:
            await self._memory.extract_and_store(
                text=text_for_memory,
                source_type=f"{domain}_{action_type}",
                source_id=action_id,
                namespace=domain,
            )

    # ========================================
    # MEMORY SEARCH
    # ========================================

    async def search_memory(
        self,
        query: str,
        namespace: Optional[str] = None,
        limit: int = 10,
    ) -> List[MemorySearchResult]:
        """Search episodic memory."""
        return await self._memory.search(query, namespace=namespace, limit=limit)

    async def get_recent_memories(
        self,
        namespace: Optional[str] = None,
        limit: int = 20,
    ) -> List[EpisodicMemory]:
        """Get recent memories."""
        return await self._memory.get_recent(namespace=namespace, limit=limit)

    # ========================================
    # LEARNINGS
    # ========================================

    async def get_learnings(
        self,
        domain: Optional[str] = None,
        days: int = 7,
        limit: int = 20,
    ) -> List[str]:
        """Get recent learnings across all domains."""
        return await self._outcomes.extract_learnings(
            domain=domain, days=days, limit=limit
        )

    # ========================================
    # CALIBRATION
    # ========================================

    async def get_calibration(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Get calibration report."""
        buckets = await self._outcomes.get_calibration_report(domain=domain)
        return {
            "buckets": [b.model_dump() for b in buckets],
            "domain": domain or "all",
        }

    # ========================================
    # PROMPT EVOLUTION
    # ========================================

    async def run_prompt_evolution(self) -> Dict[str, Any]:
        """Evolve prompts for all task types that have enough data."""
        variants = await self._prompts.get_variants()
        task_types = set(v.task_type for v in variants)

        evolved = []
        for tt in task_types:
            new_variant = await self._prompts.evolve(tt)
            if new_variant:
                evolved.append({
                    "task_type": tt,
                    "new_variant": new_variant.variant_name,
                    "generation": new_variant.generation,
                })

        return {"evolved": evolved, "task_types_checked": len(task_types)}

    # ========================================
    # REFLECTION
    # ========================================

    async def run_reflection(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Run reflection on recent decisions and outcomes."""
        recent = await self._outcomes.get_recent(domain=domain, limit=20)

        decisions = [
            {
                "action_type": r.action_type,
                "strategy": r.strategy_used,
                "predicted": r.predicted_score,
                "actual": r.actual_score,
            }
            for r in recent
            if r.actual_score is not None
        ]

        if not decisions:
            return {"learnings": [], "status": "no_decisions_to_reflect_on"}

        learnings = await self._reflection.reflect_on_decisions(
            decisions=decisions, domain=domain or "general"
        )

        # Store learnings as episodic memories
        for learning in learnings:
            await self._memory.store_direct(
                content=learning,
                source_type="reflection",
                namespace=domain or "general",
                importance=75,
                tags=["reflection", "meta-learning"],
            )

        return {"learnings": learnings, "decisions_analyzed": len(decisions)}

    # ========================================
    # LEARNING CYCLES
    # ========================================

    async def get_recent_cycles(self, limit: int = 20) -> List[LearningCycle]:
        """Get recent learning cycles."""
        try:
            async with get_session() as session:
                query = (
                    select(LearningCycleModel)
                    .order_by(LearningCycleModel.started_at.desc())
                    .limit(limit)
                )
                result = await session.execute(query)
                rows = result.scalars().all()

                return [
                    LearningCycle(
                        id=r.id, cycle_type=r.cycle_type, status=r.status,
                        input_data=r.input_data or {}, results=r.results or {},
                        improvements=r.improvements or [],
                        cost_usd=r.cost_usd, started_at=r.started_at,
                        completed_at=r.completed_at, error=r.error,
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.error("get_recent_cycles_failed", error=str(e))
            return []

    # ========================================
    # CONTENT DELEGATION
    # ========================================

    async def get_content_insights(self) -> Dict[str, Any]:
        return await self._content.get_product_performance_insights()

    async def get_content_strategies(self) -> List[Dict]:
        return await self._content.get_content_strategy_leaderboard()

    async def get_posting_times(self) -> Dict[str, Any]:
        return await self._content.get_posting_time_analysis()

    async def get_experiments(self, status: Optional[str] = None) -> List[ContentExperiment]:
        return await self._content.get_experiments(status=status)

    async def create_experiment(
        self, experiment_type: str, hypothesis: str,
        control_config: Dict, variant_config: Dict,
        name: Optional[str] = None, sample_size: int = 10,
    ) -> ContentExperiment:
        return await self._content.run_content_experiment(
            experiment_type=experiment_type, hypothesis=hypothesis,
            control_config=control_config, variant_config=variant_config,
            name=name, sample_size_target=sample_size,
        )

    async def get_prompt_variants(
        self, task_type: Optional[str] = None
    ) -> List[PromptVariant]:
        return await self._prompts.get_variants(task_type=task_type)

    async def get_best_prompt(self, task_type: str) -> Optional[PromptVariant]:
        return await self._prompts.select_best(task_type)

    async def get_benchmark_history(self, limit: int = 20) -> List[BenchmarkSnapshot]:
        return await self._benchmark.get_history(limit=limit)


@lru_cache()
def get_zero_brain_service() -> ZeroBrainService:
    return ZeroBrainService()
