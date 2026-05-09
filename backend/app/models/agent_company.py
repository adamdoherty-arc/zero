"""
AI Company data models.
Models for agent roles, agent tasks, experiments, council decisions, and deep research.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentTaskType(str, Enum):
    RESEARCH = "research"
    ANALYSIS = "analysis"
    VALIDATION = "validation"
    IMPLEMENTATION = "implementation"
    IDEATION = "ideation"
    SYNTHESIS = "synthesis"
    PLANNING = "planning"


class AgentTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DELEGATED = "delegated"
    NEEDS_REVIEW = "needs_review"


class ExperimentType(str, Enum):
    BENCHMARK = "benchmark"
    VALIDATION = "validation"
    AB_TEST = "ab_test"
    PROTOTYPE = "prototype"


class ExperimentStatus(str, Enum):
    DESIGNED = "designed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CouncilDecisionStatus(str, Enum):
    PROPOSED = "proposed"
    VOTING = "voting"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class DeepResearchStatus(str, Enum):
    PENDING = "pending"
    OUTLINING = "outlining"
    RESEARCHING = "researching"
    SYNTHESIZING = "synthesizing"
    VALIDATING = "validating"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Agent Roles
# ---------------------------------------------------------------------------

class AgentRole(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    system_prompt: str
    llm_provider: str
    llm_model: str
    llm_temperature: float = 0.7
    execution_llm_provider: Optional[str] = None
    execution_llm_model: Optional[str] = None
    delegation_rules: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Agent Tasks
# ---------------------------------------------------------------------------

class AgentTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    task_type: AgentTaskType = AgentTaskType.RESEARCH
    assigned_role: str = "ceo"
    priority: int = Field(3, ge=1, le=5)
    context: Dict[str, Any] = Field(default_factory=dict)
    parent_task_id: Optional[str] = None
    project_id: Optional[str] = None


class AgentTask(BaseModel):
    id: str
    project_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    task_type: str
    assigned_role: str
    status: AgentTaskStatus = AgentTaskStatus.PENDING
    priority: int = 3
    dependencies: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    parent_task_id: Optional[str] = None
    cost_usd: float = 0.0
    error: Optional[str] = None
    lease_id: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    attempt_count: int = 0
    last_heartbeat_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

class ExperimentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    hypothesis: str = Field(..., min_length=1)
    experiment_type: ExperimentType = ExperimentType.VALIDATION
    parameters: Dict[str, Any] = Field(default_factory=dict)
    linked_idea_id: Optional[str] = None
    linked_research_id: Optional[str] = None


class Experiment(BaseModel):
    id: str
    title: str
    hypothesis: str
    methodology: Optional[str] = None
    experiment_type: str
    status: ExperimentStatus = ExperimentStatus.DESIGNED
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    results: Optional[Dict[str, Any]] = None
    conclusion: Optional[str] = None
    linked_idea_id: Optional[str] = None
    linked_research_id: Optional[str] = None
    created_by_role: Optional[str] = None
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Council Decisions
# ---------------------------------------------------------------------------

class CouncilProposal(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    context: Dict[str, Any] = Field(default_factory=dict)
    proposer_role: str = "ceo"


class CouncilVote(BaseModel):
    role: str
    position: str  # "approve", "reject", "needs_revision"
    reasoning: str
    confidence: float = Field(50.0, ge=0, le=100)


class CouncilDecision(BaseModel):
    id: str
    topic: str
    context: Dict[str, Any] = Field(default_factory=dict)
    proposer_role: Optional[str] = None
    rounds: List[Dict[str, Any]] = Field(default_factory=list)
    votes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    decision: Optional[str] = None
    confidence_score: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Deep Research
# ---------------------------------------------------------------------------

class DeepResearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    perspectives: List[str] = Field(
        default_factory=lambda: ["technical", "business", "competitive"]
    )
    max_cost_usd: float = Field(0.30, ge=0.01, le=5.0)


class DeepResearchReport(BaseModel):
    id: str
    query: str
    status: str = "pending"
    outline: Optional[Dict[str, Any]] = None
    perspectives: List[str] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    sections: Dict[str, Any] = Field(default_factory=dict)
    report_markdown: Optional[str] = None
    executive_summary: Optional[str] = None
    cost_usd: float = 0.0
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Stats / Dashboard
# ---------------------------------------------------------------------------

class AiCompanyStats(BaseModel):
    total_tasks: int = 0
    tasks_by_status: Dict[str, int] = Field(default_factory=dict)
    tasks_by_role: Dict[str, int] = Field(default_factory=dict)
    total_experiments: int = 0
    experiments_by_status: Dict[str, int] = Field(default_factory=dict)
    total_council_decisions: int = 0
    total_research_reports: int = 0
    total_cost_usd: float = 0.0
    cost_by_role: Dict[str, float] = Field(default_factory=dict)
