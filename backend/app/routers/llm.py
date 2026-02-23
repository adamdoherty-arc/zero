"""
LLM Router API — manage centralized model configuration.

GET  /api/llm/config          - Current router config (default model + all task assignments)
PUT  /api/llm/default-model   - Change the default model
PUT  /api/llm/task/{type}     - Set model for a specific task type
DELETE /api/llm/task/{type}   - Remove task override (fall back to default)
GET  /api/llm/resolve/{type}  - Resolve which model a task type would use
GET  /api/llm/providers       - List all providers with health status
GET  /api/llm/usage/today     - Today's spend + usage breakdown
GET  /api/llm/available-models - All models grouped by provider
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

from app.infrastructure.llm_router import get_llm_router
from app.models.llm import (
    DefaultModelUpdate,
    LlmRouterStatus,
    TaskAssignmentUpdate,
)

router = APIRouter()


@router.get("/config", response_model=LlmRouterStatus)
async def get_config():
    """Get the current LLM router configuration."""
    llm = get_llm_router()
    return LlmRouterStatus(
        default_model=llm.config.default_model,
        task_assignments=llm.config.task_assignments,
        daily_budget_usd=llm.config.daily_budget_usd,
        current_spend_usd=llm.config.current_spend_usd,
    )


@router.put("/default-model")
async def set_default_model(req: DefaultModelUpdate):
    """Change the default model for the entire system."""
    llm = get_llm_router()
    await llm.set_default_model(req.model, update_all_tasks=req.update_all_tasks)
    return {
        "status": "updated",
        "default_model": llm.default_model,
        "tasks_updated": req.update_all_tasks,
    }


@router.put("/task/{task_type}")
async def set_task_model(task_type: str, req: TaskAssignmentUpdate):
    """Set or update the model for a specific task type."""
    llm = get_llm_router()
    await llm.set_task_model(
        task_type=task_type,
        model=req.model,
        fallbacks=req.fallbacks,
        temperature=req.temperature,
        num_predict=req.num_predict,
        keep_alive=req.keep_alive,
    )
    return {"status": "updated", "task_type": task_type, "model": req.model}


@router.delete("/task/{task_type}")
async def remove_task_override(task_type: str):
    """Remove a task-specific model override."""
    llm = get_llm_router()
    await llm.remove_task_override(task_type)
    return {"status": "removed", "task_type": task_type}


@router.get("/resolve/{task_type}")
async def resolve_model(task_type: str):
    """Resolve which model would be used for a task type."""
    llm = get_llm_router()
    model, assignment = llm.resolve_with_params(task_type)
    return {
        "task_type": task_type,
        "model": model,
        "assignment": assignment.model_dump() if assignment else None,
        "is_default": assignment is None,
    }


@router.get("/providers")
async def list_providers():
    """List all configured LLM providers with health status."""
    from app.infrastructure.llm_providers import get_provider_registry

    registry = get_provider_registry()
    providers = []

    for name, provider in registry.items():
        healthy = False
        try:
            healthy = await provider.is_healthy()
        except Exception:
            pass

        providers.append({
            "name": name,
            "configured": provider.is_configured,
            "healthy": healthy,
        })

    return {"providers": providers}


@router.get("/usage/today")
async def usage_today():
    """Get today's LLM spend and usage breakdown by provider."""
    from app.infrastructure.database import get_session
    from sqlalchemy import select, func
    from app.db.models import LlmUsageModel

    llm = get_llm_router()
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    async with get_session() as session:
        # Totals
        totals_q = select(
            func.count(LlmUsageModel.id).label("total_calls"),
            func.coalesce(func.sum(LlmUsageModel.cost_usd), 0).label("total_cost"),
            func.coalesce(func.sum(LlmUsageModel.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LlmUsageModel.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.avg(LlmUsageModel.latency_ms), 0).label("avg_latency_ms"),
        ).where(LlmUsageModel.created_at >= today_start)
        totals = (await session.execute(totals_q)).first()

        # By provider
        by_provider_q = select(
            LlmUsageModel.provider,
            func.count(LlmUsageModel.id).label("calls"),
            func.coalesce(func.sum(LlmUsageModel.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(LlmUsageModel.prompt_tokens), 0).label("tokens"),
        ).where(
            LlmUsageModel.created_at >= today_start
        ).group_by(LlmUsageModel.provider)
        by_provider_rows = (await session.execute(by_provider_q)).all()

        # By task type
        by_task_q = select(
            LlmUsageModel.task_type,
            func.count(LlmUsageModel.id).label("calls"),
            func.coalesce(func.sum(LlmUsageModel.cost_usd), 0).label("cost"),
        ).where(
            LlmUsageModel.created_at >= today_start
        ).group_by(LlmUsageModel.task_type)
        by_task_rows = (await session.execute(by_task_q)).all()

    return {
        "date": today_start.isoformat(),
        "total_calls": totals.total_calls if totals else 0,
        "total_cost_usd": float(totals.total_cost) if totals else 0.0,
        "prompt_tokens": int(totals.prompt_tokens) if totals else 0,
        "completion_tokens": int(totals.completion_tokens) if totals else 0,
        "avg_latency_ms": float(totals.avg_latency_ms) if totals else 0.0,
        "daily_budget_usd": llm.config.daily_budget_usd,
        "remaining_budget_usd": llm.get_remaining_budget(),
        "by_provider": [
            {
                "provider": row.provider,
                "calls": row.calls,
                "cost_usd": float(row.cost),
                "tokens": int(row.tokens),
            }
            for row in by_provider_rows
        ],
        "by_task_type": [
            {
                "task_type": row.task_type or "unknown",
                "calls": row.calls,
                "cost_usd": float(row.cost),
            }
            for row in by_task_rows
        ],
    }


@router.get("/available-models")
async def available_models():
    """List all available models grouped by provider."""
    from app.infrastructure.llm_providers import get_provider_registry

    registry = get_provider_registry()
    result = {}

    # Ollama models from the Ollama API
    ollama_provider = registry.get("ollama")
    if ollama_provider and ollama_provider.is_configured:
        try:
            from app.infrastructure.ollama_client import OllamaClient
            client = OllamaClient()
            models = await client.list_models()
            result["ollama"] = [m.get("name", m.get("model", "")) for m in models]
        except Exception:
            result["ollama"] = []
    else:
        result["ollama"] = []

    # Cloud providers — static known models
    result["gemini"] = [
        "gemini-3.1-pro-preview",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-pro-preview-05-06",
        "gemini-2.0-flash",
    ]
    result["openrouter"] = [
        "meta-llama/llama-4-maverick",
        "meta-llama/llama-4-scout",
        "anthropic/claude-sonnet-4",
        "google/gemini-3.1-pro-preview",
        "deepseek/deepseek-r1",
    ]
    result["huggingface"] = [
        "mistralai/Mistral-7B-Instruct-v0.3",
        "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    ]
    result["kimi"] = [
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ]

    return {"models_by_provider": result}
