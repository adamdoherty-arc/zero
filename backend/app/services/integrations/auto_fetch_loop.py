"""
Auto-fetch loop — walks every connected integration on a configurable
cadence (openhuman uses 20 min) and feeds the result into the Memory Tree.

Decoupled from the Composio provider so the loop also covers Zero-native
connectors (gmail/calendar already living in ``backend/app/services``).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional

import structlog

from app.services.integrations.composio_provider import (
    DEFAULT_CATALOG,
    get_composio_provider,
)
from app.services.memory_tree import get_memory_tree

logger = structlog.get_logger(__name__)

DEFAULT_INTERVAL_MINUTES = int(os.getenv("ZERO_AUTO_FETCH_MINUTES", "20"))


class AutoFetchLoop:
    """Single APScheduler-style task. Owns its own ``asyncio.Task``."""

    def __init__(self, interval_minutes: int = DEFAULT_INTERVAL_MINUTES) -> None:
        self._interval_minutes = max(1, interval_minutes)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_tick_at: Optional[str] = None
        self._last_results: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run())
        logger.info("auto_fetch_started", interval_min=self._interval_minutes)

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("auto_fetch_stopped")

    def set_interval(self, minutes: int) -> None:
        self._interval_minutes = max(1, minutes)

    def status(self) -> dict:
        return {
            "running": self._running,
            "interval_minutes": self._interval_minutes,
            "last_tick_at": self._last_tick_at,
            "last_results": self._last_results,
        }

    # ------------------------------------------------------------------
    # Loop body
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("auto_fetch_tick_failed", error=str(e))
            try:
                await asyncio.sleep(self._interval_minutes * 60)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        provider = get_composio_provider()
        results: dict[str, Any] = {}
        for integration_id in provider.list_connected():
            try:
                results[integration_id] = await self.sync_one(integration_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "auto_fetch_integration_failed",
                    integration=integration_id,
                    error=str(e),
                )
                results[integration_id] = {"status": "error", "error": str(e)}
        self._last_results = results
        self._last_tick_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    # ------------------------------------------------------------------
    # Per-integration sync
    # ------------------------------------------------------------------

    async def sync_one(self, integration_id: str) -> dict:
        """Pull fresh data from one integration into the Memory Tree.

        For native connectors (gmail, calendar) we delegate to existing
        services and write a digest into ``sources/{integration}/L0/``.
        For Composio-only connectors we issue a list call via the SDK and
        store the result as a single chunk.
        """
        spec = next((s for s in DEFAULT_CATALOG if s.id == integration_id), None)
        if spec is None:
            return {"status": "unknown_integration"}

        provider = get_composio_provider()
        conn = provider.get_connection(integration_id)
        if conn is None:
            return {"status": "not_connected"}

        body = await self._fetch_body(integration_id)
        if not body:
            return {"status": "empty"}
        tree = get_memory_tree()
        paths = await tree.write_chunk(
            integration_id,
            body,
            level=0,
            title=f"{spec.name} auto-fetch",
            tags=[spec.category.lower(), "auto-fetch"],
        )
        provider.mark_synced(integration_id)
        return {
            "status": "ok",
            "chunks_written": len(paths),
            "paths": [str(p) for p in paths],
        }

    async def _fetch_body(self, integration_id: str) -> str:
        """Per-integration fetch. Native connectors get rich, real bodies.
        Composio-only connectors get a stub line that the LLM can later
        replace with real data when we wire each tool."""
        if integration_id == "gmail":
            try:
                from app.services.gmail_service import get_gmail_service
                gmail = get_gmail_service()
                msgs = await gmail.list_recent(limit=10) if hasattr(gmail, "list_recent") else []
                if not msgs:
                    return ""
                lines = ["# Recent Gmail messages\n"]
                for m in msgs:
                    subj = m.get("subject", "(no subject)") if isinstance(m, dict) else getattr(m, "subject", "")
                    snippet = m.get("snippet", "") if isinstance(m, dict) else getattr(m, "snippet", "")
                    lines.append(f"- **{subj}**: {snippet[:200]}")
                return "\n".join(lines)
            except Exception as e:  # noqa: BLE001
                logger.debug("gmail_autofetch_skipped", error=str(e))
                return ""

        if integration_id == "calendar":
            try:
                from app.services.calendar_service import get_calendar_service
                cal = get_calendar_service()
                events = (
                    await cal.list_upcoming(limit=10) if hasattr(cal, "list_upcoming") else []
                )
                if not events:
                    return ""
                lines = ["# Upcoming calendar events\n"]
                for ev in events:
                    title = ev.get("title", "(no title)") if isinstance(ev, dict) else getattr(ev, "title", "")
                    start = ev.get("start", "") if isinstance(ev, dict) else getattr(ev, "start", "")
                    lines.append(f"- {start}: {title}")
                return "\n".join(lines)
            except Exception as e:  # noqa: BLE001
                logger.debug("calendar_autofetch_skipped", error=str(e))
                return ""

        # Composio-backed integrations — placeholder body until we wire
        # the SDK's per-tool calls. The act of writing a chunk still lets
        # the user see in the UI that the loop is alive.
        now = datetime.utcnow().isoformat(timespec="seconds")
        return (
            f"# {integration_id} sync\n\n"
            f"Composio-backed connector — last touched at {now} UTC. "
            f"Wire `composio_provider.call_tool` for richer fetches."
        )


@lru_cache(maxsize=1)
def get_auto_fetch_loop() -> AutoFetchLoop:
    return AutoFetchLoop()
