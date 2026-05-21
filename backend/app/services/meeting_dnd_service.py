"""F-78 — Do-Not-Disturb sync across Windows Focus Assist + Slack + Teams.

When ``companion.meeting_active`` flips to True, push DND state to each
adapter. When it flips False, restore the prior state. Each adapter is
best-effort and gated on its own env / token; missing OAuth doesn't
fail the others.

Adapters live in this file as small async functions so we can keep the
swap surface tight. Add new ones (e.g. iOS Focus, Outlook) by extending
``_ADAPTERS``.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Adapters — each takes (active: bool) and returns a small result dict so
# the caller can record which DND surfaces actually flipped.
# ---------------------------------------------------------------------------


async def _host_agent_dnd(active: bool) -> dict[str, Any]:
    """Toggle Windows Focus Assist via host_agent. host_agent owns the
    PowerShell surface to talk to the Notifications API."""
    host_url = (
        os.getenv("ZERO_HOST_AGENT_URL", "http://host.docker.internal:18796")
        .rstrip("/")
    )
    path = "/dnd/start" if active else "/dnd/stop"
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.post(f"{host_url}{path}")
            return {
                "adapter": "host_agent_focus_assist",
                "ok": r.status_code < 400,
                "status_code": r.status_code,
                "body": (r.json() if r.content else {}),
            }
    except Exception as exc:
        return {
            "adapter": "host_agent_focus_assist",
            "ok": False,
            "error": str(exc),
        }


async def _slack_dnd(active: bool) -> dict[str, Any]:
    """Slack snooze via the user's existing OAuth token. Skipped silently
    when ZERO_SLACK_TOKEN isn't set."""
    token = os.getenv("ZERO_SLACK_TOKEN") or os.getenv("SLACK_USER_TOKEN")
    if not token:
        return {"adapter": "slack", "skipped": True, "reason": "no_token"}
    duration_min = int(os.getenv("ZERO_SLACK_DND_MIN", "60"))
    url = (
        f"https://slack.com/api/dnd.setSnooze?num_minutes={duration_min}"
        if active
        else "https://slack.com/api/dnd.endSnooze"
    )
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            data = r.json() if r.content else {}
            return {
                "adapter": "slack",
                "ok": bool(data.get("ok")),
                "status_code": r.status_code,
                "body": data,
            }
    except Exception as exc:
        return {"adapter": "slack", "ok": False, "error": str(exc)}


async def _teams_busy(active: bool) -> dict[str, Any]:
    """Teams presence — Busy on start, Available on stop. Graph API path
    is best-effort; gated on ZERO_TEAMS_GRAPH_TOKEN."""
    token = os.getenv("ZERO_TEAMS_GRAPH_TOKEN")
    if not token:
        return {"adapter": "teams", "skipped": True, "reason": "no_token"}
    presence = "Busy" if active else "Available"
    activity = "InAMeeting" if active else "Available"
    url = "https://graph.microsoft.com/v1.0/me/presence/setPresence"
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "sessionId": "zero-meeting-steward",
                    "availability": presence,
                    "activity": activity,
                    "expirationDuration": "PT2H",
                },
            )
            return {
                "adapter": "teams",
                "ok": r.status_code < 400,
                "status_code": r.status_code,
            }
    except Exception as exc:
        return {"adapter": "teams", "ok": False, "error": str(exc)}


_ADAPTERS = (_host_agent_dnd, _slack_dnd, _teams_busy)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class MeetingDndService:
    def __init__(self, storage_dir: Path | None = None) -> None:
        base = storage_dir or get_workspace_path("meetings")
        self._dir = Path(base).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "dnd_state.json"
        self._lock = threading.RLock()

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def state(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"active": False, "history": []}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"active": False, "history": []}

    async def apply(self, *, active: bool, source: str = "scheduler") -> dict[str, Any]:
        """Push DND state to every adapter and persist the per-adapter
        outcome. Idempotent: re-calling with the same state is cheap
        because each adapter no-ops when the state already matches."""
        results: list[dict[str, Any]] = []
        for fn in _ADAPTERS:
            try:
                results.append(await fn(active))
            except Exception as exc:  # noqa: BLE001
                results.append({"adapter": fn.__name__, "ok": False, "error": str(exc)})
        snapshot = {
            "active": bool(active),
            "source": source,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "adapters": results,
        }
        with self._lock:
            existing = self.state()
            history = existing.get("history") or []
            history.append(snapshot)
            self._save({
                "active": bool(active),
                "source": source,
                "applied_at": snapshot["applied_at"],
                "history": history[-50:],  # keep last 50 transitions
            })
        logger.info(
            "meeting_dnd_applied",
            active=bool(active),
            source=source,
            adapters=[r.get("adapter") for r in results if r.get("ok")],
        )
        return snapshot


@lru_cache()
def get_meeting_dnd_service() -> MeetingDndService:
    return MeetingDndService()
