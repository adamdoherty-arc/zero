"""
Zero Brain API Router.

Endpoints for brain status, benchmarks, memory, learning, experiments,
calibration, prompt evolution, and content insights.
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query
from app.infrastructure.auth import require_auth
from app.services.zero_brain_service import get_zero_brain_service
from app.models.brain import (
    BrainStatus, BenchmarkSnapshot, EpisodicMemory,
    MemorySearchResult, LearningCycle, ContentExperiment,
    ContentExperimentCreate, PromptVariant, PromptRun,
)

router = APIRouter(
    prefix="/api/brain",
    tags=["Zero Brain"],
    dependencies=[Depends(require_auth)],
)


# --- Status & Dashboard ---

@router.get("/status")
async def get_brain_status() -> BrainStatus:
    svc = get_zero_brain_service()
    return await svc.get_status()


@router.get("/benchmark")
async def get_benchmark() -> Optional[BenchmarkSnapshot]:
    svc = get_zero_brain_service()
    from app.services.employee_benchmark_service import get_employee_benchmark_service
    return await get_employee_benchmark_service().get_latest()


@router.get("/benchmark/history")
async def get_benchmark_history(
    limit: int = Query(20, ge=1, le=100),
) -> List[BenchmarkSnapshot]:
    svc = get_zero_brain_service()
    return await svc.get_benchmark_history(limit=limit)


@router.post("/benchmark/run")
async def run_benchmark() -> BenchmarkSnapshot:
    svc = get_zero_brain_service()
    return await svc.run_benchmark()


# --- Learning ---

@router.get("/learnings")
async def get_learnings(
    domain: Optional[str] = None,
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=100),
) -> List[str]:
    svc = get_zero_brain_service()
    return await svc.get_learnings(domain=domain, days=days, limit=limit)


@router.get("/calibration")
async def get_calibration(
    domain: Optional[str] = None,
) -> Dict[str, Any]:
    svc = get_zero_brain_service()
    return await svc.get_calibration(domain=domain)


@router.get("/outcomes")
async def get_outcomes(
    domain: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    from app.services.outcome_learning_service import get_outcome_learning_service
    svc = get_outcome_learning_service()
    records = await svc.get_recent(domain=domain, limit=limit)
    metrics = await svc.get_strategy_metrics(domain=domain)
    return {
        "recent": [r.model_dump() for r in records],
        "strategy_metrics": [m.model_dump() for m in metrics],
    }


@router.post("/improve")
async def trigger_improvement(
    dimension: Optional[str] = None,
) -> Dict[str, Any]:
    svc = get_zero_brain_service()
    return await svc.run_improvement(dimension=dimension)


# --- Memory ---

@router.get("/memory")
async def search_memory(
    q: str = Query(..., min_length=2),
    namespace: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
) -> List[Dict[str, Any]]:
    svc = get_zero_brain_service()
    results = await svc.search_memory(q, namespace=namespace, limit=limit)
    return [
        {"memory": r.memory.model_dump(), "similarity": r.similarity}
        for r in results
    ]


@router.get("/memory/recent")
async def get_recent_memories(
    namespace: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    svc = get_zero_brain_service()
    memories = await svc.get_recent_memories(namespace=namespace, limit=limit)
    return [m.model_dump() for m in memories]


# --- Prompt Evolution ---

@router.get("/prompts")
async def get_prompt_variants(
    task_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    svc = get_zero_brain_service()
    variants = await svc.get_prompt_variants(task_type=task_type)
    return [v.model_dump() for v in variants]


@router.get("/prompts/best")
async def get_best_prompt(
    task_type: str = Query(...),
) -> Optional[Dict[str, Any]]:
    svc = get_zero_brain_service()
    variant = await svc.get_best_prompt(task_type=task_type)
    return variant.model_dump() if variant else None


# --- Prompt Runs (full request/response capture) ---

@router.get("/prompt-runs")
async def list_prompt_runs(
    task_type: Optional[str] = None,
    source: Optional[str] = None,
    variant_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    from app.services.prompt_evolution_service import get_prompt_evolution_service
    svc = get_prompt_evolution_service()
    runs = await svc.get_runs(
        task_type=task_type, source=source, variant_id=variant_id, limit=limit,
    )
    return [r.model_dump() for r in runs]


@router.get("/prompt-runs/stats")
async def prompt_run_stats() -> Dict[str, Any]:
    """Aggregate stats per task_type: run count, graded count, avg scores."""
    from app.services.prompt_evolution_service import get_prompt_evolution_service
    from app.infrastructure.database import get_session
    from app.db.models import PromptRunModel
    from sqlalchemy import select, func as sql_func

    svc = get_prompt_evolution_service()
    try:
        async with get_session() as session:
            query = (
                select(
                    PromptRunModel.task_type,
                    sql_func.count(PromptRunModel.id).label("total"),
                    sql_func.count(PromptRunModel.graded_at).label("graded"),
                    sql_func.avg(PromptRunModel.quality_score).label("avg_quality"),
                    sql_func.avg(PromptRunModel.outcome_score).label("avg_outcome"),
                    sql_func.avg(PromptRunModel.latency_ms).label("avg_latency_ms"),
                    sql_func.sum(PromptRunModel.cost_usd).label("total_cost_usd"),
                )
                .group_by(PromptRunModel.task_type)
            )
            result = await session.execute(query)
            by_task = [
                {
                    "task_type": r.task_type,
                    "total": r.total or 0,
                    "graded": r.graded or 0,
                    "ungraded": (r.total or 0) - (r.graded or 0),
                    "avg_quality": round(float(r.avg_quality), 2) if r.avg_quality else None,
                    "avg_outcome": round(float(r.avg_outcome), 2) if r.avg_outcome else None,
                    "avg_latency_ms": round(float(r.avg_latency_ms), 1) if r.avg_latency_ms else None,
                    "total_cost_usd": round(float(r.total_cost_usd or 0), 4),
                }
                for r in result.all()
            ]

            totals_query = select(
                sql_func.count(PromptRunModel.id).label("total"),
                sql_func.count(PromptRunModel.graded_at).label("graded"),
                sql_func.sum(PromptRunModel.cost_usd).label("total_cost_usd"),
            )
            totals_row = (await session.execute(totals_query)).one()
            totals = {
                "total": totals_row.total or 0,
                "graded": totals_row.graded or 0,
                "ungraded": (totals_row.total or 0) - (totals_row.graded or 0),
                "total_cost_usd": round(float(totals_row.total_cost_usd or 0), 4),
            }
        return {"totals": totals, "by_task_type": by_task}
    except Exception:
        return {"totals": {"total": 0, "graded": 0, "ungraded": 0, "total_cost_usd": 0}, "by_task_type": []}


@router.get("/prompt-runs/{run_id}")
async def get_prompt_run(run_id: str) -> Optional[Dict[str, Any]]:
    from app.services.prompt_evolution_service import get_prompt_evolution_service
    from app.infrastructure.database import get_session
    from app.db.models import PromptRunModel
    svc = get_prompt_evolution_service()
    async with get_session() as session:
        row = await session.get(PromptRunModel, run_id)
        if not row:
            return None
        return svc._run_to_pydantic(row).model_dump()


@router.post("/prompt-runs/grade")
async def trigger_prompt_grading(
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Manually kick off the Kimi-as-judge grader for pending runs."""
    from app.services.prompt_grader_service import get_prompt_grader_service
    svc = get_prompt_grader_service()
    return await svc.grade_pending(limit=limit)


@router.post("/prompt-runs/{run_id}/outcome")
async def record_prompt_outcome(
    run_id: str,
    outcome_score: float = Query(..., ge=0, le=100),
) -> Dict[str, Any]:
    """Attach a downstream outcome score (e.g. engagement) to a run."""
    from app.services.prompt_evolution_service import get_prompt_evolution_service
    svc = get_prompt_evolution_service()
    ok = await svc.record_outcome(run_id=run_id, outcome_score=outcome_score)
    return {"ok": ok, "run_id": run_id, "outcome_score": outcome_score}


# --- Content Experiments ---

@router.get("/experiments")
async def get_experiments(
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    svc = get_zero_brain_service()
    exps = await svc.get_experiments(status=status)
    return [e.model_dump() for e in exps]


@router.post("/experiments")
async def create_experiment(
    data: ContentExperimentCreate,
) -> Dict[str, Any]:
    svc = get_zero_brain_service()
    exp = await svc.create_experiment(
        experiment_type=data.experiment_type,
        hypothesis=data.hypothesis,
        control_config=data.control_config,
        variant_config=data.variant_config,
        name=data.name,
        sample_size=data.sample_size_target,
    )
    return exp.model_dump()


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: str) -> Optional[Dict[str, Any]]:
    svc = get_zero_brain_service()
    exps = await svc.get_experiments()
    for e in exps:
        if e.id == experiment_id:
            return e.model_dump()
    return None


# --- Content Learning ---

@router.get("/content/insights")
async def get_content_insights() -> Dict[str, Any]:
    svc = get_zero_brain_service()
    return await svc.get_content_insights()


@router.get("/content/strategies")
async def get_content_strategies() -> List[Dict]:
    svc = get_zero_brain_service()
    return await svc.get_content_strategies()


@router.get("/content/posting-times")
async def get_posting_times() -> Dict[str, Any]:
    svc = get_zero_brain_service()
    return await svc.get_posting_times()


# --- Learning Cycles ---

@router.get("/cycles")
async def get_learning_cycles(
    limit: int = Query(20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    svc = get_zero_brain_service()
    cycles = await svc.get_recent_cycles(limit=limit)
    return [c.model_dump() for c in cycles]


@router.post("/cycles/run")
async def trigger_learning_cycle() -> Dict[str, Any]:
    svc = get_zero_brain_service()
    cycle = await svc.run_learning_cycle()
    return cycle.model_dump()


# --- Content Employee Dashboard (Phase 4 Content Brain v2) ---


@router.get("/employee/overview")
async def get_employee_overview() -> Dict[str, Any]:
    """Live stats: content units last 24h, trending signals active, swarm predictions 7d."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, func as sql_func
    from app.db.models import (
        CharacterCarouselModel, TrendingSignalModel, AgentPredictionModel,
        BenchmarkHistoryModel, CompetitorContentSampleModel, PromptVariantModel,
    )
    from app.infrastructure.database import get_session

    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    async with get_session() as session:
        carousels_24h = (await session.execute(
            select(sql_func.count(CharacterCarouselModel.id))
            .where(CharacterCarouselModel.created_at >= last_24h)
        )).scalar() or 0
        signals_active = (await session.execute(
            select(sql_func.count(TrendingSignalModel.id))
            .where(
                (TrendingSignalModel.expires_at.is_(None))
                | (TrendingSignalModel.expires_at > now)
            )
        )).scalar() or 0
        predictions_7d = (await session.execute(
            select(sql_func.count(AgentPredictionModel.id))
            .where(AgentPredictionModel.created_at >= last_7d)
        )).scalar() or 0
        competitor_samples = (await session.execute(
            select(sql_func.count(CompetitorContentSampleModel.id))
            .where(
                (CompetitorContentSampleModel.expires_at.is_(None))
                | (CompetitorContentSampleModel.expires_at > now)
            )
        )).scalar() or 0
        active_variants = (await session.execute(
            select(sql_func.count(PromptVariantModel.id))
            .where(PromptVariantModel.is_active.is_(True))
        )).scalar() or 0

        last_benchmark = (await session.execute(
            select(BenchmarkHistoryModel)
            .order_by(BenchmarkHistoryModel.snapshot_at.desc())
            .limit(1)
        )).scalars().first()

    return {
        "carousels_last_24h": int(carousels_24h),
        "trending_signals_active": int(signals_active),
        "swarm_predictions_7d": int(predictions_7d),
        "competitor_samples_active": int(competitor_samples),
        "active_prompt_variants": int(active_variants),
        "benchmark_overall": float(last_benchmark.overall_score) if last_benchmark else None,
        "weakest_dimension": last_benchmark.weakest_dimension if last_benchmark else None,
        "last_benchmark_at": last_benchmark.snapshot_at.isoformat() if last_benchmark else None,
    }


@router.get("/employee/agent-stats")
async def get_agent_stats() -> List[Dict[str, Any]]:
    """Per-role calibration + win rate + sample counts."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, func as sql_func, case
    from app.db.models import AgentPredictionModel
    from app.infrastructure.database import get_session

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    async with get_session() as session:
        res = await session.execute(
            select(
                AgentPredictionModel.role_name,
                sql_func.count(AgentPredictionModel.id).label("total"),
                sql_func.avg(AgentPredictionModel.confidence).label("avg_confidence"),
                sql_func.avg(AgentPredictionModel.calibration_error).label("avg_calibration_err"),
                sql_func.sum(case((AgentPredictionModel.vote == "accept", 1), else_=0)).label("accepts"),
                sql_func.sum(case((AgentPredictionModel.vote == "reject", 1), else_=0)).label("rejects"),
            )
            .where(AgentPredictionModel.created_at >= cutoff)
            .group_by(AgentPredictionModel.role_name)
        )
        rows = list(res.all())

    out: List[Dict[str, Any]] = []
    for role_name, total, avg_conf, avg_err, accepts, rejects in rows:
        out.append({
            "role_name": role_name,
            "total_predictions_30d": int(total),
            "avg_confidence": round(float(avg_conf or 0.0), 3),
            "avg_calibration_error": round(float(avg_err or 0.0), 2) if avg_err is not None else None,
            "accept_count": int(accepts or 0),
            "reject_count": int(rejects or 0),
            "accept_rate": round((int(accepts or 0) / int(total)) * 100, 2) if total else 0.0,
        })
    out.sort(key=lambda r: r["total_predictions_30d"], reverse=True)
    return out


@router.get("/employee/trending")
async def get_trending_feed(limit: int = 10) -> List[Dict[str, Any]]:
    """Top active trending signals — used as a live feed on the dashboard."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.db.models import TrendingSignalModel
    from app.infrastructure.database import get_session

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        res = await session.execute(
            select(TrendingSignalModel)
            .where(
                (TrendingSignalModel.expires_at.is_(None))
                | (TrendingSignalModel.expires_at > now)
            )
            .order_by(TrendingSignalModel.signal_strength.desc())
            .limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "id": r.id,
            "source": r.source,
            "title": r.title,
            "franchise": r.franchise,
            "media_type": r.media_type,
            "release_date": r.release_date.isoformat() if r.release_date else None,
            "signal_strength": r.signal_strength,
            "linked_character_count": len(r.linked_character_ids or []),
            "linked_media_title_count": len(r.linked_media_title_ids or []),
        }
        for r in rows
    ]


@router.get("/employee/cost")
async def get_employee_cost() -> Dict[str, Any]:
    """Rolling 7-day LLM cost + cost-per-content-unit."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, func as sql_func
    from app.db.models import LlmUsageModel, CharacterCarouselModel
    from app.infrastructure.database import get_session

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    async with get_session() as session:
        cost_res = await session.execute(
            select(sql_func.sum(LlmUsageModel.cost_usd))
            .where(LlmUsageModel.created_at >= cutoff)
        )
        total_cost = float(cost_res.scalar() or 0.0)
        carousels_res = await session.execute(
            select(sql_func.count(CharacterCarouselModel.id))
            .where(CharacterCarouselModel.created_at >= cutoff)
        )
        total_carousels = int(carousels_res.scalar() or 0)

    cost_per_unit = round(total_cost / total_carousels, 4) if total_carousels else None
    return {
        "total_llm_cost_usd_7d": round(total_cost, 4),
        "carousels_7d": total_carousels,
        "cost_per_carousel_usd": cost_per_unit,
    }


# --- Prompt Breeder trigger endpoint (Phase 3a) ---


@router.post("/prompts/breed")
async def breed_prompts(task_type: Optional[str] = None) -> Dict[str, Any]:
    """Manual trigger for prompt breeder. Omit task_type to breed all."""
    from app.services.prompt_breeder_service import get_prompt_breeder_service
    svc = get_prompt_breeder_service()
    if task_type:
        return await svc.breed_task_type(task_type)
    return await svc.breed_all()
