"""
Project management service.
Handles project CRUD operations, scanning, and context retrieval.
Backed by PostgreSQL via SQLAlchemy.
"""

import json
import os
import re
import subprocess
from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache
from pathlib import Path
import structlog

from sqlalchemy import select

from app.models.project import (
    Project, ProjectCreate, ProjectUpdate, ProjectType, ProjectStatus,
    ProjectScanConfig, ProjectScanResult
)
from app.infrastructure.database import get_session
from app.db.models import ProjectModel

logger = structlog.get_logger()


class ProjectService:
    """Service for project management operations."""

    # ============================================
    # ORM <-> PYDANTIC MAPPING
    # ============================================

    def _model_to_project(self, row: ProjectModel) -> Project:
        """Convert a ProjectModel ORM row to a Pydantic Project."""
        # Reconstruct scan_config from JSONB
        scan_cfg_raw = row.scan_config or {}
        scan_config = ProjectScanConfig(
            enabled=scan_cfg_raw.get("enabled", True),
            scan_todos=scan_cfg_raw.get("scan_todos", scan_cfg_raw.get("scanTodos", True)),
            scan_errors=scan_cfg_raw.get("scan_errors", scan_cfg_raw.get("scanErrors", True)),
            scan_tests=scan_cfg_raw.get("scan_tests", scan_cfg_raw.get("scanTests", True)),
            exclude_patterns=scan_cfg_raw.get(
                "exclude_patterns",
                scan_cfg_raw.get("excludePatterns", ProjectScanConfig().exclude_patterns),
            ),
            include_extensions=scan_cfg_raw.get(
                "include_extensions",
                scan_cfg_raw.get("includeExtensions", ProjectScanConfig().include_extensions),
            ),
            max_file_size_kb=scan_cfg_raw.get(
                "max_file_size_kb",
                scan_cfg_raw.get("maxFileSizeKb", 500),
            ),
        )

        # Reconstruct last_scan from JSONB
        last_scan = None
        ls_raw = row.last_scan
        if ls_raw:
            scanned_at = ls_raw.get("scanned_at") or ls_raw.get("scannedAt")
            if scanned_at:
                last_scan = ProjectScanResult(
                    scanned_at=datetime.fromisoformat(str(scanned_at)) if isinstance(scanned_at, str) else scanned_at,
                    files_scanned=ls_raw.get("files_scanned", ls_raw.get("filesScanned", 0)),
                    signals_found=ls_raw.get("signals_found", ls_raw.get("signalsFound", 0)),
                    errors=ls_raw.get("errors", []),
                    summary=ls_raw.get("summary", {}),
                )

        return Project(
            id=row.id,
            name=row.name,
            description=row.description,
            path=row.path,
            project_type=ProjectType(row.project_type) if row.project_type else ProjectType.LOCAL,
            status=ProjectStatus(row.status) if row.status else ProjectStatus.ACTIVE,
            scan_config=scan_config,
            tags=row.tags or [],
            last_scan=last_scan,
            task_count=row.task_count or 0,
            open_signals=row.open_signals or 0,
            git_remote=row.git_remote,
            git_branch=row.git_branch,
            last_commit_hash=row.last_commit_hash,
            last_commit_message=row.last_commit_message,
            github_repo_url=row.github_repo_url,
            github_owner=row.github_owner,
            github_repo=row.github_repo,
            github_default_branch=row.github_default_branch,
            github_sync_enabled=row.github_sync_enabled or False,
            github_last_sync=row.github_last_sync,
            github_sync_issues=row.github_sync_issues if row.github_sync_issues is not None else True,
            github_sync_prs=row.github_sync_prs if row.github_sync_prs is not None else True,
            github_open_issues=row.github_open_issues or 0,
            github_open_prs=row.github_open_prs or 0,
            github_stars=row.github_stars or 0,
            github_forks=row.github_forks or 0,
            created_at=row.created_at or datetime.utcnow(),
            updated_at=row.updated_at,
        )

    def _scan_config_to_dict(self, scan_config: ProjectScanConfig) -> Dict:
        """Serialize ProjectScanConfig to a plain dict for JSONB storage."""
        return {
            "enabled": scan_config.enabled,
            "scan_todos": scan_config.scan_todos,
            "scan_errors": scan_config.scan_errors,
            "scan_tests": scan_config.scan_tests,
            "exclude_patterns": scan_config.exclude_patterns,
            "include_extensions": scan_config.include_extensions,
            "max_file_size_kb": scan_config.max_file_size_kb,
        }

    # ============================================
    # CRUD
    # ============================================

    async def list_projects(self, status: Optional[ProjectStatus] = None) -> List[Project]:
        """Get all projects with optional status filter."""
        async with get_session() as session:
            stmt = select(ProjectModel)
            if status:
                stmt = stmt.where(ProjectModel.status == status.value)
            stmt = stmt.order_by(ProjectModel.name)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._model_to_project(r) for r in rows]

    async def get_project(self, project_id: str) -> Optional[Project]:
        """Get project by ID."""
        async with get_session() as session:
            row = await session.get(ProjectModel, project_id)
            if row is None:
                return None
            return self._model_to_project(row)

    async def create_project(self, project_data: ProjectCreate) -> Project:
        """Register a new project."""
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

        scan_config = project_data.scan_config or ProjectScanConfig()

        async with get_session() as session:
            # Generate next project ID via max existing
            stmt = select(ProjectModel.id).order_by(ProjectModel.id.desc()).limit(1)
            result = await session.execute(stmt)
            last_id = result.scalar()
            if last_id and last_id.startswith("proj-"):
                try:
                    next_num = int(last_id.split("-", 1)[1]) + 1
                except (ValueError, IndexError):
                    next_num = 1
            else:
                next_num = 1
            project_id = f"proj-{next_num}"

            row = ProjectModel(
                id=project_id,
                name=project_data.name,
                description=project_data.description,
                path=path,
                project_type=project_type.value,
                status=ProjectStatus.ACTIVE.value,
                scan_config=self._scan_config_to_dict(scan_config),
                tags=project_data.tags or [],
                git_remote=git_remote,
                git_branch=git_branch,
                last_commit_hash=last_commit_hash,
                last_commit_message=last_commit_message,
                github_repo_url=github_repo_url,
                github_owner=github_owner,
                github_repo=github_repo,
                github_sync_enabled=project_data.github_sync_enabled,
                created_at=now,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            project = self._model_to_project(row)

        logger.info("Project created", project_id=project_id, name=project.name, path=path)
        return project

    async def update_project(self, project_id: str, updates: ProjectUpdate) -> Optional[Project]:
        """Update a project."""
        async with get_session() as session:
            row = await session.get(ProjectModel, project_id)
            if row is None:
                return None

            update_dict = updates.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                if value is None:
                    continue

                # Handle enums
                if hasattr(value, "value"):
                    value = value.value

                # Handle nested scan_config
                if key == "scan_config" and isinstance(value, ProjectScanConfig):
                    row.scan_config = self._scan_config_to_dict(value)
                    continue

                if hasattr(row, key):
                    setattr(row, key, value)

            row.updated_at = datetime.utcnow()
            await session.flush()
            await session.refresh(row)
            project = self._model_to_project(row)

        logger.info("Project updated", project_id=project_id)
        return project

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project."""
        async with get_session() as session:
            row = await session.get(ProjectModel, project_id)
            if row is None:
                return False
            await session.delete(row)

        logger.info("Project deleted", project_id=project_id)
        return True

    # ============================================
    # SCANNING
    # ============================================

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

        # Persist scan result into the project row
        async with get_session() as session:
            row = await session.get(ProjectModel, project_id)
            if row:
                row.last_scan = {
                    "scanned_at": scan_result.scanned_at.isoformat(),
                    "files_scanned": scan_result.files_scanned,
                    "signals_found": scan_result.signals_found,
                    "errors": scan_result.errors,
                    "summary": scan_result.summary,
                }
                row.open_signals = signals_found
                row.status = ProjectStatus.ACTIVE.value
                row.updated_at = now

        logger.info(
            "Project scanned",
            project_id=project_id,
            files_scanned=files_scanned,
            signals_found=signals_found
        )

        return scan_result

    # ============================================
    # CONTEXT RETRIEVAL
    # ============================================

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
        async with get_session() as session:
            row = await session.get(ProjectModel, project_id)
            if row:
                row.task_count = len(tasks)
                row.updated_at = datetime.utcnow()

    # ============================================
    # UTILITY METHODS
    # ============================================

    def _get_git_info(self, path: str) -> Optional[Dict[str, str]]:
        """Get git information for a directory."""
        # Resolve symlinks and canonicalize to prevent path traversal
        try:
            canonical = os.path.realpath(path)
        except (OSError, ValueError):
            return None
        git_dir = os.path.join(canonical, ".git")
        if not os.path.isdir(git_dir):
            return None
        path = canonical

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

    def _resolve_path(self, path: str) -> str:
        """Translate a host Windows path to a container path if needed.

        Docker mounts host project dirs under /projects/<name>.
        When the API runs inside a container, C:\\code\\zero won't exist
        but /projects/zero will.
        """
        # Already a valid directory — no translation needed
        if os.path.isdir(path):
            return os.path.realpath(path)

        # Try translating common Windows patterns: C:\code\<name> or C:/code/<name>
        normalised = path.replace("\\", "/").rstrip("/")
        # Match C:/code/<project_name> (case-insensitive drive letter)
        import re as _re
        m = _re.match(r"(?i)^[a-z]:/code/([^/]+)$", normalised)
        if m:
            candidate = f"/projects/{m.group(1).lower()}"
            if os.path.isdir(candidate):
                return candidate

        return os.path.realpath(path)

    async def analyze_path(self, path: str) -> Dict[str, Any]:
        """Use Ollama to analyze a project directory and suggest metadata."""
        canonical = self._resolve_path(path)
        if not os.path.isdir(canonical):
            return {"error": f"Directory not found: {path}"}

        # Gather project signals
        folder_name = os.path.basename(canonical)
        structure = self._get_directory_structure(canonical, max_depth=2)
        git_info = self._get_git_info(canonical)

        # Read README
        readme = ""
        for name in ["README.md", "readme.md", "README.txt", "README"]:
            rp = os.path.join(canonical, name)
            if os.path.isfile(rp):
                try:
                    with open(rp, "r", encoding="utf-8") as f:
                        readme = f.read()[:2000]
                    break
                except Exception:
                    pass

        # Detect tech stack from manifest files
        manifests: Dict[str, str] = {}
        manifest_files = {
            "package.json": "package.json",
            "requirements.txt": "requirements.txt",
            "pyproject.toml": "pyproject.toml",
            "Cargo.toml": "Cargo.toml",
            "go.mod": "go.mod",
            "Gemfile": "Gemfile",
            "pom.xml": "pom.xml",
            "build.gradle": "build.gradle",
            "composer.json": "composer.json",
        }
        for fname, label in manifest_files.items():
            fp = os.path.join(canonical, fname)
            if os.path.isfile(fp):
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        manifests[label] = f.read()[:1000]
                except Exception:
                    pass

        # Build context for LLM
        context_parts = [f"Folder name: {folder_name}"]
        if git_info:
            context_parts.append(f"Git remote: {git_info.get('remote', 'none')}")
            context_parts.append(f"Branch: {git_info.get('branch', 'unknown')}")
        if readme:
            context_parts.append(f"README (first 2000 chars):\n{readme}")
        if manifests:
            for mname, mcontent in manifests.items():
                context_parts.append(f"{mname}:\n{mcontent}")
        if structure:
            context_parts.append(f"Directory tree:\n" + "\n".join(structure[:50]))

        context_str = "\n\n".join(context_parts)

        # Call Ollama
        try:
            from app.infrastructure.ollama_client import get_ollama_client
            client = get_ollama_client()

            system_prompt = (
                "You are a project analyzer. Given information about a software project, "
                "return ONLY a JSON object with these fields:\n"
                '- "name": short project name (2-4 words max)\n'
                '- "description": one-sentence description of what the project does\n'
                '- "project_type": one of "local", "git", "github", "gitlab"\n'
                '- "tech_stack": array of technologies/frameworks used (e.g. ["Python", "FastAPI", "React"])\n'
                '- "tags": array of 2-5 descriptive tags (e.g. ["web-app", "api", "fullstack"])\n'
                "No markdown, no explanation, ONLY the JSON object."
            )

            response = await client.chat_safe(
                f"Analyze this project:\n\n{context_str}",
                system=system_prompt,
                task_type="analysis",
                temperature=0.0,
                num_predict=500,
                max_retries=1,
            )

            if response and "{" in response:
                json_str = response[response.index("{"):response.rindex("}") + 1]
                data = json.loads(json_str)

                # Auto-detect project type from git info
                if git_info:
                    remote = git_info.get("remote", "")
                    if "github.com" in remote:
                        data["project_type"] = "github"
                    elif "gitlab" in remote:
                        data["project_type"] = "gitlab"
                    else:
                        data["project_type"] = "git"
                    data["github_url"] = remote if "github.com" in remote else None

                return {
                    "name": data.get("name", folder_name),
                    "description": data.get("description", ""),
                    "project_type": data.get("project_type", "local"),
                    "tech_stack": data.get("tech_stack", []),
                    "tags": data.get("tags", []),
                    "github_url": data.get("github_url"),
                    "git_info": git_info,
                    "ai_generated": True,
                }

        except Exception as e:
            logger.warning("ai_analyze_failed", error=str(e))

        # Fallback: heuristic analysis without LLM
        tech_stack = []
        tags = []
        project_type = "local"
        if "package.json" in manifests:
            tech_stack.append("Node.js")
            try:
                pkg = json.loads(manifests["package.json"])
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "react" in deps:
                    tech_stack.append("React")
                if "vue" in deps:
                    tech_stack.append("Vue")
                if "next" in deps:
                    tech_stack.append("Next.js")
                if "typescript" in deps:
                    tech_stack.append("TypeScript")
            except Exception:
                pass
        if "requirements.txt" in manifests:
            tech_stack.append("Python")
            content = manifests["requirements.txt"].lower()
            if "fastapi" in content:
                tech_stack.append("FastAPI")
            if "django" in content:
                tech_stack.append("Django")
            if "flask" in content:
                tech_stack.append("Flask")
        if "Cargo.toml" in manifests:
            tech_stack.append("Rust")
        if "go.mod" in manifests:
            tech_stack.append("Go")

        if git_info:
            remote = git_info.get("remote", "")
            if "github.com" in remote:
                project_type = "github"
            else:
                project_type = "git"

        return {
            "name": folder_name,
            "description": "",
            "project_type": project_type,
            "tech_stack": tech_stack,
            "tags": tags,
            "github_url": git_info.get("remote") if git_info and "github.com" in git_info.get("remote", "") else None,
            "git_info": git_info,
            "ai_generated": False,
        }

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
