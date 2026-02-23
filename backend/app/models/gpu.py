"""
GPU and Ollama resource management models.
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class GpuInfo(BaseModel):
    """GPU hardware information."""
    name: str = "NVIDIA RTX 5090"
    total_vram_mb: int = 32768
    used_vram_mb: int = 0
    free_vram_mb: int = 32768
    utilization_percent: float = 0.0
    temperature_c: Optional[int] = None
    available: bool = False  # True if nvidia-smi data was obtained


class OllamaModelInfo(BaseModel):
    """A model available in Ollama (from /api/tags)."""
    name: str
    size_bytes: int
    size_gb: float
    parameter_size: Optional[str] = None
    quantization: Optional[str] = None
    family: Optional[str] = None
    modified_at: Optional[str] = None


class LoadedModel(BaseModel):
    """A model currently loaded in VRAM (from /api/ps)."""
    name: str
    size_bytes: int
    size_vram_bytes: int
    size_vram_mb: int
    vram_percent: float = 0.0
    expires_at: Optional[str] = None
    context_length: Optional[int] = None


class ProjectUsage(BaseModel):
    """Tracks which project last used Ollama."""
    project: str
    model: str
    last_used_at: str
    request_count: int = 0


class VramBudget(BaseModel):
    """VRAM budget calculation result."""
    total_vram_mb: int
    used_vram_mb: int
    free_vram_mb: int
    loaded_models: List[LoadedModel] = Field(default_factory=list)
    can_fit: bool = False
    requested_model: Optional[str] = None
    requested_model_size_mb: Optional[int] = None
    models_to_unload: List[str] = Field(default_factory=list)
    recommendation: str = ""


class GpuStatus(BaseModel):
    """Complete GPU + Ollama resource status."""
    gpu: GpuInfo
    ollama_healthy: bool = False
    ollama_url: str = ""
    loaded_models: List[LoadedModel] = Field(default_factory=list)
    available_models: List[OllamaModelInfo] = Field(default_factory=list)
    project_usage: List[ProjectUsage] = Field(default_factory=list)
    vram_budget: VramBudget
    last_refresh: Optional[str] = None
    refresh_interval_seconds: int = 60


class GpuManagerConfig(BaseModel):
    """Persisted configuration for the GPU manager."""
    total_vram_mb: int = 32768
    refresh_interval_seconds: int = 60
    default_keep_alive: str = "30m"
    vram_safety_margin_mb: int = 1024
    preferred_model: str = "qwen3-coder-next:latest"
    project_priorities: Dict[str, int] = Field(
        default_factory=lambda: {"zero": 3, "legion": 2, "ada": 1}
    )
    nvidia_smi_proxy_url: Optional[str] = None


# Request models

class ModelLoadRequest(BaseModel):
    model: str
    project: str = "zero"
    keep_alive: str = "30m"
    force: bool = False


class ModelUnloadRequest(BaseModel):
    model: str
    project: str = "zero"


class UsageReportRequest(BaseModel):
    project: str
    model: str


class ConfigUpdateRequest(BaseModel):
    total_vram_mb: Optional[int] = None
    refresh_interval_seconds: Optional[int] = None
    default_keep_alive: Optional[str] = None
    vram_safety_margin_mb: Optional[int] = None
    preferred_model: Optional[str] = None
    project_priorities: Optional[Dict[str, int]] = None
    nvidia_smi_proxy_url: Optional[str] = None
