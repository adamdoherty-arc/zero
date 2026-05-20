"""Subscribe to /api/notifications/ws and fire Windows toasts via BurntToast.

Runs as a background task inside host_agent's uvicorn event loop. When
notification_bus emits ``meeting.starting`` / ``meeting.nudge`` /
``meeting.stopped``, this subscriber relays it to the user's Windows
notification tray via the BurntToast PowerShell module. Click-through
on the toast opens http://localhost:5173 so the user lands on the
dashboard with the meeting context.

Why: the browser toast covers the dashboard-open case; the BurntToast
toast covers "user is heads-down in another app and didn't see Zero
notify them". Same backend event, two surfaces.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from typing import Any

import structlog

try:
    import httpx  # noqa: F401 — gated import; host_agent already depends on httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]

logger = structlog.get_logger()

DEFAULT_RELAY_URL = "ws://localhost:18792/api/notifications/ws"
DASHBOARD_URL = "http://localhost:5173/"
BACKOFF_MIN = 0.5
BACKOFF_MAX = 15.0


def _powershell_available() -> bool:
    return bool(shutil.which("powershell.exe") or shutil.which("pwsh.exe"))


def _burnt_toast_available() -> bool:
    if not _powershell_available():
        return False
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "if (Get-Module -ListAvailable -Name BurntToast) { 'yes' } else { 'no' }",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=8)
        return result.stdout.strip().endswith(b"yes")
    except Exception:
        return False


def _fire_toast(title: str, body: str) -> None:
    """Best-effort Windows toast via BurntToast. Silent on failure."""
    if not _burnt_toast_available():
        return
    title_safe = title.replace("'", "''")
    body_safe = body.replace("'", "''")
    ps = (
        "Import-Module BurntToast -ErrorAction SilentlyContinue; "
        f"New-BurntToastNotification -Text '{title_safe}', '{body_safe}' "
        f"-AppLogo $null -SilentNotification:$false -ErrorAction SilentlyContinue"
    )
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        logger.debug("burnt_toast_spawn_failed", error=str(exc))


def _format(event: dict[str, Any]) -> tuple[str, str] | None:
    et = str(event.get("type") or "")
    if et == "meeting.starting":
        return (
            "Recording meeting",
            f"Capturing {event.get('title') or 'this meeting'}. Reachy is silent — say 'Hey Zero' to ask a question.",
        )
    if et == "meeting.nudge":
        return (
            f"Meeting in {event.get('bucket_min') or '?'} min",
            str(event.get("title") or "an event"),
        )
    if et == "meeting.stopped":
        return (
            "Meeting captured",
            f"Transcript + summary saved for {event.get('title') or 'meeting'}.",
        )
    return None


async def _consume(url: str) -> None:
    if websockets is None:
        logger.warning("notifications_subscriber_websockets_missing")
        return
    backoff = BACKOFF_MIN
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                backoff = BACKOFF_MIN
                logger.info("notifications_subscriber_connected", url=url)
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except Exception:
                        continue
                    if event.get("type") == "ping":
                        continue
                    fmt = _format(event)
                    if not fmt:
                        continue
                    title, body = fmt
                    _fire_toast(title, body)
        except Exception as exc:
            logger.info(
                "notifications_subscriber_disconnected",
                error=str(exc),
                backoff=backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)


def start_subscriber(loop: asyncio.AbstractEventLoop) -> asyncio.Task | None:
    """Hand off to background task. Returns the Task or None if disabled.

    Disable with ``ZERO_NOTIFICATIONS_SUBSCRIBER=off``. Default URL points
    at the local zero-api; override with ``ZERO_NOTIFICATIONS_WS_URL``.
    """
    if os.getenv("ZERO_NOTIFICATIONS_SUBSCRIBER", "auto").lower() in {"off", "false", "0"}:
        return None
    if not _burnt_toast_available():
        logger.info(
            "notifications_subscriber_skipped",
            reason="BurntToast PowerShell module not installed",
        )
        return None
    url = os.getenv("ZERO_NOTIFICATIONS_WS_URL", DEFAULT_RELAY_URL)
    task = loop.create_task(_consume(url), name="notifications-subscriber")
    logger.info("notifications_subscriber_started", url=url)
    return task
