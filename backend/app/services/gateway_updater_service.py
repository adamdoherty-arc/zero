"""
Gateway Updater Service for Zero.

Checks for new OpenClaw gateway releases via the GitHub API,
fetches changelogs, manages update state, and sends Discord notifications.
Creates Legion tasks to track upgrades through the sprint system.

The actual Docker build/restart is handled by a host-side PowerShell script
(scripts/update-gateway.ps1) since the backend container lacks Docker socket access.

State coordination uses workspace/gateway-update/:
- pending.json: Written here when update available, consumed by PS script
- last-update.json: Written by PS script after upgrade attempt
- history.json: Append-only log of all past updates
"""

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)

GITHUB_API = "https://api.github.com"
REPO_OWNER = "openclaw"
REPO_NAME = "openclaw"


class GatewayUpdaterService:
    """Checks for OpenClaw updates and manages upgrade state."""

    def __init__(self):
        settings = get_settings()
        self._config_path = Path(settings.config_dir) / "zero.json"
        self._update_dir = Path(settings.workspace_dir) / "gateway-update"
        self._update_dir.mkdir(parents=True, exist_ok=True)
        self._gh_token = os.getenv("GH_TOKEN", "")

    def _gh_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Zero-AI-Assistant",
        }
        if self._gh_token:
            headers["Authorization"] = f"Bearer {self._gh_token}"
        return headers

    # ================================================================
    # VERSION QUERIES
    # ================================================================

    def get_current_version(self) -> str:
        """Read current gateway version from config/zero.json."""
        try:
            with open(self._config_path) as f:
                config = json.load(f)
            return (
                config.get("lastTouchedVersion")
                or config.get("meta", {}).get("lastTouchedVersion", "unknown")
            )
        except Exception as e:
            logger.error("read_gateway_version_failed", error=str(e))
            return "unknown"

    async def get_latest_version(self) -> Dict[str, Any]:
        """Query GitHub releases API for the latest stable release.

        Returns dict with keys: version, tag, published_at, changelog, url
        """
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest",
                    headers=self._gh_headers(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    tag = data.get("tag_name", "")
                    # Strip leading 'v' for comparison (v2026.2.19 -> 2026.2.19)
                    version = tag.lstrip("v")
                    return {
                        "version": version,
                        "tag": tag,
                        "published_at": data.get("published_at", ""),
                        "changelog": data.get("body", ""),
                        "url": data.get("html_url", ""),
                        "name": data.get("name", ""),
                    }
                elif resp.status_code == 403:
                    logger.warning("github_rate_limited", remaining=resp.headers.get("X-RateLimit-Remaining"))
                    return {"error": "GitHub API rate limited"}
                else:
                    logger.warning("github_api_error", status=resp.status_code)
                    return {"error": f"GitHub API returned {resp.status_code}"}
        except Exception as e:
            logger.error("github_api_failed", error=str(e))
            return {"error": str(e)}

    async def get_changelog(self, tag: str) -> Optional[str]:
        """Fetch release notes for a specific version tag."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{tag}",
                    headers=self._gh_headers(),
                )
                if resp.status_code == 200:
                    return resp.json().get("body", "")
        except Exception as e:
            logger.error("changelog_fetch_failed", tag=tag, error=str(e))
        return None

    # ================================================================
    # UPDATE STATE
    # ================================================================

    def _read_json(self, filename: str) -> Optional[Dict[str, Any]]:
        path = self._update_dir / filename
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _write_json(self, filename: str, data: Dict[str, Any]):
        path = self._update_dir / filename
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    async def get_update_status(self) -> Dict[str, Any]:
        """Return comprehensive update status for the API."""
        current = self.get_current_version()
        latest_info = await self.get_latest_version()
        pending = self._read_json("pending.json")
        last_update = self._read_json("last-update.json")
        history = self._read_json("history.json") or []

        latest_version = latest_info.get("version", "unknown")
        update_available = (
            latest_version != "unknown"
            and current != "unknown"
            and "error" not in latest_info
            and self._version_newer(latest_version, current)
        )

        return {
            "current_version": current,
            "latest_version": latest_version,
            "latest_tag": latest_info.get("tag", ""),
            "latest_published_at": latest_info.get("published_at", ""),
            "latest_url": latest_info.get("url", ""),
            "update_available": update_available,
            "pending_update": pending,
            "last_update": last_update,
            "update_history_count": len(history),
        }

    # ================================================================
    # VERSION COMPARISON (CalVer: YYYY.M.DD)
    # ================================================================

    @staticmethod
    def _parse_calver(version: str) -> tuple:
        """Parse CalVer string like '2026.2.19' into comparable tuple."""
        try:
            parts = version.split(".")
            return tuple(int(p) for p in parts)
        except (ValueError, AttributeError):
            return (0,)

    def _version_newer(self, candidate: str, current: str) -> bool:
        """Return True if candidate is newer than current."""
        return self._parse_calver(candidate) > self._parse_calver(current)

    # ================================================================
    # LEGION TASK INTEGRATION
    # ================================================================

    async def _create_legion_task(self, current: str, latest: str, changelog_summary: str, url: str) -> Optional[int]:
        """Create a Legion task to track the gateway upgrade."""
        try:
            from app.services.legion_client import get_legion_client
            from app.infrastructure.config import get_settings

            legion = get_legion_client()
            if not await legion.health_check():
                logger.warning("legion_not_reachable_for_gateway_task")
                return None

            settings = get_settings()
            sprint = await legion.get_current_sprint(settings.zero_legion_project_id)
            if not sprint:
                logger.warning("no_active_sprint_for_gateway_task")
                return None

            task_data = {
                "title": f"[Auto-Update] Upgrade OpenClaw gateway v{current} → v{latest}",
                "description": (
                    f"A new OpenClaw gateway release is available.\n\n"
                    f"**Current:** v{current}\n"
                    f"**Available:** v{latest}\n"
                    f"**Release:** {url}\n\n"
                    f"**What's new:**\n{changelog_summary}\n\n"
                    f"Executed by `scripts/update-gateway.ps1` via Windows Task Scheduler."
                ),
                "priority": 2,
                "source": "gateway_updater",
            }
            task = await legion.create_task(sprint["id"], task_data)
            task_id = task.get("id")
            logger.info("legion_gateway_task_created", task_id=task_id, sprint_id=sprint["id"])
            return task_id
        except Exception as e:
            logger.error("legion_gateway_task_creation_failed", error=str(e))
            return None

    async def sync_upgrade_result(self) -> Optional[Dict[str, Any]]:
        """Check if PS script completed an upgrade and update the Legion task.

        Reads last-update.json, finds the legion_task_id, and moves the task
        to completed (on success) or failed (on failure). Clears processed state.
        """
        last_update = self._read_json("last-update.json")
        if not last_update:
            return None

        # Skip if already synced to Legion
        if last_update.get("legion_synced"):
            return None

        task_id = last_update.get("legion_task_id")
        if not task_id:
            return None

        success = last_update.get("success", False)
        from_ver = last_update.get("from_version", "?")
        to_ver = last_update.get("to_version", "?")

        try:
            from app.services.legion_client import get_legion_client
            legion = get_legion_client()

            if not await legion.health_check():
                return None

            if success:
                await legion.move_task(
                    task_id,
                    new_status="completed",
                    reason=f"Gateway upgraded v{from_ver} → v{to_ver} in {last_update.get('duration_seconds', '?')}s",
                )
                logger.info("legion_gateway_task_completed", task_id=task_id)
            else:
                error = last_update.get("error", "Unknown error")
                await legion.move_task(
                    task_id,
                    new_status="failed",
                    reason=f"Gateway upgrade failed: {error}. Rolled back to v{from_ver}.",
                )
                logger.warning("legion_gateway_task_failed", task_id=task_id, error=error)

            # Mark as synced so we don't process again
            last_update["legion_synced"] = True
            self._write_json("last-update.json", last_update)

            return {"task_id": task_id, "success": success}
        except Exception as e:
            logger.error("legion_gateway_task_sync_failed", task_id=task_id, error=str(e))
            return None

    # ================================================================
    # MAIN CHECK LOGIC
    # ================================================================

    async def check_for_updates(self) -> Dict[str, Any]:
        """Check GitHub for updates. Write pending.json and create Legion task if update available.

        Returns dict with: current, latest, update_available, changelog_summary
        """
        # First, sync any completed upgrade results back to Legion
        await self.sync_upgrade_result()

        current = self.get_current_version()
        latest_info = await self.get_latest_version()

        if "error" in latest_info:
            logger.warning("update_check_failed", error=latest_info["error"])
            return {
                "current": current,
                "latest": "unknown",
                "update_available": False,
                "error": latest_info["error"],
            }

        latest_version = latest_info["version"]
        update_available = self._version_newer(latest_version, current)

        result = {
            "current": current,
            "latest": latest_version,
            "update_available": update_available,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        # Don't re-create pending if one already exists for this version
        existing_pending = self._read_json("pending.json")
        if existing_pending and existing_pending.get("version") == latest_version:
            result["changelog_summary"] = existing_pending.get("changelog_summary", "")
            result["changelog_url"] = existing_pending.get("url", "")
            result["already_pending"] = True
            return result

        if update_available:
            changelog = latest_info.get("changelog", "")
            # Truncate changelog for Discord (max ~300 chars for summary)
            changelog_summary = changelog[:300].strip()
            if len(changelog) > 300:
                changelog_summary += "..."

            result["changelog_summary"] = changelog_summary
            result["changelog_url"] = latest_info.get("url", "")

            # Create Legion task to track the upgrade
            legion_task_id = await self._create_legion_task(
                current, latest_version, changelog_summary, latest_info.get("url", "")
            )

            # Write pending update for the host-side PS script
            pending = {
                "version": latest_version,
                "tag": latest_info["tag"],
                "current_version": current,
                "changelog": changelog,
                "changelog_summary": changelog_summary,
                "url": latest_info.get("url", ""),
                "name": latest_info.get("name", ""),
                "published_at": latest_info.get("published_at", ""),
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "legion_task_id": legion_task_id,
            }
            self._write_json("pending.json", pending)

            if legion_task_id:
                result["legion_task_id"] = legion_task_id

            logger.info(
                "gateway_update_available",
                current=current,
                latest=latest_version,
                tag=latest_info["tag"],
                legion_task_id=legion_task_id,
            )

            # Send Discord notification
            await self._notify_update_available(current, latest_version, changelog_summary, latest_info.get("url", ""))
        else:
            logger.info(
                "gateway_up_to_date",
                current=current,
                latest=latest_version,
            )

        return result

    async def _notify_update_available(
        self, current: str, latest: str, changelog: str, url: str
    ):
        """Send Discord embed about available update."""
        try:
            from app.services.discord_notifier import get_discord_notifier

            notifier = get_discord_notifier()
            if not notifier.configured:
                return

            fields = [
                {"name": "Current", "value": f"v{current}", "inline": True},
                {"name": "Available", "value": f"v{latest}", "inline": True},
            ]
            if url:
                fields.append({"name": "Release", "value": url, "inline": False})

            description = f"A new OpenClaw version is available.\n\n"
            if changelog:
                description += f"**What's new:**\n{changelog}"

            await notifier.send_embed(
                title="Gateway Update Available",
                description=description,
                fields=fields,
                color=0x5865F2,  # blurple
            )
        except Exception as e:
            logger.error("discord_update_notify_failed", error=str(e))


@lru_cache()
def get_gateway_updater_service() -> GatewayUpdaterService:
    """Get singleton GatewayUpdaterService instance."""
    return GatewayUpdaterService()
