"""
Project management API endpoints.
Handles project registration, scanning, and context retrieval.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
import structlog

from app.models.project import (
    Project, ProjectCreate, ProjectUpdate, ProjectStatus, ProjectScanResult
)
from app.models.task import Task
from app.services.project_service import get_project_service
from app.services.github_service import get_github_service
from pydantic import BaseModel


class GitHubConnectRequest(BaseModel):
    """Request to connect a project to GitHub."""
    github_url: str
    sync_issues: bool = True
    sync_prs: bool = True
    auto_sync: bool = False


class AnalyzePathRequest(BaseModel):
    """Request to analyze a project path with AI."""
    path: str


router = APIRouter()
logger = structlog.get_logger()


@router.post("/analyze")
async def analyze_project_path(request: AnalyzePathRequest) -> Dict[str, Any]:
    """Use AI to analyze a project directory and suggest metadata."""
    service = get_project_service()
    return await service.analyze_path(request.path)


@router.get("", response_model=List[Project])
async def list_projects(
    status: Optional[ProjectStatus] = Query(None, description="Filter by status")
):
    """Get all registered projects."""
    service = get_project_service()
    return await service.list_projects(status=status)


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str):
    """Get project by ID."""
    service = get_project_service()
    project = await service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", response_model=Project)
async def create_project(project_data: ProjectCreate):
    """Register a new project."""
    service = get_project_service()
    return await service.create_project(project_data)


@router.patch("/{project_id}", response_model=Project)
async def update_project(project_id: str, updates: ProjectUpdate):
    """Update a project."""
    service = get_project_service()
    project = await service.update_project(project_id, updates)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """Delete a project."""
    service = get_project_service()
    deleted = await service.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": project_id}


@router.post("/{project_id}/scan", response_model=ProjectScanResult)
async def scan_project(project_id: str):
    """Scan a project for enhancement signals (TODO, FIXME, etc.)."""
    service = get_project_service()
    try:
        return await service.scan_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{project_id}/context")
async def get_project_context(project_id: str) -> Dict[str, Any]:
    """Get project context for Claude (CLAUDE.md, README, structure, git info)."""
    service = get_project_service()
    try:
        return await service.get_project_context(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{project_id}/tasks", response_model=List[Task])
async def get_project_tasks(project_id: str):
    """Get all tasks associated with a project."""
    service = get_project_service()
    project = await service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return await service.get_project_tasks(project_id)


# ============================================================================
# GitHub Integration Endpoints
# ============================================================================

@router.post("/{project_id}/github/connect")
async def connect_github(project_id: str, request: GitHubConnectRequest) -> Dict[str, Any]:
    """Connect a project to a GitHub repository.

    Parses the GitHub URL, fetches repo metadata, and updates project settings.
    """
    project_service = get_project_service()
    github_service = get_github_service()

    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Parse GitHub URL
    parsed = github_service.parse_repo_url(request.github_url)
    if not parsed:
        raise HTTPException(status_code=400, detail="Invalid GitHub URL format")

    owner, repo = parsed

    # Fetch repo info from GitHub
    try:
        repo_info = await github_service.get_repo_info(owner, repo)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to access GitHub repo: {str(e)}")

    # Update project with GitHub info
    from datetime import datetime
    updates = ProjectUpdate(
        github_repo_url=request.github_url,
        github_sync_enabled=request.auto_sync,
        github_sync_issues=request.sync_issues,
        github_sync_prs=request.sync_prs,
    )

    # Need to update additional fields directly
    data = await project_service._load_data()
    projects = data.get("projects", [])
    for i, p in enumerate(projects):
        if p["id"] == project_id:
            p["github_repo_url"] = request.github_url
            p["github_owner"] = owner
            p["github_repo"] = repo
            p["github_default_branch"] = repo_info.get("default_branch")
            p["github_sync_enabled"] = request.auto_sync
            p["github_sync_issues"] = request.sync_issues
            p["github_sync_prs"] = request.sync_prs
            p["github_stars"] = repo_info.get("stars", 0)
            p["github_forks"] = repo_info.get("forks", 0)
            p["github_open_issues"] = repo_info.get("open_issues_count", 0)
            p["updated_at"] = datetime.utcnow().isoformat()
            projects[i] = p
            break

    data["projects"] = projects
    await project_service._save_data(data)

    logger.info("GitHub connected", project_id=project_id, owner=owner, repo=repo)

    return {
        "status": "connected",
        "project_id": project_id,
        "github_owner": owner,
        "github_repo": repo,
        "repo_info": repo_info
    }


@router.post("/{project_id}/github/sync")
async def sync_github(project_id: str) -> Dict[str, Any]:
    """Sync GitHub issues and PRs with the project.

    Fetches latest issues and PRs from GitHub and updates project metadata.
    """
    project_service = get_project_service()
    github_service = get_github_service()

    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.github_owner or not project.github_repo:
        raise HTTPException(status_code=400, detail="Project has no GitHub connection")

    # Perform sync
    try:
        sync_result = await github_service.sync_project(project)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

    # Update project with sync results
    from datetime import datetime
    data = await project_service._load_data()
    projects = data.get("projects", [])
    for i, p in enumerate(projects):
        if p["id"] == project_id:
            p["github_last_sync"] = datetime.utcnow().isoformat()
            if sync_result.get("repo_info"):
                p["github_stars"] = sync_result["repo_info"].get("stars", 0)
                p["github_forks"] = sync_result["repo_info"].get("forks", 0)
            p["github_open_issues"] = sync_result.get("issues_count", 0)
            p["github_open_prs"] = sync_result.get("prs_count", 0)
            p["updated_at"] = datetime.utcnow().isoformat()
            projects[i] = p
            break

    data["projects"] = projects
    await project_service._save_data(data)

    return {
        "status": "synced",
        "project_id": project_id,
        "synced_at": sync_result.get("synced_at"),
        "issues_count": sync_result.get("issues_count"),
        "prs_count": sync_result.get("prs_count"),
        "issues": sync_result.get("issues", []),
        "prs": sync_result.get("prs", []),
        "errors": sync_result.get("errors", [])
    }


@router.get("/{project_id}/github/status")
async def github_status(project_id: str) -> Dict[str, Any]:
    """Get GitHub sync status and statistics for a project."""
    project_service = get_project_service()
    project = await project_service.get_project(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.github_repo_url:
        return {
            "connected": False,
            "project_id": project_id
        }

    return {
        "connected": True,
        "project_id": project_id,
        "github_url": project.github_repo_url,
        "github_owner": project.github_owner,
        "github_repo": project.github_repo,
        "default_branch": project.github_default_branch,
        "sync_enabled": project.github_sync_enabled,
        "sync_issues": project.github_sync_issues,
        "sync_prs": project.github_sync_prs,
        "last_sync": project.github_last_sync.isoformat() if project.github_last_sync else None,
        "stats": {
            "open_issues": project.github_open_issues,
            "open_prs": project.github_open_prs,
            "stars": project.github_stars,
            "forks": project.github_forks
        }
    }


@router.post("/{project_id}/github/disconnect")
async def disconnect_github(project_id: str) -> Dict[str, Any]:
    """Disconnect GitHub from a project."""
    project_service = get_project_service()
    project = await project_service.get_project(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.github_repo_url:
        raise HTTPException(status_code=400, detail="Project has no GitHub connection")

    # Clear GitHub fields
    from datetime import datetime
    data = await project_service._load_data()
    projects = data.get("projects", [])
    for i, p in enumerate(projects):
        if p["id"] == project_id:
            p["github_repo_url"] = None
            p["github_owner"] = None
            p["github_repo"] = None
            p["github_default_branch"] = None
            p["github_sync_enabled"] = False
            p["github_last_sync"] = None
            p["github_sync_issues"] = True
            p["github_sync_prs"] = True
            p["github_open_issues"] = 0
            p["github_open_prs"] = 0
            p["github_stars"] = 0
            p["github_forks"] = 0
            p["updated_at"] = datetime.utcnow().isoformat()
            projects[i] = p
            break

    data["projects"] = projects
    await project_service._save_data(data)

    logger.info("GitHub disconnected", project_id=project_id)

    return {
        "status": "disconnected",
        "project_id": project_id
    }


@router.post("/{project_id}/github/sync-to-tasks")
async def sync_github_issues_to_tasks(
    project_id: str,
    sprint_id: Optional[str] = Query(None, description="Sprint to add tasks to")
) -> Dict[str, Any]:
    """Convert GitHub issues to sprint tasks.

    Creates tasks from open GitHub issues that don't already have corresponding tasks.
    """
    project_service = get_project_service()
    github_service = get_github_service()

    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.github_owner or not project.github_repo:
        raise HTTPException(status_code=400, detail="Project has no GitHub connection")

    # Fetch issues
    try:
        issues = await github_service.list_issues(
            project.github_owner,
            project.github_repo,
            state="open"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch issues: {str(e)}")

    # Import task service
    from app.services.task_service import get_task_service
    task_service = get_task_service()

    # Get existing tasks to avoid duplicates
    existing_tasks = await task_service.list_tasks(project_id=project_id)
    existing_gh_numbers = set()
    for task in existing_tasks:
        # Extract GH# from title if present
        import re
        match = re.search(r'\[GH#(\d+)\]', task.title)
        if match:
            existing_gh_numbers.add(int(match.group(1)))

    # Create tasks for new issues
    created_tasks = []
    for issue in issues:
        if issue["number"] in existing_gh_numbers:
            continue

        task_create = github_service.issue_to_task_create(
            issue,
            project_id=project_id,
            sprint_id=sprint_id
        )

        try:
            task = await task_service.create_task(task_create)
            created_tasks.append({
                "task_id": task.id,
                "title": task.title,
                "github_issue": issue["number"]
            })
        except Exception as e:
            logger.error("Failed to create task from issue", issue=issue["number"], error=str(e))

    # Update project task count
    await project_service.update_task_count(project_id)

    return {
        "status": "synced",
        "project_id": project_id,
        "issues_processed": len(issues),
        "tasks_created": len(created_tasks),
        "created_tasks": created_tasks
    }
