"""
Runtime provider selector for Reachy's voice-chat fallback intent.

Lets the user toggle between local vLLM and cloud providers (Gemini / Kimi)
without a restart. Selection is persisted to workspace/settings/reachy_chat.json
so it survives container rebuilds and restarts.

Why not use the LLM router? The router optimizes for cost + task_type routing,
but a user picking "Gemini" wants Gemini *every time* for voice replies, not a
model chosen by the router's budget heuristics.
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


# Hand-tuned list — each entry is a (provider, model) pair that UnifiedLLMClient
# knows how to call. Voice replies are short so cheap flash models are fine.
AVAILABLE_PROVIDERS: list[ChatProvider] = [
    ChatProvider(
        id="vllm",
        label="Local vLLM",
        provider="vllm",
        model="qwen3-chat",
        description="Runs on your 5090. Private, free, ~2s response, needs model warm.",
    ),
    ChatProvider(
        id="gemini-flash",
        label="Gemini 3.1 Flash",
        provider="gemini",
        model="gemini-3.1-flash",
        description="Cheap + fast cloud model. Needs ZERO_GEMINI_API_KEY.",
    ),
    ChatProvider(
        id="gemini-pro",
        label="Gemini 3.1 Pro",
        provider="gemini",
        model="gemini-3.1-pro",
        description="Smartest Gemini. Slower and pricier than Flash.",
    ),
    ChatProvider(
        id="kimi-light",
        label="Kimi Light",
        provider="kimi",
        model="moonshot-v1-32k",
        description="Cheap Kimi. Good for short voice replies.",
    ),
    ChatProvider(
        id="kimi-heavy",
        label="Kimi K2.6",
        provider="kimi",
        model="kimi-k2.6",
        description="Top-tier Kimi (April 2026 release). Thinking-optimized, 256K context.",
    ),
]

DEFAULT_PROVIDER_ID = "gemini-flash"


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
