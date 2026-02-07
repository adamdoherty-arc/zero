"""
Automated backup service for ZERO workspace data.

Backs up all JSON files in workspace/ with three rotation tiers:
  - Hourly: every hour, keep 24
  - Daily:  2 AM, keep 7
  - Weekly: Sunday 3 AM, keep 4

Each backup is gzip-compressed with SHA256 checksum.
"""

import asyncio
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog

logger = structlog.get_logger(__name__)

RETENTION = {
    "hourly": 24,
    "daily": 7,
    "weekly": 4,
}


class BackupService:
    """Manages compressed workspace backups with rotation."""

    def __init__(self, workspace_dir: str = "workspace", backup_dir: str = "backups"):
        self.workspace_path = Path(workspace_dir).resolve()
        self.backup_path = Path(backup_dir).resolve()

        # Create tier directories
        for tier in RETENTION:
            (self.backup_path / tier).mkdir(parents=True, exist_ok=True)

    async def create_backup(self, tier: str = "hourly") -> Dict[str, Any]:
        """Create a compressed backup of the workspace."""
        if tier not in RETENTION:
            return {"error": f"Invalid tier: {tier}"}

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        archive_base = self.backup_path / tier / f"zero_{tier}_{timestamp}"

        logger.info("backup_starting", tier=tier)

        try:
            # shutil.make_archive is blocking — run in thread pool
            archive_path = await asyncio.to_thread(
                shutil.make_archive,
                str(archive_base),
                "gztar",
                root_dir=str(self.workspace_path.parent),
                base_dir=self.workspace_path.name,
            )
            archive_path = Path(archive_path)

            # Calculate checksum
            checksum = await self._sha256(archive_path)
            checksum_file = archive_path.with_suffix(archive_path.suffix + ".sha256")
            await asyncio.to_thread(
                checksum_file.write_text,
                f"{checksum}  {archive_path.name}\n",
            )

            size_mb = archive_path.stat().st_size / (1024 * 1024)
            logger.info(
                "backup_completed",
                tier=tier,
                file=archive_path.name,
                size_mb=f"{size_mb:.2f}",
            )

            # Rotate old backups
            await self._rotate(tier)

            return {
                "tier": tier,
                "file": archive_path.name,
                "size_bytes": archive_path.stat().st_size,
                "checksum": checksum,
                "timestamp": timestamp,
            }

        except Exception as e:
            logger.error("backup_failed", tier=tier, error=str(e))
            return {"error": str(e)}

    async def list_backups(self) -> Dict[str, List[Dict[str, Any]]]:
        """List all backups grouped by tier."""
        result = {}
        for tier in RETENTION:
            tier_path = self.backup_path / tier
            backups = []
            for f in sorted(tier_path.glob("zero_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
                backups.append({
                    "file": f.name,
                    "size_bytes": f.stat().st_size,
                    "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
            result[tier] = backups
        return result

    async def verify_backup(self, tier: str, filename: str) -> Dict[str, Any]:
        """Verify a backup's SHA256 checksum."""
        archive = self.backup_path / tier / filename
        if not archive.exists():
            return {"valid": False, "error": "File not found"}

        checksum_file = archive.with_suffix(archive.suffix + ".sha256")
        if not checksum_file.exists():
            return {"valid": False, "error": "No checksum file"}

        stored = (await asyncio.to_thread(checksum_file.read_text)).split()[0]
        actual = await self._sha256(archive)
        return {"valid": stored == actual, "stored": stored, "actual": actual}

    async def _sha256(self, path: Path) -> str:
        def _hash():
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        return await asyncio.to_thread(_hash)

    async def _rotate(self, tier: str):
        """Delete old backups beyond the retention limit."""
        tier_path = self.backup_path / tier
        keep = RETENTION[tier]
        archives = sorted(tier_path.glob("zero_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)

        for old in archives[keep:]:
            logger.info("backup_rotated", file=old.name)
            await asyncio.to_thread(old.unlink)
            sha_file = old.with_suffix(old.suffix + ".sha256")
            if sha_file.exists():
                await asyncio.to_thread(sha_file.unlink)


@lru_cache()
def get_backup_service() -> BackupService:
    """Get singleton BackupService."""
    return BackupService()
