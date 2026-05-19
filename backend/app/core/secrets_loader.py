"""Sprint S6 (2026-05-18) — boot-time secrets loader for Zero.

Decrypts ``Zero/.env.enc`` with sops at process start (if present) and
populates ``os.environ`` before any settings reads. Falls back to plain
``Zero/.env`` when only the unencrypted file exists (dev mode).

See ``C:\\code\\SECRETS_VAULT.md`` for setup + rotation procedure.

Wire from Zero's startup BEFORE any settings imports:

    from app.core.secrets_loader import load_env_from_sops
    load_env_from_sops()
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def _project_env_paths() -> Iterable[Path]:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        yield parent / ".env.enc"
        yield parent / ".env"


def _decrypt_sops(path: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["sops", "-d", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("secrets_loader.sops_not_installed", extra={"path": str(path)})
        return None
    except Exception:
        logger.exception("secrets_loader.sops_invoke_failed")
        return None
    if result.returncode != 0:
        logger.warning(
            "secrets_loader.sops_failed",
            extra={"path": str(path), "stderr": result.stderr[:500]},
        )
        return None
    return result.stdout


def _parse_env_body(body: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def load_env_from_sops() -> int:
    for path in _project_env_paths():
        if not path.exists():
            continue
        body = _decrypt_sops(path) if path.name == ".env.enc" else path.read_text(encoding="utf-8")
        if not body:
            continue
        env = _parse_env_body(body)
        applied = 0
        for k, v in env.items():
            if k not in os.environ:
                os.environ[k] = v
                applied += 1
        logger.info("secrets_loader.loaded", extra={"path": str(path), "applied": applied})
        return applied
    return 0
