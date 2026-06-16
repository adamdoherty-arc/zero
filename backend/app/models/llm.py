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
      - "vllm/qwen3-chat" → Ollama provider
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
    default_model: str = "bifrost/vllm-local/qwen3-chat"
    # These defaults mirror the Fix-117 (2026-06-16) runtime router_config.json:
    # local vLLM via the Bifrost qwen3-chat gateway alias as primary, Groq as a
    # best-effort fallback. An empty fallbacks list inherits
    # LLMRouter._DEFAULT_FALLBACKS ([vllm-local, groq]) at resolution time.
    # Gemini was dropped (shared GEMINI_API_KEY is 401-dead) and Kimi/MiniMax
    # chains were removed earlier — Kimi is ADA's lane and MiniMax rejects
    # Bifrost-routed calls (400). Re-add gemini here once the key is restored.
    task_assignments: Dict[str, ModelAssignment] = Field(default_factory=lambda: {
        # -- Tier 1: Local (vLLM via Bifrost gateway) --
        "coding": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.2,
            num_predict=4096,
        ),
        "workflow": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            temperature=0.7,
            num_predict=4096,
        ),
        # -- Tier 2: Local-first utility tasks with cloud fallback --
        "analysis": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.1,
            num_predict=2048,
        ),
        "chat": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.7,
            num_predict=2048,
        ),
        "classification": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.0,
            num_predict=200,
        ),
        "summarization": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.1,
            num_predict=1024,
        ),
        "prompt_grading": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.2,
            num_predict=1024,
        ),
        # -- Tier 3: Planning & complex reasoning (local vLLM primary, Groq fallback;
        #    Fix-117: was Gemini Flash primary, but the shared GEMINI_API_KEY is
        #    401-dead — restore the key + re-point these here to re-enable it) --
        "research": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.3,
            num_predict=2048,
        ),
        "planning": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.3,
            num_predict=4096,
        ),
        "complexity_complex": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.3,
            num_predict=4096,
        ),
        "prompt_grading_heavy": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.6,
            num_predict=2048,
        ),
        # -- Tier 3b: Structured output (local primary, Groq fallback) --
        "structured_output": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.1,
            num_predict=4096,
        ),
        "extraction": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.2,
            num_predict=4096,
        ),
        # -- Character content pipeline --
        "character_content_review_final": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.3,
            num_predict=2048,
        ),
        "character_content_review_escalated": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.3,
            num_predict=2048,
        ),
        "character_hook_regen": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.7,
            num_predict=512,
        ),
        "character_research": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.3,
            num_predict=4096,
        ),
        # -- Planner complexity tiers --
        "complexity_simple": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.3,
            num_predict=2048,
        ),
        "complexity_moderate": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.3,
            num_predict=2048,
        ),
        # -- Council of Agents (provider diversity per role) --
        "council_ceo": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.3,
            num_predict=2048,
        ),
        "council_researcher": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.7,
            num_predict=2048,
        ),
        "council_analyst": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.3,
            num_predict=2048,
        ),
        "council_validator": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.3,
            num_predict=2048,
        ),
        # -- AI Company agents (local vLLM plans + executes; Fix-117: CEO/researcher_plan
        #    were Gemini-primary but the key is 401-dead — local carries it) --
        "agent_ceo": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.7,
            num_predict=4096,
        ),
        "agent_researcher_plan": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=["bifrost/groq/openai/gpt-oss-120b"],
            temperature=0.7,
            num_predict=4096,
        ),
        "agent_researcher_execute": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.7,
            num_predict=4096,
        ),
        "agent_analyst": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.3,
            num_predict=4096,
        ),
        "agent_engineer": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
            temperature=0.2,
            num_predict=4096,
        ),
        "agent_validator": ModelAssignment(
            model="bifrost/vllm-local/qwen3-chat",
            fallbacks=[],
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
