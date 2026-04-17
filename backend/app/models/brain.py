"""
Zero Brain data models.

Models for episodic memory, outcomes, prompt evolution, benchmarks, and learning cycles.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class BrainDomain(str, Enum):
    CONTENT = "content"
    RESEARCH = "research"
    EXPERIMENT = "experiment"
    TASK = "task"
    MONEY = "money"
    SYSTEM = "system"


class MemoryNamespace(str, Enum):
    CONTENT = "content"
    RESEARCH = "research"
    TASK = "task"
    SYSTEM = "system"
    GENERAL = "general"


class BenchmarkDimension(str, Enum):
    CONTENT_QUALITY = "content_quality"
    RESEARCH_DEPTH = "research_depth"
    LEARNING_VELOCITY = "learning_velocity"
    EXPERIMENT_RIGOR = "experiment_rigor"
    SYSTEM_HEALTH = "system_health"
    TASK_EXECUTION = "task_execution"
    COST_EFFICIENCY = "cost_efficiency"
    COMMUNICATION_QUALITY = "communication_quality"
    CALIBRATION_ACCURACY = "calibration_accuracy"
    KNOWLEDGE_GROWTH = "knowledge_growth"


# --- Episodic Memory ---

class EpisodicMemoryCreate(BaseModel):
    namespace: MemoryNamespace = MemoryNamespace.GENERAL
    content: str = Field(..., min_length=1)
    source_type: str
    source_id: Optional[str] = None
    importance: float = Field(50.0, ge=0, le=100)
    tags: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)


class EpisodicMemory(BaseModel):
    id: str
    namespace: str
    content: str
    source_type: str
    source_id: Optional[str] = None
    importance: float = 50.0
    tags: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    expires_at: Optional[datetime] = None
    created_at: datetime


class MemorySearchResult(BaseModel):
    memory: EpisodicMemory
    similarity: float


# --- Outcome Records ---

class OutcomeRecordCreate(BaseModel):
    domain: BrainDomain
    action_type: str
    action_id: Optional[str] = None
    strategy_used: Optional[str] = None
    predicted_score: Optional[float] = None
    actual_score: Optional[float] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    learnings: Optional[str] = None


class OutcomeRecord(BaseModel):
    id: str
    domain: str
    action_type: str
    action_id: Optional[str] = None
    strategy_used: Optional[str] = None
    predicted_score: Optional[float] = None
    actual_score: Optional[float] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    learnings: Optional[str] = None
    created_at: datetime


# --- Prompt Variants ---

class PromptVariantCreate(BaseModel):
    task_type: str
    variant_name: str
    prompt_template: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    is_baseline: bool = False


class PromptVariant(BaseModel):
    id: str
    task_type: str
    variant_name: str
    prompt_template: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    success_count: int = 0
    failure_count: int = 0
    total_uses: int = 0
    avg_score: float = 50.0
    is_active: bool = True
    is_baseline: bool = False
    parent_id: Optional[str] = None
    generation: int = 1
    created_at: datetime
    last_used_at: Optional[datetime] = None


# --- Prompt Runs (full request/response capture) ---

class PromptRunCreate(BaseModel):
    variant_id: Optional[str] = None
    task_type: str
    source: str
    source_id: Optional[str] = None
    provider: str
    model: str
    system_prompt: Optional[str] = None
    user_prompt: str
    rendered_variables: Dict[str, Any] = Field(default_factory=dict)
    response_text: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    success: bool = True
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class PromptRun(BaseModel):
    id: str
    variant_id: Optional[str] = None
    task_type: str
    source: str
    source_id: Optional[str] = None
    provider: str
    model: str
    system_prompt: Optional[str] = None
    user_prompt: str
    rendered_variables: Dict[str, Any] = Field(default_factory=dict)
    response_text: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    success: bool = True
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    quality_score: Optional[float] = None
    quality_flags: List[str] = Field(default_factory=list)
    quality_summary: Optional[str] = None
    grader_model: Optional[str] = None
    graded_at: Optional[datetime] = None
    outcome_score: Optional[float] = None
    outcome_recorded_at: Optional[datetime] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PromptRunGrade(BaseModel):
    """Result of LLM-as-judge grading for a prompt run."""
    quality_score: float = Field(..., ge=0, le=100)
    quality_flags: List[str] = Field(default_factory=list)
    quality_summary: str = ""
    grader_model: str = ""


# --- Benchmark ---

class BenchmarkScore(BaseModel):
    dimension: str
    score: float
    weight: float
    details: Dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime


class BenchmarkSnapshot(BaseModel):
    overall_score: float
    dimension_scores: Dict[str, float]
    weakest_dimension: str
    improvement_action: Optional[str] = None
    snapshot_at: datetime


class BrainStatus(BaseModel):
    overall_score: float
    dimension_scores: Dict[str, BenchmarkScore]
    weakest_dimension: str
    total_memories: int
    total_outcomes: int
    total_prompt_variants: int
    active_experiments: int
    last_benchmark_at: Optional[datetime] = None
    last_learning_cycle_at: Optional[datetime] = None


# --- Learning Cycle ---

class LearningCycle(BaseModel):
    id: str
    cycle_type: str
    status: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    results: Dict[str, Any] = Field(default_factory=dict)
    improvements: List[Dict[str, Any]] = Field(default_factory=list)
    cost_usd: float = 0.0
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


# --- Content Experiment ---

class ContentExperimentCreate(BaseModel):
    name: str
    hypothesis: str
    experiment_type: str
    control_config: Dict[str, Any]
    variant_config: Dict[str, Any]
    sample_size_target: int = 10


class ContentExperiment(BaseModel):
    id: str
    name: str
    hypothesis: str
    experiment_type: str
    control_config: Dict[str, Any]
    variant_config: Dict[str, Any]
    status: str = "active"
    sample_size_target: int = 10
    control_results: List[Dict[str, Any]] = Field(default_factory=list)
    variant_results: List[Dict[str, Any]] = Field(default_factory=list)
    conclusion: Optional[str] = None
    winner: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


# --- Strategy Metrics ---

class StrategyMetrics(BaseModel):
    strategy: str
    domain: str
    total_uses: int
    win_rate: float
    avg_score: float
    calibration_error: float
    sample_size: int


class CalibrationBucket(BaseModel):
    range_label: str
    count: int
    avg_predicted: float
    avg_actual: float
    mae: float
