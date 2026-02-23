"""
QA Verification models for automated quality checks.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class CheckCategory(str, Enum):
    SERVICE_HEALTH = "service_health"
    DOCKER_HEALTH = "docker_health"
    DOCKER_BUILD = "docker_build"
    FRONTEND_BUILD = "frontend_build"
    TYPESCRIPT = "typescript"
    BROWSER = "browser"
    API = "api"
    LOGS = "logs"


class QACheckResult(BaseModel):
    """Result of a single verification check."""
    category: CheckCategory
    name: str
    status: CheckStatus
    duration_seconds: float = 0.0
    details: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class QAReport(BaseModel):
    """Complete QA verification report with all check results."""
    report_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    trigger: str  # manual | scheduled | legion_swarm
    environment: str = "unknown"  # docker | host

    # Overall
    overall_status: CheckStatus = CheckStatus.PASSED
    can_deploy: bool = False
    blocking_issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # Individual checks
    checks: List[QACheckResult] = Field(default_factory=list)

    # Counts
    total_checks: int = 0
    passed_count: int = 0
    failed_count: int = 0
    warning_count: int = 0

    # Legion integration
    legion_tasks_created: List[int] = Field(default_factory=list)


class QAStatusSummary(BaseModel):
    """Lightweight status for quick polling."""
    status: str
    can_deploy: bool = False
    report_id: Optional[str] = None
    completed_at: Optional[datetime] = None
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    blocking_issues_count: int = 0
