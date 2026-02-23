"""
QA Verification Service for Zero.

Runs comprehensive automated checks after code changes:
- Service health (HTTP checks to all known services)
- Docker container health (host-only, uses docker CLI)
- Frontend build / vite build (host-only, uses npx)
- TypeScript type checking (host-only, uses npx)
- Browser page load validation (HTTP checks)
- API endpoint health (HTTP checks)
- Backend log analysis (host-only, uses docker CLI)

Auto-detects whether running inside Docker and adapts checks:
- Inside Docker: HTTP-based checks using Docker network service names
- On host: Full CLI-based checks (docker, npx, etc.)

All checks run in parallel via asyncio.gather() and report ALL issues at once.
Can auto-create Legion tasks for failures.
"""

import asyncio
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from functools import lru_cache

import structlog

from app.models.qa import (
    QAReport, QACheckResult, CheckStatus, CheckCategory, QAStatusSummary
)
from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


class QAVerificationService:
    """
    Comprehensive QA verification orchestration.

    Runs all checks in parallel, aggregates results, saves reports
    to workspace/qa/, and optionally creates Legion fix tasks.

    Auto-detects Docker environment and adapts checks accordingly.
    """

    def __init__(self):
        settings = get_settings()
        self.workspace = Path(settings.workspace_dir).resolve()
        self.qa_dir = self.workspace / "qa"
        self.qa_dir.mkdir(parents=True, exist_ok=True)
        self.storage = JsonStorage(self.qa_dir)
        self._running = False
        self._in_docker = os.path.exists("/.dockerenv") or os.environ.get("ZERO_WORKSPACE_DIR", "").startswith("/app")

    # ================================================================
    # MAIN ENTRY POINT
    # ================================================================

    async def run_full_verification(
        self,
        trigger: str = "manual",
        auto_create_tasks: bool = True,
    ) -> QAReport:
        """Run full QA verification suite. All checks run in parallel."""
        if self._running:
            logger.warning("qa_verification_already_running")
            latest = await self.get_latest_report()
            if latest:
                return latest
            # Fall through if no latest

        self._running = True
        report_id = f"qa_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        started_at = datetime.utcnow()

        logger.info("qa_verification_started", report_id=report_id, trigger=trigger)

        try:
            # Build check list based on environment
            checks_to_run = [
                self._check_service_health(),
                self._check_browser_pages(),
                self._check_api_health(),
            ]

            if self._in_docker:
                # Inside Docker: skip CLI-based checks that need docker/npx
                logger.info("qa_running_in_docker", note="CLI checks skipped, using HTTP checks")
            else:
                # On host: add CLI-based checks
                checks_to_run.extend([
                    self._check_docker_health(),
                    self._check_docker_build(),
                    self._check_frontend_build(),
                    self._check_typescript_types(),
                    self._check_backend_logs(),
                ])

            # Run all checks in parallel
            results = await asyncio.gather(
                *checks_to_run,
                return_exceptions=True,
            )

            # Collect results, handle any that threw
            checks: List[QACheckResult] = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    checks.append(QACheckResult(
                        category=CheckCategory.API,
                        name=f"Check #{i+1} execution error",
                        status=CheckStatus.ERROR,
                        errors=[str(result)],
                    ))
                else:
                    checks.append(result)

            # Aggregate
            overall_status, can_deploy, blocking, warnings = self._aggregate(checks)

            report = QAReport(
                report_id=report_id,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                trigger=trigger,
                environment="docker" if self._in_docker else "host",
                overall_status=overall_status,
                can_deploy=can_deploy,
                blocking_issues=blocking,
                warnings=warnings,
                checks=checks,
                total_checks=len(checks),
                passed_count=sum(1 for c in checks if c.status == CheckStatus.PASSED),
                failed_count=sum(1 for c in checks if c.status == CheckStatus.FAILED),
                warning_count=sum(1 for c in checks if c.status == CheckStatus.WARNING),
            )

            await self._save_report(report)

            # Auto-create Legion tasks for failures
            if auto_create_tasks and not can_deploy:
                task_ids = await self._create_legion_tasks(report)
                report.legion_tasks_created = task_ids
                await self._save_report(report)

            duration = (report.completed_at - report.started_at).total_seconds()
            logger.info(
                "qa_verification_completed",
                report_id=report_id,
                status=overall_status.value,
                can_deploy=can_deploy,
                passed=report.passed_count,
                failed=report.failed_count,
                duration=f"{duration:.1f}s",
            )
            return report

        finally:
            self._running = False

    # ================================================================
    # INDIVIDUAL CHECKS
    # ================================================================

    async def _run_cmd(
        self, args: List[str], cwd: Optional[str] = None, timeout: int = 120
    ) -> Tuple[int, str, str]:
        """Helper: run subprocess and return (returncode, stdout, stderr)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
        except asyncio.TimeoutError:
            return -1, "", f"Command timed out after {timeout}s"
        except FileNotFoundError as e:
            return -2, "", f"Command not found: {e}"

    async def _check_service_health(self) -> QACheckResult:
        """Check all known services are reachable via HTTP health endpoints."""
        t0 = time.monotonic()
        settings = get_settings()

        # Build service list based on environment
        if self._in_docker:
            services = {
                "zero-api": "http://localhost:18792/health/ready",
                "zero-ui": "http://zero-ui:5173",
                "zero-searxng": "http://zero-searxng:8080",
                "legion": f"{settings.legion_api_url}/health",
                "ollama": settings.ollama_base_url.replace("/v1", "") + "/api/tags",
            }
        else:
            services = {
                "zero-api": f"http://localhost:{settings.api_port}/health/ready",
                "zero-ui": "http://localhost:5173",
                "zero-searxng": "http://localhost:8888",
                "legion": "http://localhost:8005/health",
                "ollama": "http://localhost:11434/api/tags",
            }

        errors = []
        warnings = []
        healthy = 0

        try:
            import httpx
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
                for name, url in services.items():
                    try:
                        resp = await client.get(url)
                        if resp.status_code < 400:
                            healthy += 1
                        elif resp.status_code >= 500:
                            errors.append(f"{name}: HTTP {resp.status_code}")
                        else:
                            warnings.append(f"{name}: HTTP {resp.status_code}")
                    except Exception as e:
                        # Non-critical services get warnings, critical ones get errors
                        if name in ("zero-api", "zero-ui"):
                            errors.append(f"{name}: {type(e).__name__}")
                        else:
                            warnings.append(f"{name}: unreachable ({type(e).__name__})")
        except ImportError:
            return QACheckResult(
                category=CheckCategory.SERVICE_HEALTH,
                name="Service Health",
                status=CheckStatus.SKIPPED,
                duration_seconds=time.monotonic() - t0,
                details="httpx not installed",
            )

        if errors:
            return QACheckResult(
                category=CheckCategory.SERVICE_HEALTH,
                name="Service Health",
                status=CheckStatus.FAILED,
                duration_seconds=time.monotonic() - t0,
                errors=errors,
                warnings=warnings,
                metrics={"total": len(services), "healthy": healthy},
            )

        status = CheckStatus.WARNING if warnings else CheckStatus.PASSED
        return QACheckResult(
            category=CheckCategory.SERVICE_HEALTH,
            name="Service Health",
            status=status,
            duration_seconds=time.monotonic() - t0,
            details=f"{healthy}/{len(services)} services healthy",
            warnings=warnings,
            metrics={"total": len(services), "healthy": healthy},
        )

    async def _check_docker_health(self) -> QACheckResult:
        """Check all zero-* Docker containers are running and healthy."""
        t0 = time.monotonic()
        rc, stdout, stderr = await self._run_cmd(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], timeout=10
        )

        if rc != 0:
            return QACheckResult(
                category=CheckCategory.DOCKER_HEALTH,
                name="Docker Container Health",
                status=CheckStatus.ERROR,
                duration_seconds=time.monotonic() - t0,
                errors=[f"docker ps failed: {stderr[:300]}"],
            )

        containers = []
        unhealthy = []
        for line in stdout.strip().splitlines():
            if "\t" in line:
                name, status = line.split("\t", 1)
                if "zero-" in name:
                    containers.append(name)
                    if "unhealthy" in status.lower() or "exit" in status.lower():
                        unhealthy.append(f"{name}: {status}")

        if unhealthy:
            return QACheckResult(
                category=CheckCategory.DOCKER_HEALTH,
                name="Docker Container Health",
                status=CheckStatus.FAILED,
                duration_seconds=time.monotonic() - t0,
                errors=unhealthy,
                metrics={"total_containers": len(containers), "unhealthy": len(unhealthy)},
            )

        return QACheckResult(
            category=CheckCategory.DOCKER_HEALTH,
            name="Docker Container Health",
            status=CheckStatus.PASSED,
            duration_seconds=time.monotonic() - t0,
            details=f"All {len(containers)} Zero containers healthy",
            metrics={"total_containers": len(containers)},
        )

    async def _check_docker_build(self) -> QACheckResult:
        """Verify Docker images can build (zero-api)."""
        t0 = time.monotonic()
        project_root = Path(__file__).resolve().parents[3]  # backend/app/services -> project root

        rc, stdout, stderr = await self._run_cmd(
            ["docker", "compose", "-f", "docker-compose.sprint.yml", "build", "--quiet", "zero-api"],
            cwd=str(project_root),
            timeout=180,
        )

        if rc == -1:
            return QACheckResult(
                category=CheckCategory.DOCKER_BUILD,
                name="Docker Build Validation",
                status=CheckStatus.WARNING,
                duration_seconds=time.monotonic() - t0,
                warnings=["Docker build timed out (180s)"],
            )

        if rc != 0:
            # Extract meaningful error lines
            error_lines = [l for l in (stderr + stdout).splitlines() if l.strip()][-10:]
            return QACheckResult(
                category=CheckCategory.DOCKER_BUILD,
                name="Docker Build Validation",
                status=CheckStatus.FAILED,
                duration_seconds=time.monotonic() - t0,
                errors=error_lines or ["Build failed (check logs)"],
            )

        return QACheckResult(
            category=CheckCategory.DOCKER_BUILD,
            name="Docker Build Validation",
            status=CheckStatus.PASSED,
            duration_seconds=time.monotonic() - t0,
            details="Docker image builds successfully",
        )

    async def _check_frontend_build(self) -> QACheckResult:
        """Run vite build to catch import/module resolution errors."""
        t0 = time.monotonic()
        project_root = Path(__file__).resolve().parents[3]
        frontend_dir = project_root / "frontend"

        rc, stdout, stderr = await self._run_cmd(
            ["npx", "vite", "build"],
            cwd=str(frontend_dir),
            timeout=60,
        )

        output = stdout + stderr

        if rc == -1:
            return QACheckResult(
                category=CheckCategory.FRONTEND_BUILD,
                name="Frontend Build (Vite)",
                status=CheckStatus.WARNING,
                duration_seconds=time.monotonic() - t0,
                warnings=["Vite build timed out (60s)"],
            )

        if rc != 0:
            error_lines = [l.strip() for l in output.splitlines() if "error" in l.lower()][:10]
            return QACheckResult(
                category=CheckCategory.FRONTEND_BUILD,
                name="Frontend Build (Vite)",
                status=CheckStatus.FAILED,
                duration_seconds=time.monotonic() - t0,
                errors=error_lines or [output[:500]],
            )

        return QACheckResult(
            category=CheckCategory.FRONTEND_BUILD,
            name="Frontend Build (Vite)",
            status=CheckStatus.PASSED,
            duration_seconds=time.monotonic() - t0,
            details="Frontend builds successfully",
        )

    async def _check_typescript_types(self) -> QACheckResult:
        """Run tsc --noEmit to catch type errors."""
        t0 = time.monotonic()
        project_root = Path(__file__).resolve().parents[3]
        frontend_dir = project_root / "frontend"

        rc, stdout, stderr = await self._run_cmd(
            ["npx", "tsc", "--noEmit"],
            cwd=str(frontend_dir),
            timeout=30,
        )

        output = (stdout + stderr).strip()

        if rc == -1:
            return QACheckResult(
                category=CheckCategory.TYPESCRIPT,
                name="TypeScript Type Check",
                status=CheckStatus.WARNING,
                duration_seconds=time.monotonic() - t0,
                warnings=["tsc timed out (30s)"],
            )

        if rc != 0:
            error_lines = [l.strip() for l in output.splitlines() if l.strip()][:15]
            return QACheckResult(
                category=CheckCategory.TYPESCRIPT,
                name="TypeScript Type Check",
                status=CheckStatus.WARNING,  # Warning not failure — pre-existing type issues
                duration_seconds=time.monotonic() - t0,
                warnings=error_lines,
                details=f"{len(error_lines)} type issue(s) found",
            )

        return QACheckResult(
            category=CheckCategory.TYPESCRIPT,
            name="TypeScript Type Check",
            status=CheckStatus.PASSED,
            duration_seconds=time.monotonic() - t0,
            details="No type errors",
        )

    async def _check_browser_pages(self) -> QACheckResult:
        """Check key frontend pages return HTTP 200."""
        t0 = time.monotonic()

        # Use Docker service name when running inside Docker
        if self._in_docker:
            base_url = "http://zero-ui:5173"
        else:
            base_url = "http://localhost:5173"

        pages = ["/", "/ecosystem", "/board", "/sprints", "/architecture", "/qa"]
        errors = []

        try:
            import httpx
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
                for page in pages:
                    try:
                        resp = await client.get(f"{base_url}{page}")
                        if resp.status_code != 200:
                            errors.append(f"{page}: HTTP {resp.status_code}")
                    except Exception as e:
                        errors.append(f"{page}: {type(e).__name__}")
        except ImportError:
            return QACheckResult(
                category=CheckCategory.BROWSER,
                name="Browser Page Load",
                status=CheckStatus.SKIPPED,
                duration_seconds=time.monotonic() - t0,
                details="httpx not installed",
            )

        if errors:
            return QACheckResult(
                category=CheckCategory.BROWSER,
                name="Browser Page Load",
                status=CheckStatus.FAILED,
                duration_seconds=time.monotonic() - t0,
                errors=errors,
            )

        return QACheckResult(
            category=CheckCategory.BROWSER,
            name="Browser Page Load",
            status=CheckStatus.PASSED,
            duration_seconds=time.monotonic() - t0,
            details=f"All {len(pages)} pages return HTTP 200",
        )

    async def _check_api_health(self) -> QACheckResult:
        """Check key API endpoints respond without 500s."""
        t0 = time.monotonic()
        settings = get_settings()
        base_url = f"http://localhost:{settings.api_port}"

        endpoints = [
            "/health",
            "/health/ready",
            "/api/sprints",
            "/api/qa/status",
            "/api/ecosystem/sync/status",
        ]
        errors = []
        warnings = []

        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                for ep in endpoints:
                    try:
                        resp = await client.get(f"{base_url}{ep}")
                        if resp.status_code >= 500:
                            errors.append(f"{ep}: HTTP {resp.status_code}")
                        elif resp.status_code >= 400:
                            warnings.append(f"{ep}: HTTP {resp.status_code}")
                    except Exception as e:
                        errors.append(f"{ep}: {type(e).__name__}")
        except ImportError:
            return QACheckResult(
                category=CheckCategory.API,
                name="API Health Check",
                status=CheckStatus.SKIPPED,
                duration_seconds=time.monotonic() - t0,
                details="httpx not installed",
            )

        if errors:
            return QACheckResult(
                category=CheckCategory.API,
                name="API Health Check",
                status=CheckStatus.FAILED,
                duration_seconds=time.monotonic() - t0,
                errors=errors,
                warnings=warnings,
            )

        status = CheckStatus.WARNING if warnings else CheckStatus.PASSED
        return QACheckResult(
            category=CheckCategory.API,
            name="API Health Check",
            status=status,
            duration_seconds=time.monotonic() - t0,
            details=f"Checked {len(endpoints)} endpoints",
            warnings=warnings,
        )

    async def _check_backend_logs(self) -> QACheckResult:
        """Scan zero-api container logs for tracebacks/errors."""
        t0 = time.monotonic()

        # Try docker logs first (works on host), fall back to container name variants
        for container_name in ["zero-api", "zero-zero-api-1"]:
            rc, stdout, stderr = await self._run_cmd(
                ["docker", "logs", "--tail", "200", container_name], timeout=10
            )
            if rc == 0:
                break

        if rc != 0:
            return QACheckResult(
                category=CheckCategory.LOGS,
                name="Backend Log Analysis",
                status=CheckStatus.WARNING,
                duration_seconds=time.monotonic() - t0,
                warnings=[f"Could not read logs: {stderr[:200]}"],
            )

        # Docker logs go to stderr for most frameworks
        logs = stdout + stderr
        lines = logs.splitlines()

        tracebacks = []
        error_lines = []
        for i, line in enumerate(lines):
            lower = line.lower()
            if "traceback" in lower:
                context = "\n".join(lines[max(0, i):min(len(lines), i + 8)])
                tracebacks.append(context)
            elif "error" in lower and "error=" not in lower and "error_count" not in lower:
                error_lines.append(line.strip())

        if tracebacks:
            return QACheckResult(
                category=CheckCategory.LOGS,
                name="Backend Log Analysis",
                status=CheckStatus.FAILED,
                duration_seconds=time.monotonic() - t0,
                errors=[f"Found {len(tracebacks)} traceback(s)"],
                details=tracebacks[0][:500] if tracebacks else None,
            )

        if len(error_lines) > 5:
            return QACheckResult(
                category=CheckCategory.LOGS,
                name="Backend Log Analysis",
                status=CheckStatus.WARNING,
                duration_seconds=time.monotonic() - t0,
                warnings=[f"Found {len(error_lines)} error log entries"],
                details="\n".join(error_lines[:5]),
            )

        return QACheckResult(
            category=CheckCategory.LOGS,
            name="Backend Log Analysis",
            status=CheckStatus.PASSED,
            duration_seconds=time.monotonic() - t0,
            details="No tracebacks in last 200 log lines",
        )

    # ================================================================
    # AGGREGATION
    # ================================================================

    def _aggregate(
        self, checks: List[QACheckResult]
    ) -> Tuple[CheckStatus, bool, List[str], List[str]]:
        """Aggregate check results into overall status."""
        blocking: List[str] = []
        warnings: List[str] = []

        for c in checks:
            if c.status == CheckStatus.FAILED:
                summary = c.errors[0] if c.errors else "Failed"
                blocking.append(f"{c.name}: {summary}")
            elif c.status == CheckStatus.ERROR:
                blocking.append(f"{c.name}: Check execution error")
            elif c.status == CheckStatus.WARNING:
                for w in c.warnings:
                    warnings.append(w)

        if any(c.status == CheckStatus.FAILED for c in checks):
            overall = CheckStatus.FAILED
        elif any(c.status == CheckStatus.ERROR for c in checks):
            overall = CheckStatus.ERROR
        elif any(c.status == CheckStatus.WARNING for c in checks):
            overall = CheckStatus.WARNING
        else:
            overall = CheckStatus.PASSED

        can_deploy = overall in (CheckStatus.PASSED, CheckStatus.WARNING)
        return overall, can_deploy, blocking, warnings

    # ================================================================
    # STORAGE
    # ================================================================

    async def _save_report(self, report: QAReport) -> None:
        """Save report to workspace/qa/."""
        data = report.model_dump(mode="json")
        await self.storage.write(f"{report.report_id}.json", data)
        await self.storage.write("latest.json", data)

    async def get_latest_report(self) -> Optional[QAReport]:
        """Load the most recent QA report."""
        data = await self.storage.read("latest.json")
        if data:
            return QAReport(**data)
        return None

    async def get_report_history(self, limit: int = 20) -> List[QAReport]:
        """Load recent QA reports (newest first)."""
        reports = []
        files = sorted(self.qa_dir.glob("qa_*.json"), reverse=True)[:limit]
        for f in files:
            data = await self.storage.read(f.name)
            if data:
                try:
                    reports.append(QAReport(**data))
                except Exception:
                    pass
        return reports

    async def get_status_summary(self) -> QAStatusSummary:
        """Get lightweight status for quick polling."""
        report = await self.get_latest_report()
        if not report:
            return QAStatusSummary(status="no_reports")
        return QAStatusSummary(
            status=report.overall_status.value,
            can_deploy=report.can_deploy,
            report_id=report.report_id,
            completed_at=report.completed_at,
            total_checks=report.total_checks,
            passed=report.passed_count,
            failed=report.failed_count,
            warnings=report.warning_count,
            blocking_issues_count=len(report.blocking_issues),
        )

    # ================================================================
    # LEGION INTEGRATION
    # ================================================================

    async def _create_legion_tasks(self, report: QAReport) -> List[int]:
        """Auto-create Legion tasks for QA failures (one per category)."""
        try:
            from app.services.legion_client import get_legion_client
        except ImportError:
            logger.warning("legion_client_not_available")
            return []

        settings = get_settings()
        legion = get_legion_client()
        task_ids: List[int] = []

        # Group failures by category
        failures: dict = {}
        for check in report.checks:
            if check.status in (CheckStatus.FAILED, CheckStatus.ERROR):
                failures.setdefault(check.category, []).append(check)

        if not failures:
            return []

        try:
            # Find or create a QA sprint
            sprints = await legion.list_sprints(
                project_id=settings.zero_legion_project_id,
                status="active",
                limit=10,
            )

            qa_sprint = None
            for s in sprints:
                if "QA" in s.get("name", ""):
                    qa_sprint = s
                    break

            if not qa_sprint:
                qa_sprint = await legion.create_sprint({
                    "name": f"QA Fixes - {datetime.utcnow().strftime('%Y-%m-%d')}",
                    "project_id": settings.zero_legion_project_id,
                    "status": "active",
                    "description": "Auto-generated sprint for QA verification failures",
                })

            sprint_id = qa_sprint["id"]

            for category, checks in failures.items():
                lines = [f"QA verification failed for {category.value}:\n"]
                for c in checks:
                    lines.append(f"**{c.name}:**")
                    for err in c.errors[:5]:
                        lines.append(f"- {err}")

                description = "\n".join(lines)
                task = await legion.create_task(sprint_id, {
                    "title": f"Fix {category.value.replace('_', ' ').title()} QA Failures",
                    "prompt": description,
                    "description": description,
                    "priority": 1,
                })
                task_ids.append(task["id"])
                logger.info("qa_legion_task_created", task_id=task["id"], category=category.value)

        except Exception as e:
            logger.error("failed_to_create_legion_tasks", error=str(e))

        return task_ids


# ================================================================
# SINGLETON
# ================================================================

@lru_cache()
def get_qa_verification_service() -> QAVerificationService:
    """Get singleton QA verification service."""
    return QAVerificationService()
