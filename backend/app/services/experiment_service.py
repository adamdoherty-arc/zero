"""
Experiment Service.
Design, run, and analyze experiments using the AI Company agent roles.
"""

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import List, Dict, Any, Optional

import structlog
from sqlalchemy import select

from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client, StructuredOutputError
from app.db.models import ExperimentModel
from app.models.agent_company import Experiment, ExperimentCreate

logger = structlog.get_logger()


def _orm_to_experiment(row: ExperimentModel) -> Experiment:
    return Experiment(
        id=row.id,
        title=row.title,
        hypothesis=row.hypothesis,
        methodology=row.methodology,
        experiment_type=row.experiment_type,
        status=row.status,
        parameters=row.parameters or {},
        metrics=row.metrics or {},
        results=row.results,
        conclusion=row.conclusion,
        linked_idea_id=row.linked_idea_id,
        linked_research_id=row.linked_research_id,
        created_by_role=row.created_by_role,
        cost_usd=row.cost_usd,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


class ExperimentService:
    def __init__(self):
        self._llm = get_unified_llm_client()

    async def design_experiment(self, req: ExperimentCreate) -> Experiment:
        """CEO designs experiment methodology from a hypothesis."""
        exp_id = f"exp-{uuid.uuid4().hex[:12]}"

        # CEO designs methodology
        design_prompt = (
            f"Design an experiment to test this hypothesis:\n\n"
            f"Hypothesis: {req.hypothesis}\n"
            f"Type: {req.experiment_type}\n"
            f"Parameters: {req.parameters}\n\n"
            "Return JSON:\n"
            '{"methodology": "step-by-step description of how to test this", '
            '"metrics": {"metric_name": "how to measure it"}, '
            '"success_criteria": "what constitutes success", '
            '"estimated_duration": "time estimate", '
            '"risks": ["risk1", "risk2"]}'
        )

        try:
            design = await self._llm.structured_chat(
                prompt=design_prompt,
                system="You are a research director. Design rigorous, practical experiments.",
                task_type="planning",
                temperature=0.7,
                max_tokens=2048,
            )
        except StructuredOutputError:
            design = {"methodology": "Manual evaluation required", "metrics": {}, "success_criteria": "TBD"}

        async with get_session() as session:
            row = ExperimentModel(
                id=exp_id,
                title=req.title,
                hypothesis=req.hypothesis,
                methodology=design.get("methodology", ""),
                experiment_type=req.experiment_type,
                parameters=req.parameters,
                metrics=design.get("metrics", {}),
                linked_idea_id=req.linked_idea_id,
                linked_research_id=req.linked_research_id,
                created_by_role="ceo",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

        logger.info("experiment_designed", exp_id=exp_id, type=req.experiment_type)
        return _orm_to_experiment(row)

    async def run_experiment(self, exp_id: str) -> Experiment:
        """Execute an experiment and generate results."""
        async with get_session() as session:
            row = await session.get(ExperimentModel, exp_id)
            if not row:
                raise ValueError(f"Experiment {exp_id} not found")
            if row.status not in ("designed", "failed"):
                raise ValueError(f"Experiment {exp_id} is {row.status}, cannot run")

            row.status = "running"
            row.started_at = datetime.now(timezone.utc)
            await session.commit()

        try:
            # Execute based on type
            exec_prompt = (
                f"Execute this experiment and provide results:\n\n"
                f"Title: {row.title}\n"
                f"Hypothesis: {row.hypothesis}\n"
                f"Methodology: {row.methodology}\n"
                f"Metrics to measure: {row.metrics}\n"
                f"Parameters: {row.parameters}\n\n"
                "Simulate running this experiment based on your knowledge. Return JSON:\n"
                '{"results": {"metric_name": "measured_value"}, '
                '"observations": ["observation1", "observation2"], '
                '"data_points": [{"label": "point1", "value": 0}], '
                '"anomalies": ["any unexpected findings"]}'
            )

            results = await self._llm.structured_chat(
                prompt=exec_prompt,
                system="You are an experiment runner. Execute experiments methodically and report results precisely.",
                task_type="structured_output",
                temperature=0.2,
                max_tokens=2048,
            )

            # Analyst draws conclusion
            conclusion_prompt = (
                f"Analyze these experiment results:\n\n"
                f"Hypothesis: {row.hypothesis}\n"
                f"Results: {results}\n"
                f"Success criteria: {row.metrics}\n\n"
                "Return JSON:\n"
                '{"conclusion": "clear conclusion about whether hypothesis is supported", '
                '"confidence": 0-100, '
                '"recommendations": ["next step 1", "next step 2"], '
                '"hypothesis_supported": true/false}'
            )

            analysis = await self._llm.structured_chat(
                prompt=conclusion_prompt,
                system="You are a data analyst. Draw clear, evidence-based conclusions.",
                task_type="structured_output",
                temperature=0.2,
                max_tokens=1024,
            )

            async with get_session() as session:
                row = await session.get(ExperimentModel, exp_id)
                row.status = "completed"
                row.results = results if isinstance(results, dict) else {"raw": str(results)}
                row.conclusion = analysis.get("conclusion", "") if isinstance(analysis, dict) else str(analysis)
                row.completed_at = datetime.now(timezone.utc)
                await session.commit()

            logger.info("experiment_completed", exp_id=exp_id)

        except Exception as e:
            logger.error("experiment_failed", exp_id=exp_id, error=str(e))
            async with get_session() as session:
                row = await session.get(ExperimentModel, exp_id)
                row.status = "failed"
                row.results = {"error": str(e)}
                await session.commit()

        return await self.get_experiment(exp_id)

    async def get_experiment(self, exp_id: str) -> Optional[Experiment]:
        async with get_session() as session:
            row = await session.get(ExperimentModel, exp_id)
            return _orm_to_experiment(row) if row else None

    async def list_experiments(
        self, status: Optional[str] = None, exp_type: Optional[str] = None, limit: int = 20
    ) -> List[Experiment]:
        async with get_session() as session:
            q = select(ExperimentModel).order_by(ExperimentModel.created_at.desc()).limit(limit)
            if status:
                q = q.where(ExperimentModel.status == status)
            if exp_type:
                q = q.where(ExperimentModel.experiment_type == exp_type)
            result = await session.execute(q)
            return [_orm_to_experiment(r) for r in result.scalars().all()]


@lru_cache()
def get_experiment_service() -> ExperimentService:
    return ExperimentService()
