"""
Project data models.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict, Field


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
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = True
    scan_todos: bool = Field(True, alias="scanTodos")
    scan_errors: bool = Field(True, alias="scanErrors")
    scan_tests: bool = Field(True, alias="scanTests")
    exclude_patterns: List[str] = Field(
        default=["node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv"],
        alias="excludePatterns"
    )
    include_extensions: List[str] = Field(
        default=[".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".json"],
        alias="includeExtensions"
    )
    max_file_size_kb: int = Field(500, alias="maxFileSizeKb")


class ProjectScanResult(BaseModel):
    """Results from a project scan."""
    model_config = ConfigDict(populate_by_name=True)

    scanned_at: datetime = Field(alias="scannedAt")
    files_scanned: int = Field(alias="filesScanned")
    signals_found: int = Field(alias="signalsFound")
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
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: Optional[str] = None
    path: str
    project_type: ProjectType = Field(ProjectType.LOCAL, alias="projectType")
    status: ProjectStatus = ProjectStatus.ACTIVE
    scan_config: ProjectScanConfig = Field(default_factory=ProjectScanConfig, alias="scanConfig")
    tags: List[str] = Field(default_factory=list)

    # Scan metadata
    last_scan: Optional[ProjectScanResult] = Field(None, alias="lastScan")
    task_count: int = Field(0, alias="taskCount")
    open_signals: int = Field(0, alias="openSignals")

    # Git metadata
    git_remote: Optional[str] = Field(None, alias="gitRemote")
    git_branch: Optional[str] = Field(None, alias="gitBranch")
    last_commit_hash: Optional[str] = Field(None, alias="lastCommitHash")
    last_commit_message: Optional[str] = Field(None, alias="lastCommitMessage")

    # GitHub Integration
    github_repo_url: Optional[str] = Field(None, alias="githubRepoUrl")
    github_owner: Optional[str] = Field(None, alias="githubOwner")
    github_repo: Optional[str] = Field(None, alias="githubRepo")
    github_default_branch: Optional[str] = Field(None, alias="githubDefaultBranch")
    github_sync_enabled: bool = Field(False, alias="githubSyncEnabled")
    github_last_sync: Optional[datetime] = Field(None, alias="githubLastSync")
    github_sync_issues: bool = Field(True, alias="githubSyncIssues")
    github_sync_prs: bool = Field(True, alias="githubSyncPrs")
    github_open_issues: int = Field(0, alias="githubOpenIssues")
    github_open_prs: int = Field(0, alias="githubOpenPrs")
    github_stars: int = Field(0, alias="githubStars")
    github_forks: int = Field(0, alias="githubForks")

    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
