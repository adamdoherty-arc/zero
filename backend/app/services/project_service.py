"""
Project management service.
Handles project CRUD operations, scanning, and context retrieval.
"""

import os
import re
import subprocess
from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache
from pathlib import Path
import structlog

from app.models.project import (
    Project, ProjectCreate, ProjectUpdate, ProjectType, ProjectStatus,
    ProjectScanConfig, ProjectScanResult
)
from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_sprints_path

logger = structlog.get_logger()


class ProjectService:
    """Service for project management operations."""

    def __init__(self):
        self.storage = JsonStorage(get_sprints_path())
        self._projects_file = "projects.json"

    async def _load_data(self) -> Dict[str, Any]:
        """Load projects data from storage."""
        return await self.storage.read(self._projects_file)

    async def _save_data(self, data: Dict[str, Any]) -> bool:
        """Save projects data to storage."""
        return await self.storage.write(self._projects_file, data)

    def _normalize_project_data(self, project_data: Dict) -> Dict:
        """Normalize project data from storage format to Pydantic model format."""
        scan_config_data = project_data.get("scanConfig", {})
        scan_config = ProjectScanConfig(
            enabled=scan_config_data.get("enabled", True),
            scan_todos=scan_config_data.get("scanTodos", True),
            scan_errors=scan_config_data.get("scanErrors", True),
            scan_tests=scan_config_data.get("scanTests", True),
            exclude_patterns=scan_config_data.get("excludePatterns", ProjectScanConfig().exclude_patterns),
            include_extensions=scan_config_data.get("includeExtensions", ProjectScanConfig().include_extensions),
            max_file_size_kb=scan_config_data.get("maxFileSizeKb", 500),
        )

        last_scan_data = project_data.get("lastScan")
        last_scan = None
        if last_scan_data:
            last_scan = ProjectScanResult(
                scanned_at=datetime.fromisoformat(last_scan_data["scannedAt"]),
                files_scanned=last_scan_data.get("filesScanned", 0),
                signals_found=last_scan_data.get("signalsFound", 0),
                errors=last_scan_data.get("errors", []),
                summary=last_scan_data.get("summary", {}),
            )

        return {
            "id": project_data.get("id"),
            "name": project_data.get("name"),
            "description": project_data.get("description"),
            "path": project_data.get("path"),
            "project_type": project_data.get("projectType", "local"),
            "status": project_data.get("status", "active"),
            "scan_config": scan_config,
            "tags": project_data.get("tags", []),
            "last_scan": last_scan,
            "task_count": project_data.get("taskCount", 0),
            "open_signals": project_data.get("openSignals", 0),
            "git_remote": project_data.get("gitRemote"),
            "git_branch": project_data.get("gitBranch"),
            "last_commit_hash": project_data.get("lastCommitHash"),
            "last_commit_message": project_data.get("lastCommitMessage"),
            # GitHub Integration
            "github_repo_url": project_data.get("githubRepoUrl"),
            "github_owner": project_data.get("githubOwner"),
            "github_repo": project_data.get("githubRepo"),
            "github_default_branch": project_data.get("githubDefaultBranch"),
            "github_sync_enabled": project_data.get("githubSyncEnabled", False),
            "github_last_sync": project_data.get("githubLastSync"),
            "github_sync_issues": project_data.get("githubSyncIssues", True),
            "github_sync_prs": project_data.get("githubSyncPrs", True),
            "github_open_issues": project_data.get("githubOpenIssues", 0),
            "github_open_prs": project_data.get("githubOpenPrs", 0),
            "github_stars": project_data.get("githubStars", 0),
            "github_forks": project_data.get("githubForks", 0),
            "created_at": project_data.get("createdAt"),
            "updated_at": project_data.get("updatedAt"),
        }

    def _to_storage_format(self, project: Project) -> Dict:
        """Convert project to storage format (camelCase)."""
        scan_config = {
            "enabled": project.scan_config.enabled,
            "scanTodos": project.scan_config.scan_todos,
            "scanErrors": project.scan_config.scan_errors,
            "scanTests": project.scan_config.scan_tests,
            "excludePatterns": project.scan_config.exclude_patterns,
            "includeExtensions": project.scan_config.include_extensions,
            "maxFileSizeKb": project.scan_config.max_file_size_kb,
        }

        last_scan = None
        if project.last_scan:
            last_scan = {
                "scannedAt": project.last_scan.scanned_at.isoformat(),
                "filesScanned": project.last_scan.files_scanned,
                "signalsFound": project.last_scan.signals_found,
                "errors": project.last_scan.errors,
                "summary": project.last_scan.summary,
            }

        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "path": project.path,
            "projectType": project.project_type.value if hasattr(project.project_type, 'value') else project.project_type,
            "status": project.status.value if hasattr(project.status, 'value') else project.status,
            "scanConfig": scan_config,
            "tags": project.tags,
            "lastScan": last_scan,
            "taskCount": project.task_count,
            "openSignals": project.open_signals,
            "gitRemote": project.git_remote,
            "gitBranch": project.git_branch,
            "lastCommitHash": project.last_commit_hash,
            "lastCommitMessage": project.last_commit_message,
            # GitHub Integration
            "githubRepoUrl": project.github_repo_url,
            "githubOwner": project.github_owner,
            "githubRepo": project.github_repo,
            "githubDefaultBranch": project.github_default_branch,
            "githubSyncEnabled": project.github_sync_enabled,
            "githubLastSync": project.github_last_sync.isoformat() if project.github_last_sync else None,
            "githubSyncIssues": project.github_sync_issues,
            "githubSyncPrs": project.github_sync_prs,
            "githubOpenIssues": project.github_open_issues,
            "githubOpenPrs": project.github_open_prs,
            "githubStars": project.github_stars,
            "githubForks": project.github_forks,
            "createdAt": project.created_at.isoformat() if project.created_at else None,
            "updatedAt": project.updated_at.isoformat() if project.updated_at else None,
        }

    async def list_projects(self, status: Optional[ProjectStatus] = None) -> List[Project]:
        """Get all projects with optional status filter."""
        data = await self._load_data()
        projects_data = data.get("projects", [])

        projects = []
        for p in projects_data:
            if status and p.get("status") != status.value:
                continue
            normalized = self._normalize_project_data(p)
            projects.append(Project(**normalized))

        return projects

    async def get_project(self, project_id: str) -> Optional[Project]:
        """Get project by ID."""
        data = await self._load_data()
        for p in data.get("projects", []):
            if p["id"] == project_id:
                normalized = self._normalize_project_data(p)
                return Project(**normalized)
        return None

    async def create_project(self, project_data: ProjectCreate) -> Project:
        """Register a new project."""
        data = await self._load_data()

        # Generate new project ID
        next_id = data.get("nextProjectId", 1)
        project_id = f"proj-{next_id}"

        now = datetime.utcnow()

        # Detect project type and git info
        project_type = project_data.project_type
        git_remote = None
        git_branch = None
        last_commit_hash = None
        last_commit_message = None

        path = project_data.path
        if os.path.isdir(path):
            git_info = self._get_git_info(path)
            if git_info:
                if project_type == ProjectType.LOCAL:
                    project_type = ProjectType.GIT
                git_remote = git_info.get("remote")
                git_branch = git_info.get("branch")
                last_commit_hash = git_info.get("commit_hash")
                last_commit_message = git_info.get("commit_message")

        # Parse GitHub URL if provided
        github_owner = None
        github_repo = None
        github_repo_url = project_data.github_repo_url
        if github_repo_url:
            parsed = self._parse_github_url(github_repo_url)
            if parsed:
                github_owner = parsed.get("owner")
                github_repo = parsed.get("repo")
                if project_type == ProjectType.LOCAL:
                    project_type = ProjectType.GITHUB

        project = Project(
            id=project_id,
            name=project_data.name,
            description=project_data.description,
            path=path,
            project_type=project_type,
            status=ProjectStatus.ACTIVE,
            scan_config=project_data.scan_config or ProjectScanConfig(),
            tags=project_data.tags,
            git_remote=git_remote,
            git_branch=git_branch,
            last_commit_hash=last_commit_hash,
            last_commit_message=last_commit_message,
            github_repo_url=github_repo_url,
            github_owner=github_owner,
            github_repo=github_repo,
            github_sync_enabled=project_data.github_sync_enabled,
            created_at=now
        )

        # Add to projects list
        projects = data.get("projects", [])
        projects.append(self._to_storage_format(project))

        # Update data
        data["projects"] = projects
        data["nextProjectId"] = next_id + 1

        await self._save_data(data)

        logger.info("Project created", project_id=project_id, name=project.name, path=path)
        return project

    async def update_project(self, project_id: str, updates: ProjectUpdate) -> Optional[Project]:
        """Update a project."""
        data = await self._load_data()
        projects = data.get("projects", [])

        for i, p in enumerate(projects):
            if p["id"] == project_id:
                # Apply updates
                update_dict = updates.model_dump(exclude_unset=True)
                for key, value in update_dict.items():
                    if value is not None:
                        # Convert snake_case to camelCase for storage
                        storage_key = self._to_camel_case(key)

                        # Handle enums
                        if hasattr(value, 'value'):
                            value = value.value

                        # Handle nested scan_config
                        if key == "scan_config" and value:
                            value = {
                                "enabled": value.enabled,
                                "scanTodos": value.scan_todos,
                                "scanErrors": value.scan_errors,
                                "scanTests": value.scan_tests,
                                "excludePatterns": value.exclude_patterns,
                                "includeExtensions": value.include_extensions,
                                "maxFileSizeKb": value.max_file_size_kb,
                            }
                            storage_key = "scanConfig"

                        p[storage_key] = value

                p["updatedAt"] = datetime.utcnow().isoformat()
                projects[i] = p
                data["projects"] = projects
                await self._save_data(data)

                logger.info("Project updated", project_id=project_id)
                normalized = self._normalize_project_data(p)
                return Project(**normalized)

        return None

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project."""
        data = await self._load_data()
        projects = data.get("projects", [])

        for i, p in enumerate(projects):
            if p["id"] == project_id:
                del projects[i]
                data["projects"] = projects
                await self._save_data(data)

                logger.info("Project deleted", project_id=project_id)
                return True

        return False

    async def scan_project(self, project_id: str) -> ProjectScanResult:
        """Scan a project for enhancement signals."""
        project = await self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        if not os.path.isdir(project.path):
            raise ValueError(f"Project path does not exist: {project.path}")

        # Update status to scanning
        await self.update_project(project_id, ProjectUpdate(status=ProjectStatus.SCANNING))

        now = datetime.utcnow()
        files_scanned = 0
        signals_found = 0
        errors: List[str] = []
        summary: Dict[str, int] = {"todo": 0, "fixme": 0, "hack": 0, "bug": 0}

        try:
            for root, dirs, files in os.walk(project.path):
                # Skip excluded directories
                dirs[:] = [d for d in dirs if not self._should_exclude(d, project.scan_config.exclude_patterns)]

                for filename in files:
                    # Check extension
                    ext = os.path.splitext(filename)[1]
                    if ext not in project.scan_config.include_extensions:
                        continue

                    filepath = os.path.join(root, filename)

                    # Check file size
                    try:
                        if os.path.getsize(filepath) > project.scan_config.max_file_size_kb * 1024:
                            continue
                    except OSError:
                        continue

                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            files_scanned += 1

                            # Scan for signals
                            if project.scan_config.scan_todos:
                                todos = len(re.findall(r'\bTODO\b', content, re.IGNORECASE))
                                fixmes = len(re.findall(r'\bFIXME\b', content, re.IGNORECASE))
                                hacks = len(re.findall(r'\bHACK\b', content, re.IGNORECASE))
                                bugs = len(re.findall(r'\bBUG\b', content, re.IGNORECASE))

                                summary["todo"] += todos
                                summary["fixme"] += fixmes
                                summary["hack"] += hacks
                                summary["bug"] += bugs
                                signals_found += todos + fixmes + hacks + bugs

                    except Exception as e:
                        errors.append(f"Error reading {filepath}: {str(e)}")

        except Exception as e:
            errors.append(f"Scan error: {str(e)}")

        # Create scan result
        scan_result = ProjectScanResult(
            scanned_at=now,
            files_scanned=files_scanned,
            signals_found=signals_found,
            errors=errors[:10],  # Limit errors
            summary=summary
        )

        # Update project with scan result
        data = await self._load_data()
        projects = data.get("projects", [])
        for i, p in enumerate(projects):
            if p["id"] == project_id:
                p["lastScan"] = {
                    "scannedAt": scan_result.scanned_at.isoformat(),
                    "filesScanned": scan_result.files_scanned,
                    "signalsFound": scan_result.signals_found,
                    "errors": scan_result.errors,
                    "summary": scan_result.summary,
                }
                p["openSignals"] = signals_found
                p["status"] = ProjectStatus.ACTIVE.value
                p["updatedAt"] = now.isoformat()
                projects[i] = p
                break

        data["projects"] = projects
        await self._save_data(data)

        logger.info(
            "Project scanned",
            project_id=project_id,
            files_scanned=files_scanned,
            signals_found=signals_found
        )

        return scan_result

    async def get_project_context(self, project_id: str) -> Dict[str, Any]:
        """Get project context for Claude (CLAUDE.md, structure, etc.)."""
        project = await self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        context: Dict[str, Any] = {
            "project": {
                "id": project.id,
                "name": project.name,
                "path": project.path,
                "type": project.project_type.value,
            },
            "claude_md": None,
            "readme": None,
            "structure": [],
            "git": None,
        }

        if not os.path.isdir(project.path):
            return context

        # Read CLAUDE.md if exists
        claude_md_path = os.path.join(project.path, "CLAUDE.md")
        if os.path.isfile(claude_md_path):
            try:
                with open(claude_md_path, 'r', encoding='utf-8') as f:
                    context["claude_md"] = f.read()
            except Exception:
                pass

        # Read README if exists
        for readme_name in ["README.md", "readme.md", "README.txt", "README"]:
            readme_path = os.path.join(project.path, readme_name)
            if os.path.isfile(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8') as f:
                        context["readme"] = f.read()[:5000]  # Limit size
                    break
                except Exception:
                    pass

        # Get directory structure (limited depth)
        context["structure"] = self._get_directory_structure(project.path, max_depth=2)

        # Get git info
        git_info = self._get_git_info(project.path)
        if git_info:
            context["git"] = git_info

        return context

    async def get_project_tasks(self, project_id: str) -> List[Any]:
        """Get all tasks associated with a project."""
        from app.services.task_service import get_task_service
        task_service = get_task_service()
        return await task_service.list_tasks(project_id=project_id)

    async def update_task_count(self, project_id: str) -> None:
        """Update the task count for a project."""
        tasks = await self.get_project_tasks(project_id)
        data = await self._load_data()
        projects = data.get("projects", [])

        for i, p in enumerate(projects):
            if p["id"] == project_id:
                p["taskCount"] = len(tasks)
                projects[i] = p
                break

        data["projects"] = projects
        await self._save_data(data)

    def _get_git_info(self, path: str) -> Optional[Dict[str, str]]:
        """Get git information for a directory."""
        git_dir = os.path.join(path, ".git")
        if not os.path.isdir(git_dir):
            return None

        info = {}
        try:
            # Get remote
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=path, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                info["remote"] = result.stdout.strip()

            # Get branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=path, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                info["branch"] = result.stdout.strip()

            # Get last commit
            result = subprocess.run(
                ["git", "log", "-1", "--format=%H %s"],
                cwd=path, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(" ", 1)
                if len(parts) >= 1:
                    info["commit_hash"] = parts[0][:8]
                if len(parts) >= 2:
                    info["commit_message"] = parts[1][:100]

        except Exception:
            pass

        return info if info else None

    def _get_directory_structure(self, path: str, max_depth: int = 2) -> List[str]:
        """Get directory structure as a list of paths."""
        structure = []
        path_obj = Path(path)

        def walk(current: Path, depth: int):
            if depth > max_depth:
                return

            try:
                items = sorted(current.iterdir())
                for item in items:
                    # Skip hidden and excluded
                    if item.name.startswith('.'):
                        continue
                    if item.name in ['node_modules', '__pycache__', 'dist', 'build', '.venv', 'venv']:
                        continue

                    rel_path = item.relative_to(path_obj)
                    if item.is_dir():
                        structure.append(f"{rel_path}/")
                        walk(item, depth + 1)
                    else:
                        structure.append(str(rel_path))
            except PermissionError:
                pass

        walk(path_obj, 0)
        return structure[:100]  # Limit

    def _should_exclude(self, name: str, patterns: List[str]) -> bool:
        """Check if a name matches exclude patterns."""
        return name in patterns or name.startswith('.')

    def _to_camel_case(self, snake_str: str) -> str:
        """Convert snake_case to camelCase."""
        components = snake_str.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])

    def _parse_github_url(self, url: str) -> Optional[Dict[str, str]]:
        """Parse GitHub URL to extract owner and repo name."""
        if not url:
            return None

        # Handle various GitHub URL formats
        patterns = [
            r'github\.com[:/]([^/]+)/([^/\.]+)',  # https://github.com/owner/repo or git@github.com:owner/repo
            r'github\.com[:/]([^/]+)/([^/]+)\.git',  # with .git suffix
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return {
                    "owner": match.group(1),
                    "repo": match.group(2).replace('.git', '')
                }

        return None


@lru_cache()
def get_project_service() -> ProjectService:
    """Get cached project service instance."""
    return ProjectService()
