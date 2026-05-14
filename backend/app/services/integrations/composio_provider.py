"""
Composio-backed integrations provider.

[Composio](https://composio.dev/) is the connector layer openhuman uses to
ship 118+ third-party integrations with one-click OAuth (Apache 2.0 SDK).
This file wraps the SDK and degrades gracefully when it's not installed.

Two states the rest of Zero needs to handle:

  1. **Composio installed + COMPOSIO_API_KEY set** — full provider, all
     supported integrations available.
  2. **Composio not installed or no API key** — provider reports
     ``available=False`` and falls back to Zero's native gmail / calendar
     code paths.

Tokens never live on the client — Composio holds them server-side and we
hold only a connection ID per integration. Each integration is a typed
agent tool: ``provider.call_tool("gmail.list_messages", {"count": 10})``.

Catalog seeds — the most commonly-used integrations from openhuman's
list of 118+. Add more by appending to ``DEFAULT_CATALOG``.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "integrations"
_CONNECTIONS_FILE = "connections.json"


@dataclass
class IntegrationSpec:
    """Static catalog entry — purely descriptive."""

    id: str
    name: str
    category: str
    description: str
    icon: str = "🔌"
    composio_app_name: str = ""  # the Composio SDK app slug; empty = native-only
    enabled_by_default: bool = False
    triggers: tuple[str, ...] = field(default_factory=tuple)


# Subset of openhuman's 118+ — picked for utility. The rest can be added
# without code changes; the Composio SDK handles the connection generically.
DEFAULT_CATALOG: tuple[IntegrationSpec, ...] = (
    IntegrationSpec(
        id="gmail",
        name="Gmail",
        category="Email",
        description="Read, label, draft, and send Gmail messages.",
        icon="📧",
        composio_app_name="gmail",
        triggers=("gmail.new_message", "gmail.starred"),
    ),
    IntegrationSpec(
        id="calendar",
        name="Google Calendar",
        category="Calendar",
        description="List, create, and update calendar events.",
        icon="📅",
        composio_app_name="googlecalendar",
        triggers=("calendar.event_created", "calendar.event_starts_soon"),
    ),
    IntegrationSpec(
        id="drive",
        name="Google Drive",
        category="Storage",
        description="Browse and read Drive documents.",
        icon="📂",
        composio_app_name="googledrive",
    ),
    IntegrationSpec(
        id="github",
        name="GitHub",
        category="Code",
        description="PRs, issues, releases. Per-repo scoped.",
        icon="🐙",
        composio_app_name="github",
        triggers=("github.pr_assigned", "github.issue_assigned", "github.release_published"),
    ),
    IntegrationSpec(
        id="linear",
        name="Linear",
        category="Project mgmt",
        description="Issues, projects, cycles.",
        icon="📐",
        composio_app_name="linear",
        triggers=("linear.issue_assigned", "linear.issue_status_changed"),
    ),
    IntegrationSpec(
        id="slack",
        name="Slack",
        category="Chat",
        description="Read channels, send DMs, react to threads.",
        icon="💬",
        composio_app_name="slack",
        triggers=("slack.mention", "slack.dm"),
    ),
    IntegrationSpec(
        id="notion",
        name="Notion",
        category="Docs",
        description="Browse, search, and edit Notion pages.",
        icon="📝",
        composio_app_name="notion",
    ),
    IntegrationSpec(
        id="stripe",
        name="Stripe",
        category="Finance",
        description="Customers, charges, balances (read-only by default).",
        icon="💳",
        composio_app_name="stripe",
        triggers=("stripe.payment_succeeded", "stripe.payment_failed"),
    ),
    IntegrationSpec(
        id="jira",
        name="Jira",
        category="Project mgmt",
        description="Tickets, sprints, boards.",
        icon="🎫",
        composio_app_name="jira",
        triggers=("jira.issue_assigned",),
    ),
    IntegrationSpec(
        id="hubspot",
        name="HubSpot",
        category="CRM",
        description="Contacts, deals, tickets.",
        icon="🟧",
        composio_app_name="hubspot",
    ),
    IntegrationSpec(
        id="discord",
        name="Discord",
        category="Chat",
        description="Read channels, send messages, manage bots.",
        icon="🎮",
        composio_app_name="discord",
        triggers=("discord.mention",),
    ),
    IntegrationSpec(
        id="zoom",
        name="Zoom",
        category="Meetings",
        description="List, schedule, and join Zoom meetings.",
        icon="🎥",
        composio_app_name="zoom",
        triggers=("zoom.meeting_started",),
    ),
)


@dataclass
class Connection:
    """A live, OAuth'd link to a third-party app."""

    integration_id: str
    connection_id: str  # Composio's connection identifier (or "native" if local)
    connected_at: str
    last_synced_at: Optional[str] = None
    sync_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class ComposioProvider:
    """Wraps the Composio SDK with graceful degradation."""

    def __init__(self) -> None:
        # Read _DATA_DIR at call time so tests that monkeypatch the module
        # attribute take effect for fresh instances.
        import app.services.integrations.composio_provider as _self_mod
        self._data_dir = _self_mod._DATA_DIR
        self._connections_path = self._data_dir / _CONNECTIONS_FILE
        self._connections: dict[str, Connection] = self._load_connections()
        self._composio_client = self._init_client()

    def _init_client(self):
        """Try to import the Composio SDK. Returns None on any failure
        (missing dep, missing key, bad creds)."""
        api_key = os.getenv("COMPOSIO_API_KEY") or os.getenv("COMPOSIO_KEY")
        if not api_key:
            logger.debug("composio_no_api_key")
            return None
        try:
            import composio  # type: ignore[import-not-found]
        except ImportError:
            logger.debug("composio_sdk_not_installed")
            return None
        try:
            # The Composio Python SDK exposes a Composio() client; the exact
            # constructor surface has changed across versions, so we try the
            # most common shapes and fall back to None if none work.
            client = None
            if hasattr(composio, "Composio"):
                client = composio.Composio(api_key=api_key)  # type: ignore[call-arg]
            elif hasattr(composio, "Client"):
                client = composio.Client(api_key=api_key)  # type: ignore[attr-defined]
            else:
                logger.warning("composio_unknown_sdk_shape")
                return None
            return client
        except Exception as e:
            logger.warning("composio_init_failed", error=str(e))
            return None

    def is_available(self) -> bool:
        return self._composio_client is not None

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def list_integrations(self) -> list[dict]:
        out: list[dict] = []
        for spec in DEFAULT_CATALOG:
            conn = self._connections.get(spec.id)
            is_connected = conn is not None
            if spec.id in {"gmail", "calendar"} and conn:
                is_connected = self._trusted_native_connection(conn)
            is_available = self.is_available()
            if spec.id in {"gmail", "calendar"}:
                is_available = is_connected
            out.append(
                {
                    "id": spec.id,
                    "name": spec.name,
                    "category": spec.category,
                    "description": spec.description,
                    "icon": spec.icon,
                    "composio_app_name": spec.composio_app_name,
                    "triggers": list(spec.triggers),
                    "available": is_available,
                    "connected": is_connected,
                    "connection": {
                        "id": conn.connection_id,
                        "connected_at": conn.connected_at,
                        "last_synced_at": conn.last_synced_at,
                        "sync_count": conn.sync_count,
                    }
                    if conn and is_connected
                    else None,
                }
            )
        return out

    def list_connected(self) -> list[str]:
        out: list[str] = []
        for integration_id, conn in self._connections.items():
            if integration_id in {"gmail", "calendar"} and not self._trusted_native_connection(conn):
                continue
            out.append(integration_id)
        return sorted(out)

    def _trusted_native_connection(self, conn: Connection) -> bool:
        """Only trust native Google connections created after OAuth recheck.

        Older integration rows could mark gmail/calendar connected by copying
        a legacy sync flag. Those rows must not make the catalog or auto-fetch
        believe OAuth is live.
        """
        return (
            bool(conn.extra.get("verified_oauth"))
            and conn.extra.get("verified_oauth_source") == "google_oauth_service"
        )

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    async def connect(
        self,
        integration_id: str,
        *,
        auth_token: Optional[str] = None,
    ) -> dict:
        spec = self._spec_for(integration_id)
        if spec is None:
            return {"status": "error", "message": f"unknown integration: {integration_id}"}

        if integration_id == "gmail":
            try:
                from app.services.gmail_oauth_service import get_gmail_oauth_service

                if not await get_gmail_oauth_service().has_valid_tokens():
                    return {
                        "status": "unavailable",
                        "message": "Gmail OAuth is not connected.",
                    }
            except Exception as e:  # noqa: BLE001
                return {"status": "unavailable", "message": str(e)}

        if integration_id == "calendar":
            try:
                from app.services.calendar_service import get_calendar_service

                if not await get_calendar_service().has_valid_tokens():
                    return {
                        "status": "unavailable",
                        "message": "Google Calendar OAuth is not connected.",
                    }
            except Exception as e:  # noqa: BLE001
                return {"status": "unavailable", "message": str(e)}

        if not self.is_available() and integration_id not in {"gmail", "calendar"}:
            return {
                "status": "unavailable",
                "message": (
                    "Composio SDK not installed or COMPOSIO_API_KEY not set. "
                    "Install composio-core and set COMPOSIO_API_KEY."
                ),
            }

        if integration_id not in {"gmail", "calendar"} and not auth_token:
            return {
                "status": "auth_required",
                "message": "A real Composio OAuth connection ID is required.",
            }

        from datetime import datetime
        connection_id = auth_token or f"native:{integration_id}"
        conn = Connection(
            integration_id=integration_id,
            connection_id=connection_id,
            connected_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            extra={
                "provider": "native" if integration_id in {"gmail", "calendar"} else "composio",
                "verified_oauth": integration_id in {"gmail", "calendar"},
                "verified_oauth_source": (
                    "google_oauth_service" if integration_id in {"gmail", "calendar"} else None
                ),
            },
        )
        self._connections[integration_id] = conn
        await asyncio.get_event_loop().run_in_executor(None, self._save_connections)
        logger.info("integration_connected", integration=integration_id)
        return {
            "status": "connected",
            "integration": integration_id,
            "connection_id": conn.connection_id,
        }

    async def disconnect(self, integration_id: str) -> dict:
        if integration_id not in self._connections:
            return {"status": "not_connected"}
        self._connections.pop(integration_id, None)
        await asyncio.get_event_loop().run_in_executor(None, self._save_connections)
        logger.info("integration_disconnected", integration=integration_id)
        return {"status": "disconnected", "integration": integration_id}

    def get_connection(self, integration_id: str) -> Optional[Connection]:
        return self._connections.get(integration_id)

    def mark_synced(self, integration_id: str) -> None:
        conn = self._connections.get(integration_id)
        if not conn:
            return
        from datetime import datetime
        conn.last_synced_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.sync_count += 1
        self._save_connections()

    # ------------------------------------------------------------------
    # Tool dispatch (Composio calls)
    # ------------------------------------------------------------------

    async def call_tool(self, tool_name: str, params: dict) -> dict:
        """Generic tool call. Currently a placeholder that logs and returns
        a stub — the Composio SDK's call shape varies enough by version that
        we wire this on a per-tool basis as we use each integration."""
        if not self.is_available():
            return {"status": "unavailable", "tool": tool_name}
        logger.info("composio_tool_call", tool=tool_name, param_keys=list(params.keys()))
        return {"status": "stub", "tool": tool_name, "params": params}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _spec_for(self, integration_id: str) -> Optional[IntegrationSpec]:
        for spec in DEFAULT_CATALOG:
            if spec.id == integration_id:
                return spec
        return None

    def _load_connections(self) -> dict[str, Connection]:
        if not self._connections_path.exists():
            return {}
        try:
            raw = json.loads(self._connections_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("integration_connections_read_failed", error=str(e))
            return {}
        out: dict[str, Connection] = {}
        for k, v in raw.items():
            try:
                out[k] = Connection(**v)
            except Exception:
                continue
        return out

    def _save_connections(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        data = {
            k: {
                "integration_id": c.integration_id,
                "connection_id": c.connection_id,
                "connected_at": c.connected_at,
                "last_synced_at": c.last_synced_at,
                "sync_count": c.sync_count,
                "extra": c.extra,
            }
            for k, c in self._connections.items()
        }
        self._connections_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@lru_cache(maxsize=1)
def get_composio_provider() -> ComposioProvider:
    return ComposioProvider()
