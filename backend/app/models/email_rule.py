"""
Email rule models for user-defined email automation rules.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field


class ConditionField(str, Enum):
    SENDER = "sender"
    SUBJECT = "subject"
    BODY = "body"
    CATEGORY = "category"
    HAS_ATTACHMENTS = "has_attachments"
    LABEL = "label"


class ConditionOperator(str, Enum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EXACT = "exact"
    REGEX = "regex"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"


class ActionType(str, Enum):
    ARCHIVE = "archive"
    STAR = "star"
    MARK_READ = "mark_read"
    APPLY_LABEL = "apply_label"
    NOTIFY = "notify"
    CREATE_CALENDAR_EVENT = "create_calendar_event"
    CREATE_TASK = "create_task"


class RuleCondition(BaseModel):
    """A single condition to match against an email."""
    field: ConditionField
    operator: ConditionOperator
    value: Union[str, List[str], bool]
    case_sensitive: bool = False


class ConditionsBlock(BaseModel):
    """Block of conditions with match mode."""
    match_mode: str = Field(default="all", pattern="^(all|any)$")
    conditions: List[RuleCondition] = Field(..., min_length=1)


class RuleAction(BaseModel):
    """An action to execute when a rule matches."""
    type: ActionType
    params: Dict[str, Any] = Field(default_factory=dict)


class EmailRule(BaseModel):
    """Full email rule response model."""
    id: str
    name: str
    description: Optional[str] = None
    enabled: bool = True
    priority: int = 100
    stop_after_match: bool = False
    conditions: ConditionsBlock
    actions: List[RuleAction]
    match_count: int = 0
    last_matched_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class EmailRuleCreate(BaseModel):
    """Schema for creating an email rule."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    enabled: bool = True
    priority: int = Field(default=100, ge=1, le=10000)
    stop_after_match: bool = False
    conditions: ConditionsBlock
    actions: List[RuleAction] = Field(..., min_length=1)


class EmailRuleUpdate(BaseModel):
    """Schema for updating an email rule."""
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=1, le=10000)
    stop_after_match: Optional[bool] = None
    conditions: Optional[ConditionsBlock] = None
    actions: Optional[List[RuleAction]] = None


class RuleTestRequest(BaseModel):
    """Request to test a rule against an email."""
    email_id: str
    rule: Optional[EmailRuleCreate] = None
    rule_id: Optional[str] = None


class RuleTestResult(BaseModel):
    """Result of testing a rule against an email."""
    matched: bool
    conditions_evaluated: List[Dict[str, Any]]
    actions_that_would_execute: List[RuleAction]
    email_subject: str
    email_from: str
