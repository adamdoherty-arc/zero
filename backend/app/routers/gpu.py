"""
GPU and Ollama resource management endpoints.
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.models.gpu import (
    ConfigUpdateRequest,
    ModelLoadRequest,
    ModelUnloadRequest,
    UsageReportRequest,
)

router = APIRouter()


# ============================================
# STATUS
# ============================================


@router.get("/status")
async def gpu_status() -> Dict[str, Any]:
    """Complete GPU + Ollama resource status."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    status = await svc.get_status()
    return status.model_dump()


@router.post("/refresh")
async def force_refresh() -> Dict[str, Any]:
    """Force an immediate refresh of GPU/Ollama state."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    await svc.refresh()
    return {"status": "refreshed"}


# ============================================
# MODELS
# ============================================


@router.get("/models/loaded")
async def loaded_models() -> Dict[str, Any]:
    """List models currently loaded in VRAM."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    status = await svc.get_status()
    return {
        "models": [m.model_dump() for m in status.loaded_models],
        "count": len(status.loaded_models),
        "total_vram_used_mb": sum(m.size_vram_mb for m in status.loaded_models),
    }


@router.get("/models/available")
async def available_models() -> Dict[str, Any]:
    """List all models available in Ollama."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    status = await svc.get_status()
    return {
        "models": [m.model_dump() for m in status.available_models],
        "count": len(status.available_models),
    }


@router.post("/models/load")
async def load_model(body: ModelLoadRequest) -> Dict[str, Any]:
    """Load a model into VRAM with VRAM budget check."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    result = await svc.load_model(
        model=body.model,
        project=body.project,
        keep_alive=body.keep_alive,
        force=body.force,
    )
    if result["status"] == "error":
        raise HTTPException(500, result.get("error", "Failed to load model"))
    return result


@router.post("/models/unload")
async def unload_model(body: ModelUnloadRequest) -> Dict[str, Any]:
    """Unload a model from VRAM."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    return await svc.unload_model(model=body.model, project=body.project)


# ============================================
# BUDGET
# ============================================


@router.get("/budget/{model_name}")
async def vram_budget(model_name: str) -> Dict[str, Any]:
    """Calculate VRAM budget for loading a model."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    budget = await svc.calculate_vram_budget(model_name)
    return budget.model_dump()


# ============================================
# USAGE TRACKING
# ============================================


@router.get("/usage")
async def project_usage() -> Dict[str, Any]:
    """Get per-project Ollama usage tracking."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    status = await svc.get_status()
    return {
        "usage": [u.model_dump() for u in status.project_usage],
        "count": len(status.project_usage),
    }


@router.post("/usage/report")
async def report_usage(body: UsageReportRequest) -> Dict[str, Any]:
    """External projects report their Ollama usage."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    await svc.record_external_usage(project=body.project, model=body.model)
    return {"status": "recorded", "project": body.project, "model": body.model}


# ============================================
# CONFIGURATION
# ============================================


@router.get("/config")
async def get_config() -> Dict[str, Any]:
    """Get GPU manager configuration."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    config = await svc.get_config()
    return config.model_dump()


@router.patch("/config")
async def update_config(body: ConfigUpdateRequest) -> Dict[str, Any]:
    """Update GPU manager configuration."""
    from app.services.gpu_manager_service import get_gpu_manager_service

    svc = get_gpu_manager_service()
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    config = await svc.update_config(updates)
    return config.model_dump()
