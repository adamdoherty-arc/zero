"""
GitHub integration service.
Handles GitHub API operations for project synchronization.
"""

import os
import re
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from functools import lru_cache
import httpx
import structlog

from app.models.project import Project, ProjectUpdate
from app.models.task import Task, TaskCreate, TaskCategory, TaskPriority, TaskSource
from app.infrastructure.config import get_settings

logger = structlog.get_logger()


class GitHubService:
    """Service for GitHub API integration."""

    def __init__(self):
        self.token = os.getenv("GH_TOKEN")
        self.base_url = "https://api.github.com"
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "ZERO-Assistant",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=30.0
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def parse_repo_url(self, url: str) -> Optional[Tuple[str, str]]:
        """Parse owner/repo from GitHub URL.

        Returns:
            Tuple of (owner, repo) or None if URL is invalid
        """
        if not url:
            return None

        patterns = [
            r'github\.com[:/]([^/]+)/([^/\.]+)',
            r'github\.com[:/]([^/]+)/([^/]+)\.git',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                owner = match.group(1)
                repo = match.group(2).replace('.git', '')
                return (owner, repo)

        return None

    async def get_repo_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """Get repository metadata from GitHub API.

        Returns:
            Repository info including stars, forks, default branch, etc.
        """
        client = await self._get_client()

        try:
            response = await client.get(f"/repos/{owner}/{repo}")
            response.raise_for_status()
            data = response.json()

            return {
                "name": data.get("name"),
                "full_name": data.get("full_name"),
                "description": data.get("description"),
                "default_branch": data.get("default_branch"),
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "open_issues_count": data.get("open_issues_count", 0),
                "language": data.get("language"),
                "topics": data.get("topics", []),
                "html_url": data.get("html_url"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "pushed_at": data.get("pushed_at"),
            }
        except httpx.HTTPStatusError as e:
            logger.error("GitHub API error", status=e.response.status_code, owner=owner, repo=repo)
            raise
        except Exception as e:
            logger.error("GitHub API error", error=str(e), owner=owner, repo=repo)
            raise

    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """List repository issues.

        Args:
            owner: Repository owner
            repo: Repository name
            state: Issue state (open, closed, all)
            per_page: Number of issues per page

        Returns:
            List of issue dictionaries
        """
        client = await self._get_client()

        try:
            response = await client.get(
                f"/repos/{owner}/{repo}/issues",
                params={
                    "state": state,
                    "per_page": per_page,
                    "sort": "updated",
                    "direction": "desc"
                }
            )
            response.raise_for_status()
            issues = response.json()

            # Filter out pull requests (they also appear in issues endpoint)
            return [
                {
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "body": issue.get("body", "")[:500],  # Truncate body
                    "state": issue.get("state"),
                    "labels": [l.get("name") for l in issue.get("labels", [])],
                    "assignees": [a.get("login") for a in issue.get("assignees", [])],
                    "created_at": issue.get("created_at"),
                    "updated_at": issue.get("updated_at"),
                    "html_url": issue.get("html_url"),
                    "user": issue.get("user", {}).get("login"),
                }
                for issue in issues
                if "pull_request" not in issue  # Exclude PRs
            ]
        except httpx.HTTPStatusError as e:
            logger.error("GitHub API error listing issues", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("GitHub API error", error=str(e))
            raise

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """List repository pull requests.

        Args:
            owner: Repository owner
            repo: Repository name
            state: PR state (open, closed, all)
            per_page: Number of PRs per page

        Returns:
            List of PR dictionaries
        """
        client = await self._get_client()

        try:
            response = await client.get(
                f"/repos/{owner}/{repo}/pulls",
                params={
                    "state": state,
                    "per_page": per_page,
                    "sort": "updated",
                    "direction": "desc"
                }
            )
            response.raise_for_status()
            prs = response.json()

            return [
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "body": pr.get("body", "")[:500],  # Truncate body
                    "state": pr.get("state"),
                    "draft": pr.get("draft", False),
                    "head_branch": pr.get("head", {}).get("ref"),
                    "base_branch": pr.get("base", {}).get("ref"),
                    "created_at": pr.get("created_at"),
                    "updated_at": pr.get("updated_at"),
                    "html_url": pr.get("html_url"),
                    "user": pr.get("user", {}).get("login"),
                    "mergeable_state": pr.get("mergeable_state"),
                    "labels": [l.get("name") for l in pr.get("labels", [])],
                }
                for pr in prs
            ]
        except httpx.HTTPStatusError as e:
            logger.error("GitHub API error listing PRs", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("GitHub API error", error=str(e))
            raise

    async def sync_project(self, project: Project) -> Dict[str, Any]:
        """Sync GitHub data for a project.

        Fetches repo info, issues, and PRs and updates project metadata.

        Args:
            project: Project to sync

        Returns:
            Sync result with counts and any errors
        """
        if not project.github_owner or not project.github_repo:
            raise ValueError("Project has no GitHub configuration")

        owner = project.github_owner
        repo = project.github_repo

        result = {
            "synced_at": datetime.utcnow().isoformat(),
            "repo_info": None,
            "issues_count": 0,
            "prs_count": 0,
            "issues": [],
            "prs": [],
            "errors": []
        }

        try:
            # Fetch repo info
            repo_info = await self.get_repo_info(owner, repo)
            result["repo_info"] = repo_info
        except Exception as e:
            result["errors"].append(f"Failed to fetch repo info: {str(e)}")

        try:
            # Fetch open issues
            if project.github_sync_issues:
                issues = await self.list_issues(owner, repo, state="open")
                result["issues"] = issues
                result["issues_count"] = len(issues)
        except Exception as e:
            result["errors"].append(f"Failed to fetch issues: {str(e)}")

        try:
            # Fetch open PRs
            if project.github_sync_prs:
                prs = await self.list_pull_requests(owner, repo, state="open")
                result["prs"] = prs
                result["prs_count"] = len(prs)
        except Exception as e:
            result["errors"].append(f"Failed to fetch PRs: {str(e)}")

        logger.info(
            "GitHub sync completed",
            project_id=project.id,
            owner=owner,
            repo=repo,
            issues=result["issues_count"],
            prs=result["prs_count"],
            errors=len(result["errors"])
        )

        return result

    def issue_to_task_create(
        self,
        issue: Dict[str, Any],
        project_id: str,
        sprint_id: Optional[str] = None
    ) -> TaskCreate:
        """Convert a GitHub issue to a TaskCreate object.

        Args:
            issue: GitHub issue dictionary
            project_id: Project ID to associate task with
            sprint_id: Optional sprint ID

        Returns:
            TaskCreate object ready for task service
        """
        # Determine priority from labels
        priority = TaskPriority.MEDIUM
        labels = [l.lower() for l in issue.get("labels", [])]

        if "critical" in labels or "urgent" in labels or "p0" in labels:
            priority = TaskPriority.CRITICAL
        elif "high" in labels or "p1" in labels or "important" in labels:
            priority = TaskPriority.HIGH
        elif "low" in labels or "p3" in labels or "minor" in labels:
            priority = TaskPriority.LOW

        # Determine category from labels
        category = TaskCategory.FEATURE
        if "bug" in labels or "bugfix" in labels:
            category = TaskCategory.BUG
        elif "enhancement" in labels or "improvement" in labels:
            category = TaskCategory.ENHANCEMENT
        elif "documentation" in labels or "docs" in labels:
            category = TaskCategory.DOCUMENTATION
        elif "chore" in labels or "maintenance" in labels:
            category = TaskCategory.CHORE

        # Build description with link to GitHub
        description = issue.get("body", "") or ""
        if issue.get("html_url"):
            description = f"GitHub Issue: {issue['html_url']}\n\n{description}"

        return TaskCreate(
            title=f"[GH#{issue['number']}] {issue['title']}",
            description=description[:2000],  # Limit description length
            category=category,
            priority=priority,
            points=2,  # Default story points
            sprint_id=sprint_id,
            project_id=project_id,
            source=TaskSource.ENHANCEMENT_ENGINE,
            tags=issue.get("labels", [])[:5],  # Limit tags
        )

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: Optional[str] = None,
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create a new GitHub issue.

        Args:
            owner: Repository owner
            repo: Repository name
            title: Issue title
            body: Issue body/description
            labels: List of label names

        Returns:
            Created issue data
        """
        client = await self._get_client()

        payload = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels

        try:
            response = await client.post(
                f"/repos/{owner}/{repo}/issues",
                json=payload
            )
            response.raise_for_status()
            issue = response.json()

            logger.info(
                "GitHub issue created",
                owner=owner,
                repo=repo,
                issue_number=issue.get("number")
            )

            return {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "html_url": issue.get("html_url"),
                "state": issue.get("state"),
            }
        except httpx.HTTPStatusError as e:
            logger.error("Failed to create GitHub issue", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("Failed to create GitHub issue", error=str(e))
            raise

    async def task_to_issue(
        self,
        task: Task,
        owner: str,
        repo: str
    ) -> Dict[str, Any]:
        """Create a GitHub issue from a task.

        Args:
            task: Task to convert
            owner: Repository owner
            repo: Repository name

        Returns:
            Created issue data
        """
        # Map task category to labels
        labels = []
        if task.category == TaskCategory.BUG:
            labels.append("bug")
        elif task.category == TaskCategory.FEATURE:
            labels.append("enhancement")
        elif task.category == TaskCategory.DOCUMENTATION:
            labels.append("documentation")

        # Add priority label
        if task.priority == TaskPriority.CRITICAL:
            labels.append("critical")
        elif task.priority == TaskPriority.HIGH:
            labels.append("high-priority")

        body = task.description or ""
        body += f"\n\n---\nCreated from ZERO task: {task.id}"

        return await self.create_issue(
            owner=owner,
            repo=repo,
            title=task.title,
            body=body,
            labels=labels
        )


@lru_cache()
def get_github_service() -> GitHubService:
    """Get cached GitHub service instance."""
    return GitHubService()
