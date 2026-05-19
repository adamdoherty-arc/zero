"""
Persisted user config for the Reachy realtime bridge.

Stored at ``workspace/reachy/realtime_config.json`` so the user's BYO API keys
and backend/voice/profile preferences survive container restarts without
writing them into env files. This mirrors what the upstream app does when it
persists a key typed into the Gradio textbox into ``instance_path/.env``.

File shape:
    {
      "openai_api_key": "sk-...",
      "gemini_api_key": "AIza...",
      "backend": "local" | "openai" | "gemini",
      "model": "gpt-realtime",
      "voice": "cedar",
      "profile": "default",
    }

Unknown / missing keys fall back to Settings (which read from env). A key
written here overrides the env-sourced default for the next session.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import structlog

from app.infrastructure.config import get_settings
from app.services.reachy_realtime.common import (
    BACKEND_GEMINI,
    BACKEND_LOCAL,
    BACKEND_OPENAI,
    normalize_backend,
    resolve_model,
    resolve_voice,
)

logger = structlog.get_logger()

_LOCK = threading.Lock()
_BACKEND_USER_SELECTED_FIELD = "backend_user_selected"


def _store_path() -> Path:
    settings = get_settings()
    base = Path(settings.workspace_dir).resolve() / "reachy"
    base.mkdir(parents=True, exist_ok=True)
    return base / "realtime_config.json"


def _read() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("realtime_config_read_failed", error=str(e))
        return {}


def _write(data: dict[str, Any]) -> None:
    path = _store_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _mask(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "…"
    return f"{key[:4]}…{key[-4:]}"


def _configured_env_backend() -> str | None:
    raw = os.getenv("ZERO_REACHY_REALTIME_BACKEND") or os.getenv("REACHY_REALTIME_BACKEND")
    return normalize_backend(raw) if raw else None


def _select_backend(
    stored: dict[str, Any],
    *,
    settings_backend: str | None,
    openai_key: str | None,
    gemini_key: str | None,
) -> tuple[str, str]:
    """Choose a realtime backend without letting the old local default win."""
    stored_backend = stored.get("backend")
    if stored_backend and stored.get(_BACKEND_USER_SELECTED_FIELD):
        return normalize_backend(str(stored_backend)), "stored"

    env_backend = _configured_env_backend()
    if env_backend:
        return env_backend, "env"

    if stored_backend:
        legacy_backend = normalize_backend(str(stored_backend))
        if (
            (legacy_backend == BACKEND_OPENAI and openai_key)
            or (legacy_backend == BACKEND_GEMINI and gemini_key)
        ):
            return legacy_backend, "stored_legacy"

    if settings_backend and settings_backend != BACKEND_LOCAL:
        return normalize_backend(settings_backend), "settings"

    if openai_key:
        return BACKEND_OPENAI, "auto_openai_key"
    if gemini_key:
        return BACKEND_GEMINI, "auto_gemini_key"
    return BACKEND_LOCAL, "fallback_local"


def _model_belongs_to_backend(backend: str, model: str | None) -> bool:
    if not model or not model.strip():
        return True
    candidate = model.strip().lower()
    if backend == BACKEND_OPENAI:
        return candidate.startswith(("gpt-", "o"))
    if backend == BACKEND_GEMINI:
        return candidate.startswith("gemini")
    if backend == BACKEND_LOCAL:
        return not candidate.startswith(("gpt-", "gemini", "o"))
    return False


def load_config() -> dict[str, Any]:
    """Return the persisted config merged with Settings defaults."""
    with _LOCK:
        stored = _read()
    settings = get_settings()
    openai_key = stored.get("openai_api_key") or settings.openai_api_key
    gemini_key = stored.get("gemini_api_key") or settings.gemini_api_key
    backend, backend_source = _select_backend(
        stored,
        settings_backend=settings.reachy_realtime_backend,
        openai_key=openai_key,
        gemini_key=gemini_key,
    )
    should_write_migration = (
        backend_source.startswith("auto_")
        and stored.get("backend") != backend
        and not stored.get(_BACKEND_USER_SELECTED_FIELD)
    )
    raw_model = stored.get("model") or settings.reachy_realtime_model
    if not _model_belongs_to_backend(backend, raw_model):
        raw_model = None
        should_write_migration = should_write_migration or not stored.get(_BACKEND_USER_SELECTED_FIELD)
    if should_write_migration:
        with _LOCK:
            latest = _read()
            if not latest.get(_BACKEND_USER_SELECTED_FIELD):
                latest["backend"] = backend
                latest["backend_auto_selected"] = True
                if not _model_belongs_to_backend(backend, latest.get("model")):
                    latest.pop("model", None)
                _write(latest)
    raw_voice = stored.get("voice") or settings.reachy_realtime_voice
    return {
        "openai_api_key": openai_key,
        "gemini_api_key": gemini_key,
        "backend": backend,
        "backend_source": backend_source,
        "backend_user_selected": bool(stored.get(_BACKEND_USER_SELECTED_FIELD)),
        "model": resolve_model(backend, raw_model),
        "voice": resolve_voice(backend, raw_voice),
        "profile": stored.get("profile") or settings.reachy_realtime_profile or "companion",
        # Behavior knobs — consumed by the frontend InteractiveModeBar.
        # idle_timeout_min: auto-disconnect after N minutes of silence.
        # hotkey_enabled : whether Space toggles Interactive Mode globally.
        # cost_cap_usd   : end the live session once this much has been spent.
        "idle_timeout_min": int(stored.get("idle_timeout_min") or 5),
        "hotkey_enabled": bool(stored.get("hotkey_enabled", True)),
        "cost_cap_usd": float(stored.get("cost_cap_usd") or 0),
        # Reasoning mode for the local Qwen3 brain. Default OFF for the
        # voice loop (lowest latency, no <think> blocks). When ON the
        # handler skips ``/no_think`` and passes ``enable_thinking: True``
        # so the model produces ``reasoning_content`` before the spoken
        # reply — better answers, higher latency. Surfaced as a toggle in
        # the Reachy console settings modal.
        "thinking_enabled": bool(stored.get("thinking_enabled", False)),
        # Realtime engine selector — persisted via update_config, surfaced
        # so the frontend and the local handler can branch off it without
        # re-reading the raw JSON.
        "engine": stored.get("engine") or "legacy",
    }


def load_config_masked() -> dict[str, Any]:
    """Load config but never leak full API keys. Safe for GET /config."""
    cfg = load_config()
    return {
        **cfg,
        "openai_api_key": _mask(cfg.get("openai_api_key")),
        "gemini_api_key": _mask(cfg.get("gemini_api_key")),
        "has_openai_key": bool(cfg.get("openai_api_key")),
        "has_gemini_key": bool(cfg.get("gemini_api_key")),
    }


ALLOWED_FIELDS = {
    "openai_api_key", "gemini_api_key", "backend", "model", "voice", "profile",
    "idle_timeout_min", "hotkey_enabled", "cost_cap_usd", _BACKEND_USER_SELECTED_FIELD,
    # Thinking-mode toggle for the local Qwen3 brain (False = voice-loop
    # default, True = reasoning enabled). Read by LocalRealtimeHandler at
    # session start; takes effect on next session, not mid-session.
    "thinking_enabled",
    # Realtime engine selector: "legacy" (current hand-rolled pipeline) or
    # "pipecat" (future Pipecat-backed bridge). The local handler honors this
    # flag at session start; until the Pipecat bridge lands, "pipecat" is a
    # no-op safety alias for legacy.
    "engine",
}


# Hugging Face Space that vends a free OpenAI API key — same path Pollen's own
# Reachy Mini conversation app uses so first-boot users get audio chat without
# pasting a key. Source: reachy-apps/official/reachy_mini_conversation_app/
# src/reachy_mini_conversation_app/console.py:446-459 @ upstream HEAD.
# The Space name + API endpoint are public; the returned key is a shared
# limited-quota OpenAI key provisioned by HuggingFace/Pollen.
_FREE_KEY_HF_SPACE = "HuggingFaceM4/gradium_setup"
_FREE_KEY_API_NAME = "/claim_b_key"


def claim_free_openai_key() -> dict[str, Any]:
    """Fetch a free OpenAI API key from the Pollen/HF Space and persist it.

    Returns a dict ``{"ok": bool, "has_openai_key": bool, "source": "hf_space",
    "error"?: str}``. On success, subsequent realtime sessions can start
    without the user ever pasting an API key. Fails gracefully if
    ``gradio_client`` is missing or the Space is unavailable.
    """
    try:
        from gradio_client import Client  # type: ignore
    except ImportError as e:
        return {"ok": False, "has_openai_key": False, "source": "hf_space",
                "error": f"gradio_client not installed: {e}"}

    try:
        client = Client(_FREE_KEY_HF_SPACE, verbose=False)
        result = client.predict(api_name=_FREE_KEY_API_NAME)
    except Exception as e:
        logger.warning("realtime_free_key_fetch_failed", error=str(e)[:200])
        return {"ok": False, "has_openai_key": False, "source": "hf_space",
                "error": f"free-key Space unreachable: {e}"}

    # gradio_client returns a tuple (key, something) per upstream usage; tolerate
    # both shapes in case the Space schema evolves.
    key: str | None = None
    if isinstance(result, (tuple, list)) and result:
        key = str(result[0] or "").strip() or None
    elif isinstance(result, str):
        key = result.strip() or None

    if not key:
        return {"ok": False, "has_openai_key": False, "source": "hf_space",
                "error": "Space returned no key"}

    # Persist without touching other fields. Also flip backend to openai since
    # the freebie is an OpenAI-only key.
    update_config({"openai_api_key": key, "backend": BACKEND_OPENAI})
    logger.info("realtime_free_key_claimed", source=_FREE_KEY_HF_SPACE,
                key_preview=_mask(key))
    return {"ok": True, "has_openai_key": True, "source": "hf_space",
            "backend": BACKEND_OPENAI}


def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into stored config. Only ``ALLOWED_FIELDS`` are kept.

    Passing explicit ``None`` for an API key clears it. Empty string is treated
    the same as None so the frontend can clear keys by submitting ``""``.
    """
    clean: dict[str, Any] = {}
    for k, v in patch.items():
        if k not in ALLOWED_FIELDS:
            continue
        if isinstance(v, str):
            v = v.strip()
            if not v:
                v = None
        clean[k] = v
    if "backend" in clean and clean["backend"] is not None:
        clean["backend"] = normalize_backend(clean["backend"])
        clean[_BACKEND_USER_SELECTED_FIELD] = True

    with _LOCK:
        stored = _read()
        stored.update(clean)
        # Drop Nones so we never write empty keys.
        stored = {k: v for k, v in stored.items() if v is not None}
        _write(stored)

    # Mirror profile changes into the legacy voice_loop_service so the
    # classic push-to-talk pipeline and the realtime bridge agree on which
    # persona is active. Without this, the user picks Sally in the realtime
    # modal but the classic pipeline keeps using whatever was active before.
    if "profile" in clean and clean["profile"]:
        try:
            from app.services.voice_loop_service import get_voice_loop_service
            get_voice_loop_service().set_persona(str(clean["profile"]))
        except Exception as e:
            logger.debug("voice_loop_profile_mirror_skipped", error=str(e))

    return load_config_masked()
