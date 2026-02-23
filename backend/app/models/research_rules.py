"""
Research Rules Engine data models.
Dynamic rules for scoring, categorization, routing, and auto-actions on research findings.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


class RuleType(str, Enum):
    """Type of research rule."""
    SCORING = "scoring"
    CATEGORIZATION = "categorization"
    ROUTING = "routing"
    SCHEDULING = "scheduling"
    AUTO_ACTION = "auto_action"


class RuleCreatedBy(str, Enum):
    """Who created the rule."""
    SYSTEM = "system"
    USER = "user"
    LEARNED = "learned"


class RuleCondition(BaseModel):
    """Composable condition for rule evaluation.

    Conditions are evaluated against a research finding context.
    Use `operator` to combine multiple sub-conditions.
    """
    operator: Literal["and", "or"] = "and"

    # Text matching (any keyword triggers match)
    title_contains: Optional[List[str]] = None
    snippet_contains: Optional[List[str]] = None
    url_contains: Optional[List[str]] = None
    url_domain: Optional[List[str]] = None

    # Score thresholds
    min_composite_score: Optional[float] = None
    min_relevance_score: Optional[float] = None
    max_composite_score: Optional[float] = None

    # Context matching
    category_is: Optional[List[str]] = None
    topic_tags_include: Optional[List[str]] = None
    source_engine: Optional[List[str]] = None

    # Time-based conditions
    time_of_day: Optional[Dict[str, str]] = None  # {"after": "08:00", "before": "12:00"}
    day_of_week: Optional[List[int]] = None  # 0=Mon, 6=Sun

    # Nested sub-conditions
    conditions: Optional[List["RuleCondition"]] = None


class RuleAction(BaseModel):
    """Actions to execute when a rule fires."""
    # Scoring adjustments (added to existing scores)
    boost_relevance: Optional[float] = None
    boost_novelty: Optional[float] = None
    boost_actionability: Optional[float] = None
    set_composite_weight: Optional[Dict[str, float]] = None  # override weight ratios

    # Categorization
    set_category: Optional[str] = None  # finding category (tool, pattern, etc.)
    set_category_id: Optional[str] = None  # knowledge category slug
    add_tags: Optional[List[str]] = None

    # Auto-actions
    auto_create_task: Optional[bool] = None
    auto_dismiss: Optional[bool] = None
    notify_discord: Optional[bool] = None
    priority_label: Optional[str] = None  # "high", "medium", "low"

    # Routing
    assign_to_topic: Optional[str] = None


# --- CRUD Models ---

class ResearchRuleCreate(BaseModel):
    """Schema for creating a research rule."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    rule_type: RuleType
    conditions: RuleCondition
    actions: RuleAction
    priority: int = Field(100, ge=0, le=1000)
    enabled: bool = True
    category_id: Optional[str] = None


class ResearchRuleUpdate(BaseModel):
    """Schema for updating a research rule."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    rule_type: Optional[RuleType] = None
    conditions: Optional[RuleCondition] = None
    actions: Optional[RuleAction] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    enabled: Optional[bool] = None
    category_id: Optional[str] = None


class ResearchRule(BaseModel):
    """Full research rule model."""
    id: str
    name: str
    description: Optional[str] = None
    rule_type: RuleType
    conditions: RuleCondition
    actions: RuleAction
    priority: int = 100
    enabled: bool = True
    category_id: Optional[str] = None

    # Self-improvement tracking
    times_fired: int = 0
    times_useful: int = 0
    effectiveness_score: float = 50.0

    # Audit
    created_by: str = "system"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RuleEvaluationResult(BaseModel):
    """Result of evaluating rules against a finding."""
    matched_rule_ids: List[str] = Field(default_factory=list)
    merged_actions: RuleAction = Field(default_factory=RuleAction)
    rules_evaluated: int = 0
    rules_matched: int = 0


class RuleStats(BaseModel):
    """Statistics about the rules engine."""
    total_rules: int = 0
    enabled_rules: int = 0
    by_type: Dict[str, int] = Field(default_factory=dict)
    by_creator: Dict[str, int] = Field(default_factory=dict)
    top_effective: List[Dict[str, Any]] = Field(default_factory=list)
    low_effective: List[Dict[str, Any]] = Field(default_factory=list)
    total_fires: int = 0
    total_useful: int = 0


class RuleSuggestion(BaseModel):
    """LLM-suggested rule."""
    name: str
    description: str
    rule_type: RuleType
    conditions: RuleCondition
    actions: RuleAction
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
