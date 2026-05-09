"""
Router for Reachy realtime voice chat (OpenAI Realtime / Gemini Live).

Three surfaces:

- ``GET  /api/reachy/realtime/config``   — masked config + capability flags.
- ``PUT  /api/reachy/realtime/config``   — update API keys, backend, voice, profile.
- ``GET  /api/reachy/realtime/profiles`` — merged persona / upstream-profile catalog.
- ``WS   /api/reachy/realtime/ws``       — audio bridge (client ↔ provider).

The WS endpoint sits outside Zero's bearer-auth gate (WebSockets bypass the
HTTP middleware) — the first ``start`` frame carries the API key, and the
``api_key`` in memory is never echoed back.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Body, HTTPException, WebSocket
from pydantic import BaseModel, Field

from app.services.reachy_realtime.common import (
    BACKEND_GEMINI,
    BACKEND_LOCAL,
    BACKEND_OPENAI,
    DEFAULT_MODEL_BY_BACKEND,
    DEFAULT_VOICE_BY_BACKEND,
    GEMINI_AVAILABLE_VOICES,
    LOCAL_AVAILABLE_VOICES,
    OPENAI_AVAILABLE_VOICES,
    normalize_backend,
)
from app.services.reachy_realtime import config_store
from app.services.reachy_realtime.config_store import (
    claim_free_openai_key,
    load_config,
    load_config_masked,
    update_config,
)
from app.services.reachy_realtime.profiles import list_profiles, profile_to_dict
from app.services.reachy_realtime.session import RealtimeSession, recover_all_realtime_sessions

logger = structlog.get_logger()

router = APIRouter()


class ConfigUpdate(BaseModel):
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    backend: str | None = None
    model: str | None = None
    voice: str | None = None
    profile: str | None = None
    # Behavior knobs surfaced in the realtime settings dialog.
    idle_timeout_min: int | None = None
    hotkey_enabled: bool | None = None
    cost_cap_usd: float | None = None


def _enriched_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Add capability + catalog fields to a masked config so every endpoint
    that returns config returns the SAME shape. Without this, claim-free-key
    and PUT /config returned partial configs that crashed the dialog when it
    tried to read ``cfg.default_voices['openai']``.
    """
    current = normalize_backend(cfg.get("backend") or BACKEND_LOCAL)
    has_openai = bool(cfg.get("has_openai_key"))
    has_gemini = bool(cfg.get("has_gemini_key"))
    explicit_backend = bool(cfg.get("backend_user_selected"))
    # Local backend is always "available" — the actual vLLM-up check
    # happens at session start so we don't probe on every config read.
    local_available = True
    if current == BACKEND_LOCAL and explicit_backend:
        preferred = BACKEND_LOCAL
    elif current == BACKEND_OPENAI and has_openai:
        preferred = BACKEND_OPENAI
    elif current == BACKEND_GEMINI and has_gemini:
        preferred = BACKEND_GEMINI
    elif has_openai:
        preferred = BACKEND_OPENAI
    elif has_gemini:
        preferred = BACKEND_GEMINI
    else:
        preferred = BACKEND_LOCAL
    return {
        **cfg,
        "preferred_backend": preferred,
        "realtime_available": preferred is not None,
        "has_local": local_available,
        "backends": [BACKEND_OPENAI, BACKEND_GEMINI, BACKEND_LOCAL],
        "default_models": DEFAULT_MODEL_BY_BACKEND,
        "default_voices": DEFAULT_VOICE_BY_BACKEND,
        "voices": {
            BACKEND_OPENAI: list(OPENAI_AVAILABLE_VOICES),
            BACKEND_GEMINI: list(GEMINI_AVAILABLE_VOICES),
            BACKEND_LOCAL: list(LOCAL_AVAILABLE_VOICES),
        },
    }


@router.get("/config")
async def get_config():
    return _enriched_config(config_store.load_config_masked())


@router.put("/config")
async def put_config(payload: ConfigUpdate = Body(...)):
    return _enriched_config(config_store.update_config(payload.model_dump(exclude_unset=True)))


@router.get("/models")
async def list_models(backend: str | None = None):
    """Return models the picker can offer for each backend.

    ``local`` queries the shared LiteLLM router (``vllm_chat_url``) using the
    master key (``vllm_api_key``) so we always show what's actually loadable.
    ``openai`` and ``gemini`` are static catalogs — their realtime models
    aren't enumerated by their public ``/models`` endpoints anyway, so we
    return the curated short-list the rest of the codebase already uses.
    """
    from app.infrastructure.config import get_settings as _gs
    settings = _gs()
    backends = (
        [normalize_backend(backend)]
        if backend
        else [BACKEND_OPENAI, BACKEND_GEMINI, BACKEND_LOCAL]
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for b in backends:
        if b == BACKEND_OPENAI:
            out[b] = [
                {"id": "gpt-realtime", "label": "GPT Realtime",
                 "description": "OpenAI's flagship realtime audio model."},
                {"id": "gpt-4o-realtime-preview", "label": "GPT-4o Realtime (preview)",
                 "description": "Older preview; still works, slightly slower."},
            ]
        elif b == BACKEND_GEMINI:
            out[b] = [
                {"id": "gemini-3.1-flash-live-preview", "label": "Gemini 3.1 Flash Live",
                 "description": "Latest Gemini realtime — fast, cheap."},
                {"id": "gemini-2.5-flash-live-preview", "label": "Gemini 2.5 Flash Live",
                 "description": "Older, more widely tested."},
            ]
        elif b == BACKEND_LOCAL:
            # Probe the local chat endpoint (llama.cpp serving the
            # Qwen3.6-35B-A3B abliterated MoE on :18800). One container,
            # one model — the dual-vLLM setup was retired 2026-04-28 in
            # favor of the abliterated MoE which serves both brain AND
            # voice-loop use cases at MoE-class TTFT.
            local_endpoints = [
                ("http://host.docker.internal:18800/v1",
                 "llama.cpp (Qwen3.6-35B-A3B abliterated, Q4_K_M)"),
            ]
            seen: set[str] = set()
            models = []
            async with httpx.AsyncClient(timeout=3.0) as client:
                for endpoint, label in local_endpoints:
                    try:
                        r = await client.get(
                            f"{endpoint}/models",
                            headers={"Authorization": "Bearer EMPTY"},
                        )
                        if r.status_code != 200:
                            continue
                        data = (r.json() or {}).get("data") or []
                        for m in data:
                            mid = m.get("id") or ""
                            if not mid or mid in seen:
                                continue
                            if "embed" in mid.lower():
                                continue  # hide embedding-only models
                            seen.add(mid)
                            models.append({
                                "id": mid,
                                "label": mid,
                                "description": label,
                            })
                    except Exception as e:
                        logger.debug(
                            "local_endpoint_probe_failed",
                            endpoint=endpoint,
                            error=str(e),
                        )
            out[b] = models or [
                {"id": "qwen3-chat", "label": "qwen3-chat",
                 "description": "default (local backend unreachable)"}
            ]
    return {"backends": out}


@router.post("/claim-free-key")
async def claim_free_key():
    """Fetch a free OpenAI API key from Pollen's Hugging Face Space.

    Same bootstrap the native Reachy Mini conversation app uses when no
    OPENAI_API_KEY is set — lets users get audio chat working without a
    personal API key. The key is a shared HF/Pollen-provisioned one with
    limited quota; treat it as a best-effort convenience, not a long-term key.
    """
    result = config_store.claim_free_openai_key()
    # Same shape as GET /config so the dialog can ``setCfg(result.config)``
    # without losing voices/default_voices/backends and crashing on the next
    # render.
    result["config"] = _enriched_config(config_store.load_config_masked())
    return result


# ---------------------------------------------------------------------------
# Voice preview — generate a short TTS sample of the selected voice so users
# can hear what they're picking before committing. Uses the same realtime
# config keys (no extra auth surface).
# ---------------------------------------------------------------------------

_PREVIEW_SAMPLE_TEXT = (
    "Hi, I'm Reachy. This is what I sound like when we chat live."
)

# Mapping OpenAI Realtime voice → closest edge-tts voice. Used when the
# user's OpenAI key lacks TTS scope (the free HF-claimed key is realtime-only)
# so we can still give them voice character feedback.
_OPENAI_TO_EDGE_TTS: dict[str, str] = {
    "alloy":   "en-US-AvaNeural",
    "ash":     "en-US-BrianNeural",
    "ballad":  "en-US-AndrewNeural",
    "cedar":   "en-US-GuyNeural",
    "coral":   "en-US-EmmaNeural",
    "echo":    "en-US-ChristopherNeural",
    "marin":   "en-US-JennyNeural",
    "sage":    "en-US-MichelleNeural",
    "shimmer": "en-US-AriaNeural",
    "verse":   "en-US-RogerNeural",
}


async def _edge_tts_preview(voice_name: str, edge_voice: str, label_backend: str) -> dict:
    """Fall through to edge-tts when the chosen backend's native TTS is
    unavailable (no key scope, no public endpoint, etc.). Always renders SOME
    audio so the user can pick a voice with their ears, not just the name.
    """
    from app.services.tts_service import get_tts_service
    tts = get_tts_service()
    audio_bytes = await asyncio.wait_for(
        tts.synthesize(_PREVIEW_SAMPLE_TEXT, voice_override=edge_voice),
        timeout=8.0,
    )
    if not audio_bytes:
        raise HTTPException(500, "TTS produced no audio")
    return {
        "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
        "mime": "audio/mpeg",
        "backend": label_backend,
        "voice": voice_name,
        "sample_text": _PREVIEW_SAMPLE_TEXT,
        "note": (
            f"Approximation — {label_backend.title()} doesn't expose a standalone "
            f"TTS endpoint for '{voice_name}'. Live realtime session uses the real voice."
        ),
    }


class VoicePreviewRequest(BaseModel):
    backend: str = Field(..., description="openai | gemini")
    voice: str = Field(..., min_length=1, max_length=64)


@router.post("/voice-preview")
async def voice_preview(payload: VoicePreviewRequest):
    """Synthesize a short TTS sample of ``voice`` so the user can hear it.

    OpenAI: hits ``/audio/speech`` with ``gpt-4o-mini-tts``. ~$0.0003 per call.
    Gemini: falls back to edge-tts (en-US-AriaNeural) since Gemini Live's
    voices aren't exposed via a standalone TTS endpoint.

    Returns ``{audio_b64, mime}`` so the browser can play directly:
        new Audio(`data:${mime};base64,${audio_b64}`).play()
    """
    backend = normalize_backend(payload.backend)
    cfg = load_config()  # raw, not masked — we need the real keys here

    if backend == BACKEND_OPENAI:
        api_key = (cfg.get("openai_api_key") or "").strip()
        if not api_key:
            raise HTTPException(400, "OpenAI key not configured")
        # gpt-4o-mini-tts only accepts a subset of voices. Realtime-only
        # voices (cedar, marin, verse) get mapped to the closest TTS-supported
        # one so the preview is audible even if it's not byte-identical to
        # what plays during a live session.
        _TTS_FALLBACK = {
            "cedar": "ash",
            "marin": "alloy",
            "verse": "fable",
        }
        tts_voice = _TTS_FALLBACK.get(payload.voice, payload.voice)
        approx = tts_voice != payload.voice
        # 401/403 on /audio/speech means the key lacks TTS scope (e.g. the
        # free HF-claimed key is realtime-only). Fall through to edge-tts.
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini-tts",
                        "voice": tts_voice,
                        "input": _PREVIEW_SAMPLE_TEXT,
                        "response_format": "mp3",
                    },
                )
                # If a voice we DIDN'T expect to need a fallback errors out,
                # one retry with "alloy" so the preview stays useful.
                if resp.status_code == 400 and not approx:
                    logger.info("voice_preview_openai_unknown_voice_retry", voice=payload.voice)
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/speech",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "gpt-4o-mini-tts",
                            "voice": "alloy",
                            "input": _PREVIEW_SAMPLE_TEXT,
                            "response_format": "mp3",
                        },
                    )
                    approx = True
                if resp.status_code in (401, 403):
                    # No TTS scope on this key — gracefully degrade to edge-tts.
                    logger.info(
                        "voice_preview_openai_no_tts_scope_falling_back_to_edge",
                        voice=payload.voice, status=resp.status_code,
                    )
                    edge_voice = _OPENAI_TO_EDGE_TTS.get(payload.voice, "en-US-AriaNeural")
                    return await _edge_tts_preview(payload.voice, edge_voice, "openai")
                if resp.status_code >= 400:
                    err = resp.text[:200]
                    logger.warning("voice_preview_openai_failed", voice=payload.voice, status=resp.status_code, error=err)
                    raise HTTPException(resp.status_code, f"OpenAI TTS failed: {err}")
                audio = resp.content
        except httpx.RequestError as e:
            raise HTTPException(502, f"OpenAI unreachable: {e}")
        return {
            "audio_b64": base64.b64encode(audio).decode("ascii"),
            "mime": "audio/mpeg",
            "backend": "openai",
            "voice": payload.voice,
            "sample_text": _PREVIEW_SAMPLE_TEXT,
            "note": (
                f"Approximation — '{payload.voice}' isn't in the TTS catalog; "
                f"playing closest match. Live realtime session will use the real voice."
            ) if approx else None,
        }

    if backend == BACKEND_GEMINI:
        # Gemini Live voices aren't available via a vanilla TTS endpoint, so
        # render with edge-tts as a "good enough" approximation. Gives the
        # user voice character feedback even if it's not byte-identical.
        _GEMINI_TO_EDGE_TTS: dict[str, str] = {
            "Aoede":  "en-US-EmmaNeural",
            "Charon": "en-US-AndrewNeural",
            "Fenrir": "en-US-BrianNeural",
            "Kore":   "en-US-AvaNeural",
            "Leda":   "en-US-JennyNeural",
            "Orus":   "en-US-EricNeural",
            "Puck":   "en-GB-RyanNeural",
            "Zephyr": "en-US-SteffanNeural",
        }
        edge_voice = _GEMINI_TO_EDGE_TTS.get(payload.voice, "en-US-AriaNeural")
        try:
            return await _edge_tts_preview(payload.voice, edge_voice, "gemini")
        except asyncio.TimeoutError:
            raise HTTPException(504, "TTS timed out")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("voice_preview_gemini_failed", voice=payload.voice, error=str(e)[:200])
            raise HTTPException(500, f"Gemini preview failed: {e}")

    if backend == BACKEND_LOCAL:
        # Local backend voices are Piper / Edge-TTS strings the TTSService
        # already understands. Render through the same TTS used during a live
        # session so the preview is byte-identical to what plays.
        try:
            from app.services.reachy_realtime.local_handler import (
                _is_edge_tts_voice,
                _is_piper_voice,
            )
            from app.services.tts_service import get_tts_service

            tts = get_tts_service()
            voice_override = payload.voice if (
                payload.voice.startswith("fish:") or _is_edge_tts_voice(payload.voice)
            ) else None
            if _is_piper_voice(payload.voice):
                await tts.set_piper_voice(payload.voice)
            audio_bytes, meta = await asyncio.wait_for(
                tts.synthesize_with_meta(_PREVIEW_SAMPLE_TEXT, voice_override=voice_override),
                timeout=8.0,
            )
            if not audio_bytes:
                raise HTTPException(500, "TTS produced no audio")
            return {
                "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
                "mime": "audio/wav",
                "backend": "local",
                "voice": payload.voice,
                "actual_voice": meta.get("voice"),
                "engine": meta.get("engine"),
                "sample_text": _PREVIEW_SAMPLE_TEXT,
            }
        except asyncio.TimeoutError:
            raise HTTPException(504, "TTS timed out")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("voice_preview_local_failed", voice=payload.voice, error=str(e)[:200])
            raise HTTPException(500, f"Local preview failed: {e}")

    raise HTTPException(400, f"Unknown backend: {backend}")


@router.get("/profiles")
async def list_profiles_endpoint(include_instructions: bool = False):
    profiles = [profile_to_dict(p, include_instructions=include_instructions) for p in list_profiles()]
    return {"profiles": profiles, "count": len(profiles)}


# ---- Per-persona voice / model editor -------------------------------------
#
# These rewrite the persona's filesystem files (voice.txt / model.txt) under
# ``backend/app/data/reachy_profiles/<persona_id>/``, then bust the lru_cache
# so the realtime profile loader picks the change up on the next read.
# The Voice Settings UI uses these to change a persona's bound voice/model
# without the user editing files.

@router.put("/profiles/{persona_id}/voice")
async def set_profile_voice(persona_id: str, voice: str = Body(..., embed=True)):
    return _write_profile_field(persona_id, "voice.txt", voice)


@router.put("/profiles/{persona_id}/model")
async def set_profile_model(persona_id: str, model: str = Body(..., embed=True)):
    return _write_profile_field(persona_id, "model.txt", model)


def _write_profile_field(persona_id: str, filename: str, value: str) -> dict:
    import re
    from pathlib import Path
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", persona_id or ""):
        raise HTTPException(400, "persona_id must be lowercase alphanumeric")
    value = (value or "").strip()
    if len(value) > 128:
        raise HTTPException(400, "value too long")
    profiles_dir = Path(__file__).resolve().parents[1] / "data" / "reachy_profiles"
    p_dir = profiles_dir / persona_id
    if not p_dir.is_dir():
        raise HTTPException(404, f"persona '{persona_id}' has no profile directory")
    target = p_dir / filename
    if value:
        target.write_text(value + "\n", encoding="utf-8")
    elif target.exists():
        target.unlink()
    # Bust profile cache so the next list_profiles call re-reads from disk.
    try:
        from app.services.reachy_realtime.profiles import _all_profiles
        _all_profiles.cache_clear()
    except Exception:
        pass
    # If the active realtime profile matches, mirror the new value into the
    # realtime config too — without this, picking a voice on Sally only
    # changes the next persona-select cycle, not the current saved state.
    try:
        from app.services.reachy_realtime.config_store import load_config_masked, update_config
        cfg = load_config_masked()
        if cfg.get("profile") == persona_id:
            patch_key = "voice" if filename == "voice.txt" else "model"
            update_config({patch_key: value or None})
    except Exception:
        pass
    return {"ok": True, "persona_id": persona_id, filename.replace(".txt", ""): value}


# ---- Companion memory (tier-2 + tier-3) ----------------------------------
#
# Tier-2 = pgvector RAG over recorded user utterances. Tier-3 = JSON
# summary {user_likes, shared_moments, current_mood, relationship_level}
# regenerated every SUMMARY_TURN_INTERVAL turns. Both are persona+user
# scoped. The single-user assistant uses ``user_id="default"``.

@router.get("/memory/{user_id}/{persona_id}")
async def get_companion_memory(user_id: str, persona_id: str, k: int = 10):
    """Return the persona's relationship summary plus the most-recent N
    raw memories. Used by the unified settings modal's Memory tab."""
    from app.services.reachy_memory import get_reachy_memory_service
    mem = get_reachy_memory_service()
    summary = mem.load_summary(user_id, persona_id)
    # Recent memories: query with an empty-ish sentinel; pgvector falls back
    # to recency if the embedding match is weak. Cheap and good enough for
    # a "what does she remember about me" view.
    try:
        recent = await mem.semantic_search(user_id, persona_id, "recent moments", k=k)
    except Exception as e:
        logger.warning("companion_memory_recent_failed", error=str(e))
        recent = []
    return {
        "user_id": user_id,
        "persona_id": persona_id,
        "summary": summary.to_json(),
        "recent_memories": recent,
    }


# ---- Voice cloning (Fish-Speech reference samples) ------------------------

@router.post("/voices/clone")
async def upload_voice_clone(
    voice_id: str = Body(..., embed=True),
    audio_b64: str = Body(..., embed=True),
):
    """Store a reference clip for Fish-Speech to clone. ``audio_b64`` should be
    a 10-30 second WAV-encoded sample. Files are written to
    ``backend/app/data/voice_clones/<voice_id>.wav`` and become available as
    voice id ``fish:<voice_id>`` in the TTS engine."""
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", voice_id or ""):
        raise HTTPException(400, "voice_id must be lowercase alphanumeric (with - or _), <= 64 chars")
    try:
        audio = base64.b64decode(audio_b64, validate=True)
    except Exception as e:
        raise HTTPException(400, f"audio_b64 not valid base64: {e}")
    if len(audio) < 4_000:
        raise HTTPException(400, "reference clip too small (need ≥ ~10 sec of WAV)")
    from pathlib import Path
    clone_dir = Path(__file__).resolve().parents[1] / "data" / "voice_clones"
    clone_dir.mkdir(parents=True, exist_ok=True)
    target = clone_dir / f"{voice_id}.wav"
    target.write_bytes(audio)
    logger.info("voice_clone_uploaded", voice_id=voice_id, bytes=len(audio))
    return {"ok": True, "voice_id": f"fish:{voice_id}", "size_bytes": len(audio)}


@router.delete("/memory/{user_id}/{persona_id}")
async def clear_companion_memory(user_id: str, persona_id: str):
    """Wipe both the tier-3 summary and tier-2 vector memories for a
    persona. Permanent — no undo."""
    from app.services.reachy_memory import get_reachy_memory_service
    mem = get_reachy_memory_service()
    mem.clear(user_id, persona_id)
    return {"cleared": True, "user_id": user_id, "persona_id": persona_id}


@router.post("/recover")
async def recover_realtime_session(reason: str = Body("manual", embed=True)):
    """Recover active realtime voice sessions without restarting Reachy."""
    result = await recover_all_realtime_sessions(reason=reason or "manual")
    try:
        from app.routers.reachy import _assistant_status_payload
        status = await _assistant_status_payload(actions=[{
            "id": "realtime_recover",
            "ok": True,
            "detail": "Recovered active realtime voice session.",
            "result": result,
        }])
    except Exception as e:
        status = {"state": "degraded", "error": str(e)}
    return {"ok": True, "recover": result, "assistant": status}


@router.websocket("/ws")
async def realtime_ws(ws: WebSocket) -> None:
    session = RealtimeSession(ws)
    await session.run()
