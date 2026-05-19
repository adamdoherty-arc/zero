"""
Runtime provider selector for Reachy's voice-chat fallback intent.

Reachy classic chat routes through the shared Bifrost gateway. Selection is
persisted to workspace/settings/reachy_chat.json so it survives container
rebuilds and restarts.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class ChatProvider:
    id: str
    label: str
    provider: str
    model: str
    description: str


# Active Bifrost routes. OpenRouter/MiniMax/Gemini are intentionally disabled
# in shared-infra/bifrost/disabled-providers.json, so keep the voice selector
# aligned to the gateway's live provider set. Model ids resolve through the
# central registry so future renames touch one file.
from app.constants.models import KIMI_K2, LOCAL_CHAT  # noqa: E402

AVAILABLE_PROVIDERS: list[ChatProvider] = [
    ChatProvider(
        id="bifrost-kimi",
        label="Bifrost Kimi K2.6",
        provider="bifrost",
        model=KIMI_K2,
        description="Moonshot Kimi route through Bifrost for reliable spoken replies.",
    ),
    ChatProvider(
        id="bifrost-local-qwen",
        label="Bifrost Local Qwen",
        provider="bifrost",
        model=LOCAL_CHAT,
        description="Local Qwen route through Bifrost; private, but slower on hidden-reasoning turns.",
    ),
]

DEFAULT_PROVIDER_ID = "bifrost-kimi"


def _state_path() -> Path:
    root = Path(os.getenv("ZERO_WORKSPACE_DIR", "/app/workspace"))
    p = root / "settings" / "reachy_chat.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def list_providers() -> list[ChatProvider]:
    return list(AVAILABLE_PROVIDERS)


def get_provider_by_id(provider_id: str) -> Optional[ChatProvider]:
    for p in AVAILABLE_PROVIDERS:
        if p.id == provider_id:
            return p
    return None


def get_active_provider_id() -> str:
    # Explicit env wins, then persisted file, then default.
    env_id = os.getenv("ZERO_REACHY_CHAT_PROVIDER", "").strip()
    if env_id and get_provider_by_id(env_id):
        return env_id
    try:
        path = _state_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            stored = str(data.get("provider_id", "")).strip()
            if stored and get_provider_by_id(stored):
                return stored
    except Exception as e:
        logger.debug("reachy_chat_provider_read_failed", error=str(e))
    return DEFAULT_PROVIDER_ID


def get_active_provider() -> ChatProvider:
    provider = get_provider_by_id(get_active_provider_id())
    return provider or AVAILABLE_PROVIDERS[0]


def set_active_provider_id(provider_id: str) -> ChatProvider:
    provider = get_provider_by_id(provider_id)
    if not provider:
        raise ValueError(f"Unknown Reachy chat provider id: {provider_id}")
    path = _state_path()
    path.write_text(json.dumps({"provider_id": provider_id}), encoding="utf-8")
    logger.info("reachy_chat_provider_set", provider_id=provider_id)
    return provider
