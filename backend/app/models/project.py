"""
Project data models.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    """Type of code project."""
    LOCAL = "local"
    GIT = "git"
    GITHUB = "github"
    GITLAB = "gitlab"


class ProjectStatus(str, Enum):
    """Project lifecycle status."""
    ACTIVE = "active"
    ARCHIVED = "archived"
    SCANNING = "scanning"


class ProjectScanConfig(BaseModel):
    """Configuration for project scanning."""

    enabled: bool = True
    scan_todos: bool = True
    scan_errors: bool = True
    scan_tests: bool = True
    exclude_patterns: List[str] = Field(
        default=["node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv"]
    )
    include_extensions: List[str] = Field(
        default=[".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".json"]
    )
    max_file_size_kb: int = 500


class ProjectScanResult(BaseModel):
    """Results from a project scan."""

    scanned_at: datetime
    files_scanned: int
    signals_found: int
    errors: List[str] = Field(default_factory=list)
    summary: Dict[str, int] = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    """Schema for registering a new project."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    path: str = Field(..., description="Local path or repository URL")
    project_type: ProjectType = ProjectType.LOCAL
    scan_config: Optional[ProjectScanConfig] = None
    tags: List[str] = Field(default_factory=list)
    # GitHub Integration
    github_repo_url: Optional[str] = Field(None, description="GitHub repository URL")
    github_sync_enabled: bool = False


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    path: Optional[str] = None
    status: Optional[ProjectStatus] = None
    scan_config: Optional[ProjectScanConfig] = None
    tags: Optional[List[str]] = None
    # GitHub Integration
    github_repo_url: Optional[str] = None
    github_sync_enabled: Optional[bool] = None
    github_sync_issues: Optional[bool] = None
    github_sync_prs: Optional[bool] = None


class Project(BaseModel):
    """Full project model."""

    id: str
    name: str
    description: Optional[str] = None
    path: str
    project_type: ProjectType = ProjectType.LOCAL
    status: ProjectStatus = ProjectStatus.ACTIVE
    scan_config: ProjectScanConfig = Field(default_factory=ProjectScanConfig)
    tags: List[str] = Field(default_factory=list)

    # Scan metadata
    last_scan: Optional[ProjectScanResult] = None
    task_count: int = 0
    open_signals: int = 0

    # Git metadata
    git_remote: Optional[str] = None
    git_branch: Optional[str] = None
    last_commit_hash: Optional[str] = None
    last_commit_message: Optional[str] = None

    # GitHub Integration
    github_repo_url: Optional[str] = None
    github_owner: Optional[str] = None
    github_repo: Optional[str] = None
    github_default_branch: Optional[str] = None
    github_sync_enabled: bool = False
    github_last_sync: Optional[datetime] = None
    github_sync_issues: bool = True
    github_sync_prs: bool = True
    github_open_issues: int = 0
    github_open_prs: int = 0
    github_stars: int = 0
    github_forks: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
