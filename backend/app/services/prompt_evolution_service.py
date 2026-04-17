"""
Prompt Evolution Service for Zero Brain.

Tracks prompt variants per task type. Selects the best variant using
Thompson Sampling. Evolves prompts based on outcome data.
"""

import random
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from functools import lru_cache

import structlog
from sqlalchemy import select, update, func as sql_func

from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client
from app.db.models import PromptVariantModel, PromptRunModel
from app.models.brain import PromptVariant, PromptRun, PromptRunCreate, PromptRunGrade

logger = structlog.get_logger(__name__)

MIN_USES_TO_EVOLVE = 10
MAX_ACTIVE_VARIANTS = 5

EVOLUTION_SYSTEM_PROMPT = """You are a prompt engineer. Given a prompt template and its performance data,
create an improved variant. Focus on:
- Making instructions clearer and more specific
- Adding constraints that prevent common failure modes
- Incorporating patterns from successful outcomes
- Removing or rephrasing parts that correlate with failures

Return ONLY the improved prompt template text, nothing else."""


class PromptEvolutionService:
    """Tracks prompt variants per task type. Evolves based on outcome data."""

    def _gen_id(self) -> str:
        return f"pv-{uuid.uuid4().hex[:12]}"

    async def register_variant(
        self,
        task_type: str,
        variant_name: str,
        prompt_template: str,
        is_baseline: bool = False,
        parent_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> PromptVariant:
        """Register a new prompt variant."""
        variant_id = self._gen_id()
        now = datetime.now(timezone.utc)

        generation = 1
        if parent_id:
            async with get_session() as session:
                parent = await session.get(PromptVariantModel, parent_id)
                if parent:
                    generation = parent.generation + 1

        async with get_session() as session:
            model = PromptVariantModel(
                id=variant_id,
                task_type=task_type,
                variant_name=variant_name,
                prompt_template=prompt_template,
                parameters=parameters or {},
                is_baseline=is_baseline,
                parent_id=parent_id,
                generation=generation,
                created_at=now,
            )
            session.add(model)
            await session.commit()

        logger.info("prompt_variant_registered",
                    id=variant_id, task_type=task_type, name=variant_name,
                    generation=generation, is_baseline=is_baseline)

        return PromptVariant(
            id=variant_id, task_type=task_type, variant_name=variant_name,
            prompt_template=prompt_template, parameters=parameters or {},
            is_baseline=is_baseline, parent_id=parent_id, generation=generation,
            created_at=now,
        )

    async def select_best(self, task_type: str) -> Optional[PromptVariant]:
        """Select the best variant using Thompson Sampling for exploration/exploitation."""
        try:
            async with get_session() as session:
                query = (
                    select(PromptVariantModel)
                    .where(PromptVariantModel.task_type == task_type)
                    .where(PromptVariantModel.is_active == True)
                )
                result = await session.execute(query)
                variants = result.scalars().all()

                if not variants:
                    return None

                # Thompson Sampling: sample from Beta distribution
                best_variant = None
                best_sample = -1.0
                for v in variants:
                    # Beta(successes + 1, failures + 1)
                    sample = random.betavariate(v.success_count + 1, v.failure_count + 1)
                    if sample > best_sample:
                        best_sample = sample
                        best_variant = v

                if not best_variant:
                    return None

                return PromptVariant(
                    id=best_variant.id, task_type=best_variant.task_type,
                    variant_name=best_variant.variant_name,
                    prompt_template=best_variant.prompt_template,
                    parameters=best_variant.parameters or {},
                    success_count=best_variant.success_count,
                    failure_count=best_variant.failure_count,
                    total_uses=best_variant.total_uses,
                    avg_score=best_variant.avg_score,
                    is_active=best_variant.is_active,
                    is_baseline=best_variant.is_baseline,
                    parent_id=best_variant.parent_id,
                    generation=best_variant.generation,
                    created_at=best_variant.created_at,
                    last_used_at=best_variant.last_used_at,
                )

        except Exception as e:
            logger.error("prompt_select_failed", error=str(e))
            return None

    async def record_usage(
        self,
        variant_id: str,
        score: float,
        success: bool,
    ) -> None:
        """Record outcome of a variant usage. Update avg_score, counts."""
        try:
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                variant = await session.get(PromptVariantModel, variant_id)
                if not variant:
                    logger.warning("prompt_variant_not_found", id=variant_id)
                    return

                variant.total_uses += 1
                if success:
                    variant.success_count += 1
                else:
                    variant.failure_count += 1

                # Running average
                old_total = variant.total_uses - 1
                if old_total > 0:
                    variant.avg_score = (variant.avg_score * old_total + score) / variant.total_uses
                else:
                    variant.avg_score = score

                variant.last_used_at = now
                await session.commit()

        except Exception as e:
            logger.error("prompt_usage_record_failed", error=str(e))

    async def evolve(self, task_type: str) -> Optional[PromptVariant]:
        """Create a new variant by LLM-mutating the best current variant.

        Only evolves if the best variant has enough usage data.
        """
        try:
            async with get_session() as session:
                # Find the best performing variant with enough data
                query = (
                    select(PromptVariantModel)
                    .where(PromptVariantModel.task_type == task_type)
                    .where(PromptVariantModel.is_active == True)
                    .where(PromptVariantModel.total_uses >= MIN_USES_TO_EVOLVE)
                    .order_by(PromptVariantModel.avg_score.desc())
                    .limit(1)
                )
                result = await session.execute(query)
                best = result.scalar_one_or_none()

                if not best:
                    logger.info("prompt_evolve_skipped",
                              task_type=task_type, reason="no_variant_with_enough_data")
                    return None

                # Check if we have too many active variants
                count_query = (
                    select(sql_func.count())
                    .select_from(PromptVariantModel)
                    .where(PromptVariantModel.task_type == task_type)
                    .where(PromptVariantModel.is_active == True)
                )
                count_result = await session.execute(count_query)
                active_count = count_result.scalar() or 0

                if active_count >= MAX_ACTIVE_VARIANTS:
                    # Deactivate the worst performer (non-baseline)
                    worst_query = (
                        select(PromptVariantModel)
                        .where(PromptVariantModel.task_type == task_type)
                        .where(PromptVariantModel.is_active == True)
                        .where(PromptVariantModel.is_baseline == False)
                        .order_by(PromptVariantModel.avg_score.asc())
                        .limit(1)
                    )
                    worst_result = await session.execute(worst_query)
                    worst = worst_result.scalar_one_or_none()
                    if worst:
                        worst.is_active = False
                        await session.commit()

            # Use LLM to create improved variant
            llm = get_unified_llm_client()
            performance_context = (
                f"Current template (score: {best.avg_score:.1f}/100, "
                f"success rate: {best.success_count}/{best.total_uses}):\n\n"
                f"{best.prompt_template}"
            )

            improved = await llm.chat(
                prompt=performance_context,
                system=EVOLUTION_SYSTEM_PROMPT,
                task_type="analysis",
                temperature=0.3,
                max_tokens=4096,
            )

            if not improved or len(improved.strip()) < 20:
                logger.warning("prompt_evolution_empty_result", task_type=task_type)
                return None

            # Register the evolved variant
            new_variant = await self.register_variant(
                task_type=task_type,
                variant_name=f"{best.variant_name}_gen{best.generation + 1}",
                prompt_template=improved.strip(),
                parent_id=best.id,
            )

            logger.info("prompt_evolved",
                        task_type=task_type, parent=best.id, child=new_variant.id,
                        generation=new_variant.generation)
            return new_variant

        except Exception as e:
            logger.error("prompt_evolution_failed", error=str(e))
            return None

    async def get_variants(
        self,
        task_type: Optional[str] = None,
        active_only: bool = True,
    ) -> List[PromptVariant]:
        """List prompt variants."""
        try:
            async with get_session() as session:
                query = select(PromptVariantModel).order_by(
                    PromptVariantModel.avg_score.desc()
                )
                if task_type:
                    query = query.where(PromptVariantModel.task_type == task_type)
                if active_only:
                    query = query.where(PromptVariantModel.is_active == True)

                result = await session.execute(query)
                rows = result.scalars().all()

                return [
                    PromptVariant(
                        id=r.id, task_type=r.task_type,
                        variant_name=r.variant_name,
                        prompt_template=r.prompt_template,
                        parameters=r.parameters or {},
                        success_count=r.success_count,
                        failure_count=r.failure_count,
                        total_uses=r.total_uses,
                        avg_score=r.avg_score,
                        is_active=r.is_active,
                        is_baseline=r.is_baseline,
                        parent_id=r.parent_id,
                        generation=r.generation,
                        created_at=r.created_at,
                        last_used_at=r.last_used_at,
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.error("get_variants_failed", error=str(e))
            return []

    async def count(self, active_only: bool = True) -> int:
        """Count total prompt variants."""
        try:
            async with get_session() as session:
                query = select(sql_func.count(PromptVariantModel.id))
                if active_only:
                    query = query.where(PromptVariantModel.is_active == True)
                result = await session.execute(query)
                return result.scalar() or 0
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Prompt Runs: full request/response capture
    # ------------------------------------------------------------------

    async def record_run(self, run: PromptRunCreate) -> Optional[str]:
        """Persist a full prompt/response record.

        Fire-and-forget from the caller's perspective; callers should not
        let recording failures block their flow. Returns the run id, or
        None if persistence fails.
        """
        try:
            run_id = f"pr-{uuid.uuid4().hex[:12]}"
            async with get_session() as session:
                model = PromptRunModel(
                    id=run_id,
                    variant_id=run.variant_id,
                    task_type=run.task_type,
                    source=run.source,
                    source_id=run.source_id,
                    provider=run.provider,
                    model=run.model,
                    system_prompt=run.system_prompt,
                    user_prompt=run.user_prompt,
                    rendered_variables=run.rendered_variables or {},
                    response_text=run.response_text,
                    prompt_tokens=run.prompt_tokens,
                    completion_tokens=run.completion_tokens,
                    latency_ms=run.latency_ms,
                    cost_usd=run.cost_usd,
                    success=run.success,
                    error_type=run.error_type,
                    error_message=run.error_message,
                    context=run.context or {},
                )
                session.add(model)
                await session.commit()
            return run_id
        except Exception as e:
            logger.warning("prompt_run_record_failed", error=str(e))
            return None

    async def apply_grade(
        self,
        run_id: str,
        grade: PromptRunGrade,
    ) -> bool:
        """Attach a grade to a prompt run AND update its variant stats."""
        try:
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                row = await session.get(PromptRunModel, run_id)
                if not row:
                    return False
                row.quality_score = grade.quality_score
                row.quality_flags = grade.quality_flags or []
                row.quality_summary = grade.quality_summary
                row.grader_model = grade.grader_model
                row.graded_at = now

                variant_id = row.variant_id
                await session.commit()

            # Feed the grade into variant stats so Thompson Sampling responds
            if variant_id:
                success = grade.quality_score >= 60 and "hallucination" not in grade.quality_flags
                await self.record_usage(variant_id, grade.quality_score, success)
            return True
        except Exception as e:
            logger.error("prompt_grade_apply_failed", error=str(e))
            return False

    async def get_ungraded_runs(self, limit: int = 20) -> List[PromptRun]:
        """Return successful runs that have not yet been graded, oldest first."""
        try:
            async with get_session() as session:
                query = (
                    select(PromptRunModel)
                    .where(PromptRunModel.success == True)
                    .where(PromptRunModel.graded_at.is_(None))
                    .where(PromptRunModel.response_text.isnot(None))
                    .order_by(PromptRunModel.created_at.asc())
                    .limit(limit)
                )
                result = await session.execute(query)
                rows = result.scalars().all()
                return [self._run_to_pydantic(r) for r in rows]
        except Exception as e:
            logger.error("prompt_get_ungraded_failed", error=str(e))
            return []

    async def get_runs(
        self,
        task_type: Optional[str] = None,
        source: Optional[str] = None,
        variant_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[PromptRun]:
        """List prompt runs, newest first."""
        try:
            async with get_session() as session:
                query = select(PromptRunModel).order_by(
                    PromptRunModel.created_at.desc()
                )
                if task_type:
                    query = query.where(PromptRunModel.task_type == task_type)
                if source:
                    query = query.where(PromptRunModel.source == source)
                if variant_id:
                    query = query.where(PromptRunModel.variant_id == variant_id)
                query = query.limit(limit)
                result = await session.execute(query)
                return [self._run_to_pydantic(r) for r in result.scalars().all()]
        except Exception as e:
            logger.error("prompt_get_runs_failed", error=str(e))
            return []

    async def record_outcome(
        self,
        run_id: str,
        outcome_score: float,
    ) -> bool:
        """Record a downstream outcome (e.g. published carousel engagement)
        against a run so we can correlate prompts -> real-world results.
        """
        try:
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                row = await session.get(PromptRunModel, run_id)
                if not row:
                    return False
                row.outcome_score = outcome_score
                row.outcome_recorded_at = now
                await session.commit()
            return True
        except Exception as e:
            logger.error("prompt_outcome_record_failed", error=str(e))
            return False

    async def record_outcome_by_source(
        self,
        source: str,
        source_id: str,
        outcome_score: float,
    ) -> int:
        """Record an outcome against every run matching (source, source_id).

        Returns the number of runs updated. Used when a downstream object
        (e.g. a carousel) reaches a terminal state (approved/rejected/published)
        and we want to propagate that signal to every prompt that contributed.
        """
        updated = 0
        try:
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                query = (
                    select(PromptRunModel)
                    .where(PromptRunModel.source == source)
                    .where(PromptRunModel.source_id == source_id)
                )
                result = await session.execute(query)
                rows = result.scalars().all()
                for row in rows:
                    row.outcome_score = outcome_score
                    row.outcome_recorded_at = now
                    updated += 1
                if updated:
                    await session.commit()
        except Exception as e:
            logger.error(
                "prompt_outcome_bulk_failed",
                source=source, source_id=source_id, error=str(e),
            )
        return updated

    def _run_to_pydantic(self, r: PromptRunModel) -> PromptRun:
        return PromptRun(
            id=r.id,
            variant_id=r.variant_id,
            task_type=r.task_type,
            source=r.source,
            source_id=r.source_id,
            provider=r.provider,
            model=r.model,
            system_prompt=r.system_prompt,
            user_prompt=r.user_prompt,
            rendered_variables=r.rendered_variables or {},
            response_text=r.response_text,
            prompt_tokens=r.prompt_tokens,
            completion_tokens=r.completion_tokens,
            latency_ms=r.latency_ms,
            cost_usd=r.cost_usd,
            success=r.success,
            error_type=r.error_type,
            error_message=r.error_message,
            quality_score=r.quality_score,
            quality_flags=list(r.quality_flags or []),
            quality_summary=r.quality_summary,
            grader_model=r.grader_model,
            graded_at=r.graded_at,
            outcome_score=r.outcome_score,
            outcome_recorded_at=r.outcome_recorded_at,
            context=r.context or {},
            created_at=r.created_at,
        )


@lru_cache()
def get_prompt_evolution_service() -> PromptEvolutionService:
    return PromptEvolutionService()
