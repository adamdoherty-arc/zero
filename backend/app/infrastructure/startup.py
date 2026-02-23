"""
Startup validation checks for ZERO API.

Runs before the scheduler starts to catch configuration problems early.
Non-critical checks log warnings; critical failures prevent scheduler startup.
"""

import os
from pathlib import Path
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger(__name__)


class StartupChecker:
    """Validates environment and dependencies on API startup."""

    def __init__(self):
        self.results: List[Dict[str, Any]] = []

    async def run_all(self) -> bool:
        """
        Run all startup checks.

        Returns True if all critical checks pass.
        """
        logger.info("startup_checks_begin")

        checks = [
            ("workspace_directory", self._check_workspace, True),
            ("storage_writable", self._check_storage_writable, True),
            ("config_directory", self._check_config, True),
            ("environment_variables", self._check_env_vars, True),
            ("ollama_reachable", self._check_ollama, False),  # non-critical
            ("legion_reachable", self._check_legion, False),  # non-critical
            ("gpu_manager", self._check_gpu_manager, False),  # non-critical
        ]

        all_critical_passed = True

        for name, check_fn, is_critical in checks:
            try:
                passed = await check_fn()
                self.results.append({
                    "name": name,
                    "status": "pass" if passed else ("fail" if is_critical else "warn"),
                    "critical": is_critical,
                })
                if not passed and is_critical:
                    all_critical_passed = False
                    logger.error("startup_check_failed", check=name, critical=True)
                elif not passed:
                    logger.warning("startup_check_warn", check=name)
            except Exception as e:
                self.results.append({
                    "name": name,
                    "status": "error",
                    "error": str(e),
                    "critical": is_critical,
                })
                if is_critical:
                    all_critical_passed = False
                    logger.error("startup_check_error", check=name, error=str(e))

        passed_count = sum(1 for r in self.results if r["status"] == "pass")
        total = len(self.results)

        if all_critical_passed:
            logger.info("startup_checks_passed", passed=passed_count, total=total)
        else:
            failed = [r["name"] for r in self.results if r["status"] in ("fail", "error") and r["critical"]]
            logger.error("startup_checks_critical_failure", failed=failed)

        return all_critical_passed

    async def _check_workspace(self) -> bool:
        """Verify workspace directory exists (create if needed)."""
        from app.infrastructure.config import get_workspace_path
        workspace = get_workspace_path()

        try:
            if not workspace.exists():
                workspace.mkdir(parents=True, exist_ok=True)
                logger.info("workspace_created", path=str(workspace))
        except OSError:
            pass  # Mount point may already exist

        return workspace.is_dir()

    async def _check_storage_writable(self) -> bool:
        """Verify we can write to workspace."""
        from app.infrastructure.config import get_workspace_path
        workspace = get_workspace_path()
        test_file = workspace / ".startup_write_test"

        try:
            test_file.write_text("ok")
            test_file.unlink()
            return True
        except Exception as e:
            logger.error("storage_not_writable", path=str(workspace), error=str(e))
            return False

    async def _check_config(self) -> bool:
        """Verify config directory exists."""
        from app.infrastructure.config import get_settings
        settings = get_settings()
        config_dir = Path(settings.config_dir).resolve()

        if not config_dir.exists():
            logger.warning("config_dir_missing", path=str(config_dir))
            return False

        return True

    async def _check_env_vars(self) -> bool:
        """Check that recommended environment variables are set."""
        recommended = [
            "DISCORD_BOT_TOKEN",
            "SLACK_APP_TOKEN",
            "GH_TOKEN",
        ]

        missing_recommended = [v for v in recommended if not os.getenv(v)]

        if missing_recommended:
            logger.info("optional_env_vars_missing", missing=missing_recommended)

        return True

    async def _check_ollama(self) -> bool:
        """Check if Ollama is reachable and warm up default model."""
        import asyncio
        from app.infrastructure.ollama_client import get_ollama_client

        client = get_ollama_client()
        healthy = await client.is_healthy()

        if healthy:
            # Warm up the default model in background (don't block startup)
            asyncio.create_task(client.warmup())

        return healthy

    async def _check_gpu_manager(self) -> bool:
        """Initialize the GPU manager service."""
        try:
            from app.services.gpu_manager_service import get_gpu_manager_service
            svc = get_gpu_manager_service()
            await svc.initialize()
            return True
        except Exception as e:
            logger.warning("gpu_manager_init_failed", error=str(e))
            return False

    async def _check_legion(self) -> bool:
        """Check if Legion is reachable (non-critical)."""
        from app.infrastructure.config import get_settings
        settings = get_settings()

        try:
            import httpx
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{settings.legion_api_url}/health")
                return resp.status_code == 200
        except Exception:
            return False


async def run_startup_checks() -> bool:
    """Run all startup checks. Returns True if critical checks pass."""
    checker = StartupChecker()
    return await checker.run_all()
