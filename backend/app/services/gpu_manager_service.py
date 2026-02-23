"""
GPU and Ollama Resource Manager Service.

Provides centralized GPU/VRAM monitoring, model lifecycle management,
and cross-project usage tracking for the shared Ollama instance.

Capabilities:
- Query Ollama /api/ps and /api/tags for model state
- Calculate VRAM budgets before loading models
- Load/unload models with project attribution and priority-based eviction
- Track per-project usage history
- Periodic refresh via scheduler (every 60s)
"""

import asyncio
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
import structlog

from app.infrastructure.config import get_settings, get_workspace_path
from app.infrastructure.storage import JsonStorage
from app.models.gpu import (
    GpuInfo,
    GpuManagerConfig,
    GpuStatus,
    LoadedModel,
    OllamaModelInfo,
    ProjectUsage,
    VramBudget,
)

logger = structlog.get_logger(__name__)

STATE_FILE = "gpu_state.json"
CONFIG_FILE = "gpu_config.json"


class GpuManagerService:
    def __init__(self):
        self._storage = JsonStorage(get_workspace_path("gpu"))
        self._settings = get_settings()
        self._ollama_base = self._settings.ollama_base_url.rstrip("/").replace("/v1", "")

        # Cached state (refreshed periodically by scheduler)
        self._gpu_info: Optional[GpuInfo] = None
        self._loaded_models: List[LoadedModel] = []
        self._available_models: List[OllamaModelInfo] = []
        self._project_usage: Dict[str, ProjectUsage] = {}
        self._last_refresh: Optional[datetime] = None
        self._config: GpuManagerConfig = GpuManagerConfig()
        self._lock = asyncio.Lock()

    # ============================================
    # INITIALIZATION
    # ============================================

    async def initialize(self):
        """Load persisted config and state on startup."""
        config_data = await self._storage.read(CONFIG_FILE)
        if config_data:
            self._config = GpuManagerConfig(**config_data)
        else:
            await self._save_config()

        state = await self._storage.read(STATE_FILE)
        if state and state.get("project_usage"):
            for key, usage_data in state["project_usage"].items():
                self._project_usage[key] = ProjectUsage(**usage_data)

        await self.refresh()
        logger.info("gpu_manager_initialized", total_vram_mb=self._config.total_vram_mb)

    # ============================================
    # OLLAMA API
    # ============================================

    async def _fetch_loaded_models(self) -> List[LoadedModel]:
        """Call Ollama /api/ps to get currently loaded models."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._ollama_base}/api/ps")
                if resp.status_code != 200:
                    logger.warning("ollama_ps_failed", status=resp.status_code)
                    return []

                data = resp.json()
                total_vram_bytes = self._config.total_vram_mb * 1024 * 1024
                models = []

                for m in data.get("models", []):
                    size_vram = m.get("size_vram", 0)
                    size_vram_mb = size_vram // (1024 * 1024)
                    models.append(LoadedModel(
                        name=m.get("name", ""),
                        size_bytes=m.get("size", 0),
                        size_vram_bytes=size_vram,
                        size_vram_mb=size_vram_mb,
                        vram_percent=round(size_vram / total_vram_bytes * 100, 1) if total_vram_bytes else 0,
                        expires_at=m.get("expires_at"),
                        context_length=m.get("context_length"),
                    ))
                return models
        except Exception as e:
            logger.warning("ollama_ps_error", error=str(e))
            return []

    async def _fetch_available_models(self) -> List[OllamaModelInfo]:
        """Call Ollama /api/tags to get all available models."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._ollama_base}/api/tags")
                if resp.status_code != 200:
                    return []

                data = resp.json()
                models = []
                for m in data.get("models", []):
                    size = m.get("size", 0)
                    details = m.get("details", {})
                    models.append(OllamaModelInfo(
                        name=m.get("name", ""),
                        size_bytes=size,
                        size_gb=round(size / (1024 ** 3), 1),
                        parameter_size=details.get("parameter_size"),
                        quantization=details.get("quantization_level"),
                        family=details.get("family"),
                        modified_at=m.get("modified_at"),
                    ))
                return sorted(models, key=lambda x: x.size_bytes)
        except Exception as e:
            logger.warning("ollama_tags_error", error=str(e))
            return []

    async def _is_ollama_healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self._ollama_base}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    # ============================================
    # GPU INFO
    # ============================================

    def _estimate_gpu_info(self) -> GpuInfo:
        """Estimate GPU info from Ollama loaded model sizes."""
        total = self._config.total_vram_mb
        used = sum(m.size_vram_mb for m in self._loaded_models)
        return GpuInfo(
            total_vram_mb=total,
            used_vram_mb=used,
            free_vram_mb=total - used,
            available=False,
        )

    # ============================================
    # MODEL MANAGEMENT
    # ============================================

    async def load_model(
        self,
        model: str,
        project: str = "zero",
        keep_alive: str = "30m",
        force: bool = False,
    ) -> Dict[str, Any]:
        """Load a model into VRAM with VRAM budget check."""
        async with self._lock:
            # Check if already loaded
            for m in self._loaded_models:
                if m.name == model:
                    self._record_usage(project, model)
                    return {"status": "already_loaded", "model": model}

            # Calculate budget
            budget = self._calculate_vram_budget(model)

            if not budget.can_fit and not force:
                return {
                    "status": "insufficient_vram",
                    "model": model,
                    "budget": budget.model_dump(),
                    "recommendation": budget.recommendation,
                }

            # If force, unload models to make space
            if not budget.can_fit and force:
                for unload_name in budget.models_to_unload:
                    await self._do_unload(unload_name)
                    logger.info("force_unloaded_model", model=unload_name, for_model=model)

            # Load via /api/chat with trivial prompt
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    resp = await client.post(
                        f"{self._ollama_base}/api/chat",
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": "Reply OK. /no_think"}],
                            "stream": False,
                            "keep_alive": keep_alive,
                            "options": {"num_predict": 5},
                        },
                    )
                    if resp.status_code != 200:
                        return {"status": "error", "model": model,
                                "error": f"Ollama returned {resp.status_code}"}
            except Exception as e:
                return {"status": "error", "model": model, "error": str(e)}

            self._record_usage(project, model)
            await self.refresh()

            return {"status": "loaded", "model": model, "project": project}

    async def unload_model(self, model: str, project: str = "zero") -> Dict[str, Any]:
        """Unload a model from VRAM."""
        async with self._lock:
            await self._do_unload(model)
            await self.refresh()

            still_loaded = any(m.name == model for m in self._loaded_models)
            return {
                "status": "unloaded" if not still_loaded else "still_loaded",
                "model": model,
            }

    async def _do_unload(self, model: str):
        """Internal: send keep_alive=0 to Ollama."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(
                    f"{self._ollama_base}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "x"}],
                        "stream": False,
                        "keep_alive": "0",
                        "options": {"num_predict": 1},
                    },
                )
        except Exception as e:
            logger.warning("unload_model_error", model=model, error=str(e))

    # ============================================
    # VRAM BUDGET
    # ============================================

    def _calculate_vram_budget(self, requested_model: str) -> VramBudget:
        """Calculate whether a model can fit in VRAM."""
        total = self._config.total_vram_mb
        safety = self._config.vram_safety_margin_mb
        used = sum(m.size_vram_mb for m in self._loaded_models)
        free = total - used - safety

        # Check if already loaded
        if any(m.name == requested_model for m in self._loaded_models):
            return VramBudget(
                total_vram_mb=total, used_vram_mb=used, free_vram_mb=free,
                loaded_models=self._loaded_models, can_fit=True,
                requested_model=requested_model, requested_model_size_mb=0,
                recommendation="Model is already loaded.",
            )

        # Find requested model size from available models
        requested_size_mb = 0
        for m in self._available_models:
            if m.name == requested_model:
                requested_size_mb = int(m.size_gb * 1024)
                break

        can_fit = requested_size_mb > 0 and requested_size_mb <= free

        # Determine eviction plan if needed
        models_to_unload: List[str] = []
        recommendation = ""

        if can_fit:
            recommendation = f"Model fits. {free - requested_size_mb}MB will remain free."
        elif requested_size_mb == 0:
            recommendation = "Model size unknown. Cannot calculate budget."
        else:
            # Sort loaded models by project priority (lowest first)
            priorities = self._config.project_priorities
            sortable = []
            for m in self._loaded_models:
                if m.name == requested_model:
                    continue
                proj_priority = 0
                for usage in self._project_usage.values():
                    if usage.model == m.name:
                        proj_priority = priorities.get(usage.project, 0)
                        break
                sortable.append((proj_priority, m))

            sortable.sort(key=lambda x: x[0])

            freed = 0
            for _prio, m in sortable:
                models_to_unload.append(m.name)
                freed += m.size_vram_mb
                if free + freed >= requested_size_mb:
                    break

            if free + freed >= requested_size_mb:
                recommendation = (
                    f"Need to unload {', '.join(models_to_unload)} "
                    f"to free {freed}MB. Use force=true."
                )
            else:
                recommendation = (
                    f"Model requires ~{requested_size_mb}MB but only "
                    f"{free + freed}MB available even after unloading all."
                )

        return VramBudget(
            total_vram_mb=total, used_vram_mb=used, free_vram_mb=free,
            loaded_models=self._loaded_models, can_fit=can_fit,
            requested_model=requested_model,
            requested_model_size_mb=requested_size_mb,
            models_to_unload=models_to_unload,
            recommendation=recommendation,
        )

    async def calculate_vram_budget(self, requested_model: str) -> VramBudget:
        """Public async wrapper for VRAM budget calculation."""
        return self._calculate_vram_budget(requested_model)

    # ============================================
    # PROJECT TRACKING
    # ============================================

    def _record_usage(self, project: str, model: str):
        """Record that a project used a model."""
        key = f"{project}:{model}"
        now = datetime.now(timezone.utc).isoformat()
        if key in self._project_usage:
            self._project_usage[key].last_used_at = now
            self._project_usage[key].request_count += 1
        else:
            self._project_usage[key] = ProjectUsage(
                project=project, model=model,
                last_used_at=now, request_count=1,
            )

    async def record_external_usage(self, project: str, model: str):
        """Public method for other projects to report usage."""
        self._record_usage(project, model)
        await self._save_state()

    # ============================================
    # REFRESH (called by scheduler)
    # ============================================

    async def refresh(self):
        """Refresh all Ollama state."""
        try:
            self._loaded_models = await self._fetch_loaded_models()
            self._available_models = await self._fetch_available_models()
            self._gpu_info = self._estimate_gpu_info()
            self._last_refresh = datetime.now(timezone.utc)
            await self._save_state()
        except Exception as e:
            logger.warning("gpu_manager_refresh_error", error=str(e))

    # ============================================
    # STATUS
    # ============================================

    async def get_status(self) -> GpuStatus:
        """Get complete GPU + Ollama resource status."""
        gpu = self._gpu_info or self._estimate_gpu_info()
        total = self._config.total_vram_mb
        used = sum(m.size_vram_mb for m in self._loaded_models)
        free = total - used

        return GpuStatus(
            gpu=gpu,
            ollama_healthy=await self._is_ollama_healthy(),
            ollama_url=self._ollama_base,
            loaded_models=self._loaded_models,
            available_models=self._available_models,
            project_usage=list(self._project_usage.values()),
            vram_budget=VramBudget(
                total_vram_mb=total, used_vram_mb=used, free_vram_mb=free,
                loaded_models=self._loaded_models,
                recommendation=f"{free}MB free of {total}MB total",
            ),
            last_refresh=self._last_refresh.isoformat() if self._last_refresh else None,
            refresh_interval_seconds=self._config.refresh_interval_seconds,
        )

    async def get_config(self) -> GpuManagerConfig:
        return GpuManagerConfig(**self._config.model_dump())

    async def update_config(self, updates: Dict[str, Any]) -> GpuManagerConfig:
        for key, value in updates.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        await self._save_config()
        return self._config

    # ============================================
    # PERSISTENCE
    # ============================================

    async def _save_state(self):
        await self._storage.write(STATE_FILE, {
            "project_usage": {k: v.model_dump() for k, v in self._project_usage.items()},
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
        })

    async def _save_config(self):
        await self._storage.write(CONFIG_FILE, self._config.model_dump())


@lru_cache()
def get_gpu_manager_service() -> GpuManagerService:
    return GpuManagerService()
