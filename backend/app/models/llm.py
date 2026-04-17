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
    STRUCTURED_OUTPUT = "structured_output"
    EXTRACTION = "extraction"
    CHARACTER_CONTENT_REVIEW_FINAL = "character_content_review_final"
    CHARACTER_CONTENT_REVIEW_ESCALATED = "character_content_review_escalated"
    CHARACTER_HOOK_REGEN = "character_hook_regen"
    # Character content research
    CHARACTER_RESEARCH = "character_research"
    # Planner complexity tiers
    COMPLEXITY_SIMPLE = "complexity_simple"
    COMPLEXITY_MODERATE = "complexity_moderate"
    COMPLEXITY_COMPLEX = "complexity_complex"
    # Prompt grading
    PROMPT_GRADING = "prompt_grading"
    PROMPT_GRADING_HEAVY = "prompt_grading_heavy"
    # Council of Agents (intentional provider diversity)
    COUNCIL_CEO = "council_ceo"
    COUNCIL_RESEARCHER = "council_researcher"
    COUNCIL_ANALYST = "council_analyst"
    COUNCIL_VALIDATOR = "council_validator"
    # AI Company agent roles
    AGENT_CEO = "agent_ceo"
    AGENT_RESEARCHER_PLAN = "agent_researcher_plan"
    AGENT_RESEARCHER_EXECUTE = "agent_researcher_execute"
    AGENT_ANALYST = "agent_analyst"
    AGENT_ENGINEER = "agent_engineer"
    AGENT_VALIDATOR = "agent_validator"


class ModelAssignment(BaseModel):
    """A model assigned to a task type with optional provider and fallbacks.

    Model strings support 'provider/model' format:
      - "gemini/gemini-3.1-pro-preview" → Gemini provider
      - "ollama/qwen3.6:35b-a3b-q8_0" → Ollama provider
      - "openrouter/meta-llama/llama-4-maverick" → OpenRouter provider
      - "qwen3.6:35b-a3b-q8_0" → defaults to Ollama (backward compat)
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
    default_model: str = "ollama/qwen3.6:35b-a3b-q8_0"
    task_assignments: Dict[str, ModelAssignment] = Field(default_factory=lambda: {
        # -- Tier 1: Free (Ollama) --
        "coding": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["kimi/kimi-k2-0905-preview", "gemini/gemini-3.1-pro-preview"],
            temperature=0.2,
            num_predict=4096,
        ),
        "workflow": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            temperature=0.7,
            num_predict=4096,
        ),
        # -- Tier 2: Cheap paid (MiniMax M2.7 $0.30/$1.20) --
        # Replaces all moonshot-v1 usage which is overpriced ($1.00/$3.00 for v1-32k)
        "analysis": ModelAssignment(
            model="minimax/MiniMax-M2.7",
            fallbacks=["kimi/kimi-k2-0905-preview", "ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.1,
            num_predict=2048,
        ),
        "chat": ModelAssignment(
            model="minimax/MiniMax-M2.7",
            fallbacks=["kimi/kimi-k2-0905-preview", "ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.7,
            num_predict=2048,
        ),
        "classification": ModelAssignment(
            model="minimax/MiniMax-M2.7",
            fallbacks=["ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.0,
            num_predict=200,
        ),
        "summarization": ModelAssignment(
            model="minimax/MiniMax-M2.7",
            fallbacks=["kimi/kimi-k2-0905-preview", "ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.1,
            num_predict=1024,
        ),
        "prompt_grading": ModelAssignment(
            model="minimax/MiniMax-M2.7",
            fallbacks=["ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.2,
            num_predict=1024,
        ),
        # -- Tier 3: Reasoning (K2-thinking $0.60/$2.50) --
        "research": ModelAssignment(
            model="kimi/kimi-k2-thinking",
            fallbacks=["gemini/gemini-3.1-pro-preview", "ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.3,
            num_predict=2048,
        ),
        "planning": ModelAssignment(
            model="kimi/kimi-k2-thinking",
            fallbacks=["gemini/gemini-3.1-pro-preview", "openrouter/meta-llama/llama-4-maverick", "ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.3,
            num_predict=4096,
        ),
        "complexity_complex": ModelAssignment(
            model="kimi/kimi-k2-thinking",
            fallbacks=["gemini/gemini-3.1-pro-preview", "ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.3,
            num_predict=4096,
        ),
        "prompt_grading_heavy": ModelAssignment(
            model="kimi/kimi-k2-thinking",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.6,
            num_predict=2048,
        ),
        # -- Tier 3b: Non-reasoning paid (K2-0905 $0.60/$2.50, no thinking overhead) --
        "structured_output": ModelAssignment(
            model="kimi/kimi-k2-0905-preview",
            fallbacks=["gemini/gemini-3.1-pro-preview", "ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.1,
            num_predict=4096,
        ),
        "extraction": ModelAssignment(
            model="kimi/kimi-k2-0905-preview",
            fallbacks=["gemini/gemini-3.1-pro-preview", "ollama/qwen3.6:35b-a3b-q8_0"],
            temperature=0.2,
            num_predict=4096,
        ),
        # -- Character content pipeline --
        "character_content_review_final": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7", "kimi/kimi-k2-0905-preview"],
            temperature=0.3,
            num_predict=2048,
        ),
        "character_content_review_escalated": ModelAssignment(
            model="minimax/MiniMax-M2.7",
            fallbacks=["kimi/kimi-k2-0905-preview"],
            temperature=0.3,
            num_predict=2048,
        ),
        "character_hook_regen": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.7,
            num_predict=512,
        ),
        "character_research": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.3,
            num_predict=4096,
        ),
        # -- Planner complexity tiers --
        "complexity_simple": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.3,
            num_predict=2048,
        ),
        "complexity_moderate": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.3,
            num_predict=2048,
        ),
        # -- Council of Agents (provider diversity per role) --
        "council_ceo": ModelAssignment(
            model="kimi/kimi-k2-thinking",
            fallbacks=["gemini/gemini-3.1-pro-preview"],
            temperature=0.3,
            num_predict=2048,
        ),
        "council_researcher": ModelAssignment(
            model="kimi/kimi-k2-thinking",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.7,
            num_predict=2048,
        ),
        "council_analyst": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.3,
            num_predict=2048,
        ),
        "council_validator": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.3,
            num_predict=2048,
        ),
        # -- AI Company agents (K2 plans, Ollama executes) --
        "agent_ceo": ModelAssignment(
            model="kimi/kimi-k2-thinking",
            fallbacks=["gemini/gemini-3.1-pro-preview"],
            temperature=0.7,
            num_predict=4096,
        ),
        "agent_researcher_plan": ModelAssignment(
            model="kimi/kimi-k2-thinking",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.7,
            num_predict=4096,
        ),
        "agent_researcher_execute": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.7,
            num_predict=4096,
        ),
        "agent_analyst": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.3,
            num_predict=4096,
        ),
        "agent_engineer": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.2,
            num_predict=4096,
        ),
        "agent_validator": ModelAssignment(
            model="ollama/qwen3.6:35b-a3b-q8_0",
            fallbacks=["minimax/MiniMax-M2.7"],
            temperature=0.3,
            num_predict=4096,
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
