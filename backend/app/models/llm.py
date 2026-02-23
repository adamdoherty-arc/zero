"""
Centralized LLM routing models.

Defines task types, model assignments with multi-provider support,
fallback chains, and budget configuration for the LLM router.
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from enum import Enum


class TaskType(str, Enum):
    """Known task types that can be routed to specific models."""
    CODING = "coding"
    ANALYSIS = "analysis"
    RESEARCH = "research"
    CHAT = "chat"
    CLASSIFICATION = "classification"
    WORKFLOW = "workflow"
    PLANNING = "planning"
    SUMMARIZATION = "summarization"


class ModelAssignment(BaseModel):
    """A model assigned to a task type with optional provider and fallbacks.

    Model strings support 'provider/model' format:
      - "gemini/gemini-3.1-pro-preview" → Gemini provider
      - "ollama/qwen3:8b" → Ollama provider
      - "openrouter/meta-llama/llama-4-maverick" → OpenRouter provider
      - "qwen3:8b" → defaults to Ollama (backward compat)
    """
    model: str
    fallbacks: Optional[List[str]] = None
    temperature: Optional[float] = None
    num_predict: Optional[int] = None
    keep_alive: Optional[str] = None


def parse_provider_model(spec: str) -> tuple[str, str]:
    """Parse a 'provider/model' string into (provider, model).

    For OpenRouter models with nested slashes (e.g., 'openrouter/meta-llama/llama-4'),
    only the first segment is the provider.

    No slash → defaults to 'ollama' provider.
    """
    if "/" not in spec:
        return "ollama", spec
    provider, _, model = spec.partition("/")
    return provider, model


class LlmRouterConfig(BaseModel):
    """Persisted configuration for the LLM router.

    Models use 'provider/model' format. Plain model names default to ollama.
    """
    default_model: str = "ollama/qwen3:8b"
    task_assignments: Dict[str, ModelAssignment] = Field(default_factory=lambda: {
        "coding": ModelAssignment(
            model="ollama/qwen3:8b",
            fallbacks=["gemini/gemini-3.1-pro-preview"],
            temperature=0.2,
            num_predict=4096,
        ),
        "analysis": ModelAssignment(
            model="ollama/qwen3:8b",
            fallbacks=["gemini/gemini-3.1-pro-preview"],
            temperature=0.1,
            num_predict=500,
        ),
        "research": ModelAssignment(
            model="gemini/gemini-3.1-pro-preview",
            fallbacks=["ollama/qwen3:8b"],
            temperature=0.3,
            num_predict=2048,
        ),
        "chat": ModelAssignment(
            model="ollama/qwen3:8b",
            fallbacks=["gemini/gemini-3.1-pro-preview"],
            temperature=0.7,
            num_predict=2048,
        ),
        "classification": ModelAssignment(
            model="ollama/qwen3:8b",
            temperature=0.0,
            num_predict=200,
        ),
        "workflow": ModelAssignment(
            model="ollama/qwen3:8b",
            temperature=0.7,
            num_predict=4096,
        ),
        "planning": ModelAssignment(
            model="gemini/gemini-3.1-pro-preview",
            fallbacks=["openrouter/meta-llama/llama-4-maverick", "ollama/qwen3:8b"],
            temperature=0.3,
            num_predict=4096,
        ),
        "summarization": ModelAssignment(
            model="ollama/qwen3:8b",
            fallbacks=["gemini/gemini-3.1-pro-preview"],
            temperature=0.1,
            num_predict=1024,
        ),
    })
    daily_budget_usd: float = 5.0
    current_spend_usd: float = 0.0


class LlmRouterStatus(BaseModel):
    """Current state of the LLM router."""
    default_model: str
    task_assignments: Dict[str, ModelAssignment]
    active_model: Optional[str] = None
    daily_budget_usd: float = 5.0
    current_spend_usd: float = 0.0


class TaskAssignmentUpdate(BaseModel):
    """Request to update a task's model assignment."""
    task_type: str
    model: str
    fallbacks: Optional[List[str]] = None
    temperature: Optional[float] = None
    num_predict: Optional[int] = None
    keep_alive: Optional[str] = None


class DefaultModelUpdate(BaseModel):
    """Request to change the default model."""
    model: str
    update_all_tasks: bool = False
