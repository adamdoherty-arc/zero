"""
Zero Host Audio Agent.

Runs on the Windows host (outside Docker) so it can access pyaudiowpatch,
sounddevice, and USB audio devices like the Reachy Mini microphone. Records
meetings into Zero's shared PostgreSQL database, so meetings created here
appear in Zero's UI without any extra plumbing.

Run:
    cd c:\\code\\zero\\host_agent
    .venv\\Scripts\\python -m uvicorn main:app --host 0.0.0.0 --port 18796

Environment:
    ZERO_POSTGRES_URL   asyncpg-compatible URL (defaults to localhost:5433/zero)
    ZERO_RECORDINGS_DIR absolute path for WAV output (defaults to ./recordings)
    REACHY_API_URL      Reachy desktop daemon (defaults to http://localhost:8000)
    HOST_AGENT_HOST     listening address (defaults to 0.0.0.0 for Docker access)
    HOST_AGENT_PORT     listening port (defaults to 18796; 18794 is often held by Docker Desktop)

    ZERO_PREFERRED_MIC_DEVICE   substring match (case-insensitive) used when no
                                explicit mic_device_index is passed on /record/start
    REACHY_TTS_CONFIRMATIONS    "true"/"false", default true
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import time
import uuid as uuid_mod
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
import httpx
import numpy as np
import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

# Pick up the shared c:\code\zero\.env before any os.getenv() calls below so
# the host_agent inherits the same secrets / URLs as zero-api.
try:
    from dotenv import load_dotenv
    _shared_env = Path(__file__).parent.parent / ".env"
    if _shared_env.exists():
        load_dotenv(_shared_env)
except Exception:
    pass

from audio_capture import (
    AudioCapture,
    list_audio_devices,
    find_default_mic_index,
    preferred_mic_indices,
)
from camera_worker import get_camera_worker
from docker_readiness import get_docker_readiness, init_docker_readiness
from live_transcription import get_live_transcription
from speaker_process import SpeakerProcessSink
from speaker_stream import list_output_devices
from supervisor import get_supervisor
from voice_capture import VoiceCapture
from wake_loop import WakeLoop
from whisper_wake_loop import WhisperWakeLoop
from openwakeword_loop import OpenWakeWordLoop

logger = structlog.get_logger()


def _rewrite_for_host(dsn: str) -> str:
    """
    Translate a Zero-api-shaped DSN into something reachable from the Windows
    host process. Zero-api uses Docker-internal hostnames — this process is
    outside Docker, so we remap them to the ports published on the host.
    """
    out = dsn.replace("postgresql+asyncpg://", "postgresql://")
    out = out.replace("postgresql+psycopg://", "postgresql://")
    # Docker-compose zero-postgres: published as localhost:5434
    # (Legion's PG is on :5433, native host PG on :5432 — zero gets :5434.)
    out = out.replace("@zero-postgres:5432/", "@localhost:5434/")
    # Some .env variants point at host.docker.internal — that's a Docker-only
    # alias; replace with localhost but keep the port the user configured.
    out = out.replace("@host.docker.internal:", "@localhost:")
    return out


POSTGRES_URL = _rewrite_for_host(
    os.getenv("ZERO_POSTGRES_URL", "postgresql://zero:zero_dev@localhost:5433/zero")
)

# Write WAVs into Zero's shared workspace/recordings so zero-api (Docker) can
# open them for transcription — the zero-api container mounts ./workspace into
# /app/workspace, so `c:/code/zero/workspace/recordings/X.wav` on the host is
# visible as `/app/workspace/recordings/X.wav` inside the container.
_DEFAULT_RECORDINGS_DIR = (
    Path(__file__).parent.parent / "workspace" / "recordings"
)
RECORDINGS_DIR = Path(
    os.getenv("ZERO_RECORDINGS_DIR", str(_DEFAULT_RECORDINGS_DIR))
).resolve()
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_RATE = int(os.getenv("ZERO_SAMPLE_RATE", "16000"))
REACHY_API_URL = os.getenv("REACHY_API_URL", "http://localhost:8000").rstrip("/")
PREFERRED_MIC = os.getenv("ZERO_PREFERRED_MIC_DEVICE") or None
HOST_MIC_REJECT_DIGITAL_SILENCE = os.getenv(
    "ZERO_HOST_MIC_REJECT_DIGITAL_SILENCE", "false"
).lower() in ("1", "true", "yes")
HOST_MIC_PROBE_SECONDS = float(os.getenv("ZERO_HOST_MIC_PROBE_SECONDS", "0.35"))
HOST_MIC_MIN_RMS = float(os.getenv("ZERO_HOST_MIC_MIN_RMS", "0.00005"))
HOST_MIC_MIN_PEAK = float(os.getenv("ZERO_HOST_MIC_MIN_PEAK", "0.00020"))
HOST_MIC_SDK_FALLBACK = os.getenv("ZERO_HOST_MIC_SDK_FALLBACK", "true").lower() in (
    "1",
    "true",
    "yes",
)
HOST_MIC_SDK_FIRST_FRAME_TIMEOUT = float(
    os.getenv("ZERO_HOST_MIC_SDK_FIRST_FRAME_TIMEOUT", "2.0")
)
TTS_CONFIRMATIONS = os.getenv("REACHY_TTS_CONFIRMATIONS", "true").lower() in ("1", "true", "yes")
HOST_AGENT_HOST = os.getenv("HOST_AGENT_HOST", "0.0.0.0").strip() or "0.0.0.0"
HOST_AGENT_PORT = int(os.getenv("HOST_AGENT_PORT", "18796"))
HOST_AGENT_WARMUP = os.getenv("ZERO_HOST_AGENT_WARMUP", "false").lower() in ("1", "true", "yes")

# After a recording stops, the host agent calls this URL to kick off Zero's
# Whisper + summary pipeline (which lives in zero-api, not here).
ZERO_API_URL = os.getenv("ZERO_API_URL", "http://localhost:18792").rstrip("/")

# Wake loop configuration.
# ZERO_WAKE_MODE:
#   "porcupine"    -> pvporcupine (needs ZERO_PICOVOICE_ACCESS_KEY)
#   "openwakeword" -> local ONNX model (no key, default is hey_jarvis)
#   "whisper"      -> continuous Whisper "tiny" scanning for "hey zero"
#                     (legacy; unreliable — hallucinates YouTube filler)
#   "auto"         -> openwakeword > porcupine > whisper, pick first viable
#   "off"          -> no continuous listening; button / hotkey only
WAKE_MODE = os.getenv("ZERO_WAKE_MODE", "auto").strip().lower()
PICOVOICE_ACCESS_KEY = (
    os.getenv("ZERO_PICOVOICE_ACCESS_KEY")
    or os.getenv("PICOVOICE_ACCESS_KEY")
    or ""
).strip()
# Porcupine keyword (its built-in free list: jarvis, computer, terminator,
# bumblebee, picovoice, etc.). Ignored in openwakeword/whisper modes.
WAKE_KEYWORD = os.getenv("ZERO_WAKE_KEYWORD", "jarvis").strip().lower()
# openWakeWord keyword. Built-in free models: hey_jarvis, alexa, hey_mycroft,
# hey_rhasspy. Set ZERO_OWW_MODEL_PATH to point at a custom .onnx if you
# trained your own "hey reachy".
OWW_KEYWORD = os.getenv("ZERO_OWW_KEYWORD", "hey_jarvis").strip().lower()
OWW_MODEL_PATH = (os.getenv("ZERO_OWW_MODEL_PATH") or "").strip() or None
OWW_THRESHOLD = float(os.getenv("ZERO_OWW_THRESHOLD", "0.5"))
WAKE_PHRASE = os.getenv("ZERO_WAKE_PHRASE", "hey zero").strip().lower()
WAKE_WHISPER_MODEL = os.getenv("ZERO_WAKE_WHISPER_MODEL", "tiny").strip()
WAKE_SCAN_WHISPER_MODEL = os.getenv("ZERO_WAKE_SCAN_WHISPER_MODEL", "tiny").strip()


def _can_use_openwakeword() -> bool:
    """Probe whether openwakeword is importable + has its shipped models."""
    try:
        import openwakeword  # noqa: F401
        import os as _os
        pkg_dir = _os.path.dirname(openwakeword.__file__)
        rdir = _os.path.join(pkg_dir, "resources", "models")
        if not _os.path.isdir(rdir):
            return False
        # Look for at least the embedding + one keyword model.
        have = set(_os.listdir(rdir))
        return any(f.startswith("embedding_model") for f in have) and any(
            f.startswith("hey_jarvis") or f.startswith("alexa") for f in have
        )
    except Exception:
        return False

# Shared singleton state
_pool: Optional[asyncpg.Pool] = None
_capture: Optional[AudioCapture] = None
_active_meeting_id: Optional[str] = None
_wake_loop: Optional[object] = None  # WakeLoop or WhisperWakeLoop
_wake_mode_actual: str = "off"
_wake_start_task: Optional[asyncio.Task] = None
_voice_capture: Optional[VoiceCapture] = None
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def _resolve_wake_mode(mode: str) -> str:
    requested = (mode or "off").strip().lower()
    if requested == "auto":
        if _can_use_openwakeword():
            return "openwakeword"
        if PICOVOICE_ACCESS_KEY:
            return "porcupine"
        return "whisper"
    return requested


def _wake_unavailable_status() -> dict:
    requested = WAKE_MODE
    if requested == "off":
        return {
            "running": False,
            "mode": _wake_mode_actual,
            "requested_mode": requested,
            "resolved_mode": "off",
            "openwakeword_available": None,
            "picovoice_key_configured": bool(PICOVOICE_ACCESS_KEY),
            "reason": "Wake loop disabled by ZERO_WAKE_MODE=off.",
        }
    resolved = _resolve_wake_mode(requested)
    openwakeword_available = _can_use_openwakeword()
    reason = "Wake loop off."
    if resolved == "openwakeword" and not openwakeword_available:
        reason = "openWakeWord is selected but its resources are not available."
    elif resolved == "porcupine" and not PICOVOICE_ACCESS_KEY:
        reason = "Porcupine is selected but ZERO_PICOVOICE_ACCESS_KEY is missing."
    elif resolved == "whisper":
        reason = "Wake loop is not running; whisper fallback is available."
    return {
        "running": False,
        "mode": _wake_mode_actual,
        "requested_mode": requested,
        "resolved_mode": resolved,
        "openwakeword_available": openwakeword_available,
        "picovoice_key_configured": bool(PICOVOICE_ACCESS_KEY),
        "reason": reason,
    }


def _build_wake_loop(mode: str, mic_idx: int | None):
    if mode == "porcupine":
        if not PICOVOICE_ACCESS_KEY:
            raise RuntimeError("Porcupine requires ZERO_PICOVOICE_ACCESS_KEY")
        return WakeLoop(
            access_key=PICOVOICE_ACCESS_KEY,
            keyword=WAKE_KEYWORD,
            device_index=mic_idx,
            on_command=_on_wake_command,
            whisper_model=WAKE_WHISPER_MODEL,
        )
    if mode == "openwakeword":
        if not _can_use_openwakeword():
            raise RuntimeError("openWakeWord resources are not available")
        return OpenWakeWordLoop(
            keyword=OWW_KEYWORD,
            model_path=OWW_MODEL_PATH,
            threshold=OWW_THRESHOLD,
            device_index=mic_idx,
            on_command=_on_wake_command,
            whisper_model=WAKE_WHISPER_MODEL,
        )
    if mode == "whisper":
        return WhisperWakeLoop(
            keyword=WAKE_PHRASE,
            device_index=mic_idx,
            on_command=_on_wake_command,
            whisper_model=WAKE_SCAN_WHISPER_MODEL,
        )
    raise RuntimeError(f"Unknown wake mode: {mode!r}")


async def _start_wake_loop_background(chosen_mode: str) -> None:
    """Start wake detection without blocking host_agent readiness."""
    global _wake_loop, _wake_mode_actual
    try:
        mic_idx = await asyncio.to_thread(find_default_mic_index, PREFERRED_MIC)
        loop = _build_wake_loop(chosen_mode, mic_idx)
        await asyncio.to_thread(loop.start)
        _wake_loop = loop
        _wake_mode_actual = chosen_mode
        logger.info("wake_loop_ready", mode=chosen_mode, mic_device_index=mic_idx)
    except Exception as e:
        logger.warning(
            "wake_loop_start_failed",
            mode=chosen_mode,
            error=str(e),
        )
        _wake_loop = None
        _wake_mode_actual = "off"


def _get_voice_capture() -> VoiceCapture:
    global _voice_capture
    if _voice_capture is None:
        mic_idx = find_default_mic_index(PREFERRED_MIC)
        _voice_capture = VoiceCapture(
            mic_device_index=mic_idx,
            whisper_model=WAKE_WHISPER_MODEL,
        )
    return _voice_capture


# ---------------------------------------------------------------------------
# Lifecycle + DB helpers
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool, _wake_loop, _main_loop, _wake_start_task
    _main_loop = asyncio.get_running_loop()

    async def _db_startup_background() -> None:
        global _pool
        try:
            _pool = await asyncio.wait_for(
                asyncpg.create_pool(POSTGRES_URL, min_size=1, max_size=5),
                timeout=float(os.getenv("ZERO_HOST_AGENT_DB_STARTUP_TIMEOUT_S", "5")),
            )
            logger.info("host_agent_db_pool_ready", dsn=_safe_dsn(POSTGRES_URL))
        except Exception as e:
            logger.warning(
                "host_agent_db_pool_init_failed",
                dsn=_safe_dsn(POSTGRES_URL),
                error=str(e),
                hint="Start Postgres (docker compose up zero-postgres) and restart the agent",
            )
            _pool = None

    asyncio.create_task(_db_startup_background(), name="db_pool_startup")

    # Start Docker readiness probe and let the supervisor consult it. This
    # never blocks lifespan: the probe stays in "waiting" until Docker comes
    # up, while host_agent's /health responds immediately so the UI works.
    try:
        readiness = init_docker_readiness(ZERO_API_URL)
        readiness.start()
        get_supervisor().attach_docker_readiness(readiness.get_status)
        logger.info("docker_readiness_attached", backend_url=ZERO_API_URL)
    except Exception as e:
        logger.warning("docker_readiness_init_failed", error=str(e))

    # Decide which wake loop (if any) to start. Wake initialization touches
    # Windows audio APIs, so keep it off the startup path; host_agent should
    # become reachable even if a microphone driver stalls.
    chosen_mode = _resolve_wake_mode(WAKE_MODE)
    global _wake_mode_actual
    if chosen_mode != "off":
        _wake_mode_actual = chosen_mode
        _wake_start_task = asyncio.create_task(
            _start_wake_loop_background(chosen_mode),
            name="wake_loop_start",
        )
    else:
        logger.info("wake_loop_disabled", mode=chosen_mode)
        _wake_mode_actual = "off"

    # Resume watchdog if it was enabled before host_agent was restarted.
    # Keep this off the lifespan critical path; the Windows daemon/COM probe
    # can stall during unplug/replug recovery and /health must still come up.
    async def _watchdog_resume_background() -> None:
        await asyncio.sleep(2.0)
        try:
            await get_supervisor().start_watchdog_if_enabled()
        except Exception as e:
            logger.warning("watchdog_resume_failed", error=str(e))

    asyncio.create_task(_watchdog_resume_background(), name="watchdog_resume")

    # Pre-warm the push-to-talk Whisper model so the first voice turn doesn't
    # pay a 9-10 s cold start. Runs in background so lifespan keeps moving.
    async def _voice_warmup() -> None:
        try:
            vc = _get_voice_capture()
            warm = await asyncio.get_event_loop().run_in_executor(None, vc.warmup)
            logger.info("voice_capture_warmed", **warm)
        except Exception as e:
            logger.warning("voice_capture_warmup_failed", error=str(e))

    if HOST_AGENT_WARMUP:
        asyncio.create_task(_voice_warmup(), name="voice_warmup")
    else:
        logger.info("voice_capture_warmup_skipped")

    # Pre-warm the live-transcript Whisper model too, so the first segment in
    # a meeting recording lands within ~3 s instead of paying the cold start
    # mid-recording. Background, non-blocking.
    async def _live_warmup() -> None:
        try:
            live = get_live_transcription()
            await asyncio.get_event_loop().run_in_executor(None, live.load_model)
            logger.info("live_transcription_warmed", model=live.model_size)
        except Exception as e:
            logger.warning("live_transcription_warmup_failed", error=str(e))

    if HOST_AGENT_WARMUP:
        asyncio.create_task(_live_warmup(), name="live_warmup")
    else:
        logger.info("live_transcription_warmup_skipped")

    logger.info("host_agent_lifespan_ready")
    yield

    if _wake_start_task is not None and not _wake_start_task.done():
        _wake_start_task.cancel()
    if _wake_loop is not None:
        _wake_loop.stop()
    try:
        readiness = get_docker_readiness()
        if readiness is not None:
            await readiness.stop()
    except Exception:
        pass
    try:
        sup = get_supervisor()
        if sup.is_running():
            await sup.stop()
    except Exception:
        pass
    if _pool is not None:
        await _pool.close()


def _safe_dsn(dsn: str) -> str:
    # Hide password in logs.
    try:
        at = dsn.index("@")
        slash = dsn.index("//")
        return dsn[:slash + 2] + "***@" + dsn[at + 1:]
    except ValueError:
        return dsn


async def _db() -> asyncpg.Pool:
    if _pool is None:
        raise HTTPException(
            503,
            "DB pool unavailable — start Postgres and restart the host agent",
        )
    return _pool


def _get_capture(
    *,
    mic_device_index: int | None = None,
    system_device_index: int | None = None,
) -> AudioCapture:
    global _capture
    if mic_device_index is None:
        mic_device_index = find_default_mic_index(PREFERRED_MIC)
    needs_new = (
        _capture is None
        or (not _capture.is_recording and (
            _capture.mic_device_index != mic_device_index
            or _capture.system_device_index != system_device_index
        ))
    )
    if needs_new:
        _capture = AudioCapture(
            sample_rate=SAMPLE_RATE,
            mic_device_index=mic_device_index,
            system_device_index=system_device_index,
        )
    return _capture


# ---------------------------------------------------------------------------
# App + routes
# ---------------------------------------------------------------------------

app = FastAPI(title="Zero Host Audio Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartRecordingRequest(BaseModel):
    meeting_id: Optional[str] = None
    title: Optional[str] = None
    source: str = "mic"  # default "mic" (Reachy-only); override to "mixed"/"system"
    mic_device_index: Optional[int] = None
    system_device_index: Optional[int] = None


@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": app.version,
        "host": HOST_AGENT_HOST,
        "port": HOST_AGENT_PORT,
        "db_ready": _pool is not None,
        "reachy_api_url": REACHY_API_URL,
        "recordings_dir": str(RECORDINGS_DIR),
        "wake": _wake_loop.status() if _wake_loop else _wake_unavailable_status(),
    }


# ---------------------------------------------------------------------------
# Push-to-talk / hotkey-driven voice capture
# ---------------------------------------------------------------------------

@app.get("/voice/status")
async def voice_status():
    """Whether a click-to-start voice capture is active right now."""
    vc = _voice_capture
    return vc.status() if vc is not None else {"capturing": False}


@app.post("/voice/start")
async def voice_start():
    """
    Start buffering audio from the Reachy mic. Returns immediately. The UI
    then calls POST /voice/stop when the user clicks the button again.
    """
    vc = _get_voice_capture()
    try:
        vc.start()
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"capturing": True, "started_at": vc.status().get("started_at")}


@app.post("/voice/stop")
async def voice_stop():
    """
    Stop buffering, transcribe the captured audio with Whisper, POST the text
    to zero-api's intent router, then speak the response through Reachy.
    """
    vc = _get_voice_capture()
    if not vc.is_capturing:
        raise HTTPException(400, "No active voice capture")
    result = vc.stop_and_transcribe()
    text = result.get("text", "").strip()
    if not text:
        return {
            "captured": result.get("captured", False),
            "duration_seconds": result.get("duration_seconds", 0.0),
            "text": "",
            "intent": None,
            "response_text": None,
        }

    intent_url = f"{ZERO_API_URL}/api/reachy-intent/handle"
    intent_data = {}
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            resp = await c.post(intent_url, json={"text": text, "source": "reachy_ptt"})
            if resp.status_code < 400:
                intent_data = resp.json()
            else:
                logger.warning(
                    "voice_intent_forward_failed",
                    status=resp.status_code,
                    body=resp.text[:300],
                )
    except Exception as e:
        logger.warning("voice_intent_unreachable", error=str(e))

    reply = (intent_data.get("response_text") or "").strip()
    if reply:
        asyncio.create_task(_reachy_say_quiet(reply))

    return {
        "captured": True,
        "duration_seconds": result.get("duration_seconds", 0.0),
        "text": text,
        "intent": intent_data.get("intent"),
        "response_text": reply,
        "took_action": intent_data.get("took_action", False),
    }


class VoiceConfigRequest(BaseModel):
    whisper_model: str


@app.get("/voice/config")
async def voice_config_get():
    """Report which Whisper model the voice capture is currently using."""
    vc = _get_voice_capture()
    return {
        "whisper_model": vc.whisper_model_name,
        "whisper_device": vc._whisper_device,
        "whisper_compute_type": vc._whisper_compute_type,
        "capturing": vc.is_capturing,
    }


class LiveTranscriptModelRequest(BaseModel):
    model: str  # tiny | base | small | medium | large-v3


@app.get("/live-transcript/config")
async def live_transcript_config_get():
    live = get_live_transcription()
    return {
        "model": live.model_size,
        "window_s": live.window_s,
        "poll_interval_s": live.poll_interval_s,
        "loaded": live.is_loaded,
    }


@app.post("/live-transcript/config")
async def live_transcript_config_set(req: LiveTranscriptModelRequest):
    live = get_live_transcription()
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, live.set_model, req.model)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **result}


class VoiceEnrollRequest(BaseModel):
    display_name: str
    duration_seconds: float = 30.0
    is_primary: bool = True
    mic_device_index: Optional[int] = None


@app.post("/voice/enroll")
async def voice_enroll(request: VoiceEnrollRequest):
    """Record a short clip from the Reachy mic and ship it to zero-api's
    voiceprint-enrol endpoint. Does NOT touch the meeting capture pipeline."""
    if not request.display_name.strip():
        raise HTTPException(400, "display_name required")
    duration = max(3.0, min(60.0, float(request.duration_seconds)))

    # Pick mic: explicit override → preferred Reachy mic → default input.
    mic_index = request.mic_device_index
    if mic_index is None:
        mic_index = find_default_mic_index(os.getenv("ZERO_PREFERRED_MIC_DEVICE"))

    import sounddevice as sd
    import soundfile as sf
    import numpy as np

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() else "_" for c in request.display_name.strip())[:40]
    out_path = RECORDINGS_DIR / f"voiceprint_{safe_name}_{timestamp}.wav"

    try:
        loop = asyncio.get_event_loop()
        recording = await loop.run_in_executor(
            None,
            lambda: sd.rec(
                int(duration * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=mic_index,
            ),
        )
        await loop.run_in_executor(None, sd.wait)
        await loop.run_in_executor(
            None, lambda: sf.write(str(out_path), recording, SAMPLE_RATE, subtype="PCM_16")
        )
    except Exception as exc:
        logger.exception("voice_enroll_capture_failed")
        raise HTTPException(500, f"Capture failed: {exc}") from exc

    # Forward the WAV to zero-api as multipart.
    upload_url = f"{ZERO_API_URL}/api/voiceprints/enroll"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            with open(out_path, "rb") as f:
                files = {"audio": (out_path.name, f, "audio/wav")}
                data = {
                    "display_name": request.display_name.strip(),
                    "is_primary": "true" if request.is_primary else "false",
                }
                resp = await client.post(upload_url, files=files, data=data)
                resp.raise_for_status()
                return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text) from exc
    except Exception as exc:
        logger.exception("voice_enroll_forward_failed")
        raise HTTPException(502, f"zero-api enroll failed: {exc}") from exc


@app.post("/voice/config")
async def voice_config_set(request: VoiceConfigRequest):
    """
    Swap the Whisper model used for push-to-talk capture and pre-warm it.
    Safe to call while idle; returns 409 mid-capture.
    """
    vc = _get_voice_capture()
    if vc.is_capturing:
        raise HTTPException(409, "Voice capture in progress — stop it before swapping models")
    try:
        warm = await asyncio.get_event_loop().run_in_executor(
            None, vc.set_whisper_model, request.whisper_model,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **warm}


@app.get("/wake/status")
async def wake_status():
    status = {
        "mode": _wake_mode_actual,
        "available_modes": _available_wake_modes(),
        "running": False,
    }
    if _wake_loop is not None:
        status.update(_wake_loop.status())
        status["mode"] = _wake_mode_actual
    else:
        status.update(_wake_unavailable_status())
        status["available_modes"] = _available_wake_modes()
    return status


def _available_wake_modes() -> list[str]:
    modes = ["off"]
    if _can_use_openwakeword():
        modes.append("openwakeword")
    if PICOVOICE_ACCESS_KEY:
        modes.append("porcupine")
    modes.append("whisper")
    return modes


class WakeModeRequest(BaseModel):
    mode: str  # "openwakeword" | "whisper" | "porcupine" | "off" | "auto"


@app.post("/wake/mode")
async def wake_set_mode(request: WakeModeRequest):
    """Hot-swap the wake loop. No restart needed."""
    global _wake_loop, _wake_mode_actual
    requested = _resolve_wake_mode(request.mode)
    if requested not in ("off", "openwakeword", "whisper", "porcupine"):
        raise HTTPException(400, f"Unknown mode: {requested!r}")
    if requested == "porcupine" and not PICOVOICE_ACCESS_KEY:
        raise HTTPException(
            400,
            "Porcupine requires ZERO_PICOVOICE_ACCESS_KEY in .env — switch to 'whisper' instead.",
        )
    if requested == "openwakeword" and not _can_use_openwakeword():
        raise HTTPException(400, "openWakeWord resources are not available")

    if _wake_loop is not None:
        try:
            _wake_loop.stop()
        except Exception:
            pass
        _wake_loop = None

    if requested == "off":
        _wake_mode_actual = "off"
        return {"mode": "off", "running": False}

    mic_idx = await asyncio.to_thread(find_default_mic_index, PREFERRED_MIC)
    _wake_loop = _build_wake_loop(requested, mic_idx)
    await asyncio.to_thread(_wake_loop.start)
    _wake_mode_actual = requested
    return {"mode": _wake_mode_actual, **_wake_loop.status()}


@app.post("/wake/pause")
async def wake_pause():
    if _wake_loop is None:
        raise HTTPException(400, "Wake loop not configured")
    _wake_loop.pause()
    return {"paused": True}


@app.post("/wake/resume")
async def wake_resume():
    if _wake_loop is None:
        raise HTTPException(400, "Wake loop not configured")
    _wake_loop.resume()
    return {"paused": False}


def _host_mic_has_signal(rms: float, peak: float) -> bool:
    return rms >= HOST_MIC_MIN_RMS or peak >= HOST_MIC_MIN_PEAK


def _audio_frame_to_pcm16(audio_frame) -> tuple[bytes, float, float]:
    """Convert an SDK/sounddevice audio frame into mono PCM16 + normalized levels."""
    frame = np.asarray(audio_frame)
    if frame.size == 0:
        return b"", 0.0, 0.0
    if frame.ndim > 1:
        if frame.shape[1] > 1:
            as_float = frame.astype(np.float32, copy=False)
            energy = np.mean(as_float * as_float, axis=0)
            frame = frame[:, int(np.argmax(energy))]
        else:
            frame = frame[:, 0]
    if np.issubdtype(frame.dtype, np.floating):
        samples_float = np.clip(frame.astype(np.float32, copy=False), -1.0, 1.0)
        rms = float(np.sqrt(np.mean(samples_float * samples_float))) if samples_float.size else 0.0
        peak = float(np.max(np.abs(samples_float))) if samples_float.size else 0.0
        samples_i16 = np.clip(samples_float * 32767.0, -32768, 32767).astype("<i2")
    else:
        samples_i16 = frame.astype("<i2", copy=False)
        samples_float = samples_i16.astype(np.float32)
        rms = float(np.sqrt(np.mean(samples_float * samples_float)) / 32768.0) if samples_float.size else 0.0
        peak = float(np.max(np.abs(samples_float)) / 32768.0) if samples_float.size else 0.0
    return samples_i16.tobytes(), rms, peak


@app.websocket("/mic/stream")
async def mic_stream_ws(ws: WebSocket):
    """
    Persistent Reachy/host microphone source for live assistant sessions.

    The browser cannot see the Reachy USB microphone when Zero is opened from
    another device or when Windows routes that mic only to the host. This
    endpoint lets zero-api pull PCM16 frames from the host_agent and feed the
    same realtime websocket session that handles text, tools, and TTS.
    """
    global _wake_loop, _wake_mode_actual
    await ws.accept()
    stream = None
    sdk_robot = None
    sdk_recording = False
    resume_wake_mode = "off"
    wake_was_running = False
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
        if first.get("type") != "start":
            await ws.send_json({"type": "error", "message": "send {type:'start'} first"})
            return
        rate = int(first.get("rate") or SAMPLE_RATE)
        frame_ms = max(10, min(100, int(first.get("frame_ms") or 30)))
        frame_samples = max(160, int(rate * frame_ms / 1000))
        requested_device_index = first.get("device_index")
        if requested_device_index is None:
            candidate_indices: list[int | None] = list(preferred_mic_indices(PREFERRED_MIC))
            if PREFERRED_MIC is None:
                reachy_indices = {
                    int(d["index"])
                    for d in list_audio_devices().get("mic", [])
                    if d.get("is_reachy")
                }
                candidate_indices = [idx for idx in candidate_indices if idx in reachy_indices]
            if not candidate_indices:
                candidate_indices = [None]
        else:
            candidate_indices = [int(requested_device_index)]

        if first.get("pause_wake", True) and _wake_loop is not None:
            resume_wake_mode = _wake_mode_actual
            wake_was_running = True
            try:
                _wake_loop.stop()
            except Exception:
                pass
            _wake_loop = None
            _wake_mode_actual = "off"

        import sounddevice as sd
        try:
            import gstreamer_mic
        except Exception as e:
            gstreamer_mic = None  # type: ignore
            logger.info("gstreamer_mic_module_unavailable", error=str(e))
        loop = asyncio.get_running_loop()
        stream_open = True
        audio_queue: asyncio.Queue[tuple[bytes, bool, float, float]]
        first_frame: tuple[bytes, bool, float, float] | None = None
        device_index: int | None = None
        device_name: str | None = None
        device_host_api: str | None = None
        device_channels: int = 1
        tried_devices: list[dict] = []
        gst_capture: "gstreamer_mic.GStreamerMicCapture | None" = None

        def _device_info(idx: int | None) -> tuple[str | None, str | None, int]:
            if idx is None:
                return None, None, 1
            try:
                info = sd.query_devices(idx)
                host_api_name = None
                try:
                    host_apis = sd.query_hostapis()
                    host_api_idx = int(info.get("hostapi", 0))
                    if host_api_idx < len(host_apis):
                        host_api_name = host_apis[host_api_idx].get("name")
                except Exception:
                    pass
                max_input_channels = 1
                try:
                    max_input_channels = max(1, int(info.get("max_input_channels", 1)))
                except Exception:
                    pass
                return (
                    info.get("name") if isinstance(info, dict) else f"index={idx}",
                    host_api_name,
                    max_input_channels,
                )
            except Exception:
                return f"index={idx}", None, 1

        # First-pass: try GStreamer wasapi2src. This is the same path
        # Pollen's Reachy Mini Control desktop app uses; it requests the
        # multimedia role of the device and bypasses the Windows
        # comms-mode AEC chain that otherwise dead-mutes the Reachy
        # speakerphone signal in shared mode (rms_norm collapses to
        # ~0.005). Only attempt when:
        #   * the gstreamer_mic module imported cleanly
        #   * GStreamer is actually installed (find_gstreamer_bin() != None)
        #   * caller didn't pin a specific device_index (i.e. the auto
        #     "find Reachy" path — explicit device_index requests want a
        #     specific PortAudio enumeration, not GStreamer's view)
        if (
            gstreamer_mic is not None
            and gstreamer_mic.is_available()
            and requested_device_index is None
        ):
            gst_queue: asyncio.Queue[tuple[bytes, bool, float, float]] = asyncio.Queue(maxsize=50)

            def _gst_queue_audio(pcm: bytes, overflowed: bool, rms: float, peak: float, *, q=gst_queue) -> None:
                if not stream_open:
                    return
                try:
                    if q.full():
                        q.get_nowait()
                    q.put_nowait((pcm, overflowed, rms, peak))
                except Exception:
                    pass

            def _gst_threadsafe(pcm: bytes, overflowed: bool, rms: float, peak: float) -> None:
                # GStreamerMicCapture invokes from its reader thread;
                # marshal back to the asyncio loop just like the
                # sounddevice callback does.
                loop.call_soon_threadsafe(_gst_queue_audio, pcm, overflowed, rms, peak)

            try:
                gst_capture = gstreamer_mic.GStreamerMicCapture(
                    rate=rate,
                    channels=1,
                    frame_samples=frame_samples,
                    callback=_gst_threadsafe,
                )
                gst_capture.start()
                # Probe for actual audio so a misconfigured GStreamer
                # install doesn't silently take the slot.
                probe_frames: list[tuple[bytes, bool, float, float]] = []
                probe_deadline = time.monotonic() + max(0.5, HOST_MIC_PROBE_SECONDS)
                while time.monotonic() < probe_deadline:
                    try:
                        probe_frames.append(
                            await asyncio.wait_for(
                                gst_queue.get(),
                                timeout=max(0.05, probe_deadline - time.monotonic()),
                            )
                        )
                    except asyncio.TimeoutError:
                        break
                    if len(probe_frames) >= 8:
                        break
                if not probe_frames:
                    raise RuntimeError("gstreamer capture produced no frames during probe")
                first_frame = probe_frames[0]
                while probe_frames:
                    _gst_queue_audio(*probe_frames.pop(0))
                audio_queue = gst_queue
                device_name = gst_capture.device_name or "GStreamer wasapi2 (Reachy)"
                device_host_api = "gstreamer-wasapi2"
                device_channels = 1
                logger.info(
                    "host_mic_input_chosen_gstreamer",
                    device_name=device_name,
                    rate=rate,
                    frame_ms=frame_ms,
                )
            except Exception as gst_err:
                logger.warning(
                    "gstreamer_mic_failed_falling_back_to_sounddevice",
                    error=str(gst_err)[:240],
                )
                if gst_capture is not None:
                    try: gst_capture.stop()
                    except Exception: pass
                gst_capture = None

        for candidate_index in candidate_indices:
            if gst_capture is not None:
                # GStreamer already succeeded; skip the sounddevice loop.
                break
            candidate_queue: asyncio.Queue[tuple[bytes, bool, float, float]] = asyncio.Queue(maxsize=50)

            def _queue_audio(pcm: bytes, overflowed: bool, rms: float, peak: float, *, q=candidate_queue) -> None:
                if not stream_open:
                    return
                try:
                    if q.full():
                        q.get_nowait()
                    q.put_nowait((pcm, overflowed, rms, peak))
                except Exception:
                    pass

            def _mic_callback(indata, frames, time_info, status) -> None:
                try:
                    if getattr(indata, "ndim", 1) > 1 and indata.shape[1] > 1:
                        # Reachy Mini's XVF audio path is stereo. Mono capture
                        # can be nearly silent on some Windows drivers, and a
                        # fixed channel can miss the beamformed speech. Pick
                        # the channel carrying the strongest signal per frame.
                        frame = indata.astype(np.float32, copy=False)
                        energy = np.mean(frame * frame, axis=0)
                        chunk = indata[:, int(np.argmax(energy))]
                    else:
                        chunk = indata[:, 0] if getattr(indata, "ndim", 1) > 1 else indata
                    pcm = chunk.astype("<i2", copy=True).tobytes()
                    samples = chunk.astype(np.float32, copy=False)
                    rms = float(np.sqrt(np.mean(samples * samples))) / 32768.0 if samples.size else 0.0
                    peak = float(np.max(np.abs(samples))) / 32768.0 if samples.size else 0.0
                    overflowed = bool(getattr(status, "input_overflow", False))
                    loop.call_soon_threadsafe(_queue_audio, pcm, overflowed, rms, peak)
                except Exception:
                    pass

            name, host_api, max_input_channels = _device_info(candidate_index)
            capture_channels = 2 if max_input_channels >= 2 else 1
            # The Reachy "Echo Cancelling Speakerphone" registers as a Windows
            # COMMUNICATIONS device. Opened in WASAPI shared mode (sounddevice's
            # default), Windows runs an extra AEC/AGC/noise-suppression pass on
            # top of the XMOS chip's processing — which dead-mutes vowels and
            # the noise floor when no speaker reference signal is playing.
            # That produces speech at rms_norm ≈ 0.005 with peak ≈ 0.13: a
            # 26:1 peak-to-RMS that Whisper interprets as silence and rejects
            # by hallucinating YouTube outros ("Thanks for watching.", "Bye.")
            # against caption_hallucination + no_speech_prob filters.
            #
            # Pollen's reachy_mini SDK avoids this entirely by going through
            # GStreamer's wasapi2src element, which requests the multimedia
            # endpoint role and skips Windows comms-mode processing.
            #
            # We don't ship GStreamer here, so the next-best fix is WASAPI
            # exclusive mode — Windows hands us the device with no shared-mode
            # processing chain, and we get the chip's stream directly. If
            # exclusive mode is unavailable (driver doesn't support, device
            # already claimed by another exclusive client), fall back to
            # shared mode so the session still works at degraded quality.
            kwargs = dict(
                samplerate=rate,
                channels=capture_channels,
                dtype="int16",
                blocksize=frame_samples,
                callback=_mic_callback,
            )
            if candidate_index is not None:
                kwargs["device"] = int(candidate_index)
            wasapi_exclusive_attempted = False
            if (
                (host_api or "").lower().find("wasapi") >= 0
                and hasattr(sd, "WasapiSettings")
            ):
                try:
                    kwargs["extra_settings"] = sd.WasapiSettings(exclusive=True)
                    wasapi_exclusive_attempted = True
                except Exception:
                    kwargs.pop("extra_settings", None)
            test_stream = None
            try:
                try:
                    test_stream = sd.InputStream(**kwargs)
                    test_stream.start()
                except Exception as exclusive_err:
                    if not wasapi_exclusive_attempted:
                        raise
                    # Exclusive failed (device busy or driver refusal). Drop
                    # the WasapiSettings and retry shared mode so the session
                    # still works — quality will be degraded by Windows AEC
                    # but at least the user gets some transcription.
                    logger.warning(
                        "wasapi_exclusive_open_failed",
                        device=candidate_index,
                        device_name=name,
                        error=str(exclusive_err)[:200],
                    )
                    kwargs.pop("extra_settings", None)
                    if test_stream is not None:
                        try: test_stream.close()
                        except Exception: pass
                        test_stream = None
                    test_stream = sd.InputStream(**kwargs)
                    test_stream.start()
                probe_frames: list[tuple[bytes, bool, float, float]] = []
                probe_deadline = time.monotonic() + max(0.25, HOST_MIC_PROBE_SECONDS)
                while time.monotonic() < probe_deadline:
                    timeout_s = max(0.05, probe_deadline - time.monotonic())
                    try:
                        probe_frames.append(
                            await asyncio.wait_for(candidate_queue.get(), timeout=timeout_s)
                        )
                    except asyncio.TimeoutError:
                        break
                    if len(probe_frames) >= 8 and any(
                        _host_mic_has_signal(frame[2], frame[3]) for frame in probe_frames
                    ):
                        break
                if not probe_frames:
                    raise asyncio.TimeoutError()
                max_rms = max(frame[2] for frame in probe_frames)
                max_peak = max(frame[3] for frame in probe_frames)
                if (
                    HOST_MIC_REJECT_DIGITAL_SILENCE
                    and not _host_mic_has_signal(max_rms, max_peak)
                ):
                    tried_devices.append({
                        "device_index": candidate_index,
                        "device_name": name,
                        "host_api": host_api,
                        "channels": capture_channels,
                        "ok": False,
                        "error": "digital silence",
                        "rms": max_rms,
                        "peak": max_peak,
                    })
                    try:
                        test_stream.stop()
                        test_stream.close()
                    except Exception:
                        pass
                    test_stream = None
                    continue
                first_frame = probe_frames[0]
                for queued_frame in probe_frames[1:]:
                    try:
                        candidate_queue.put_nowait(queued_frame)
                    except Exception:
                        pass
                stream = test_stream
                audio_queue = candidate_queue
                device_index = candidate_index
                device_name = name
                device_host_api = host_api
                device_channels = capture_channels
                tried_devices.append({
                    "device_index": candidate_index,
                    "device_name": name,
                    "host_api": host_api,
                    "channels": capture_channels,
                    "ok": True,
                    "rms": max_rms,
                    "peak": max_peak,
                })
                break
            except asyncio.TimeoutError:
                tried_devices.append({
                    "device_index": candidate_index,
                    "device_name": name,
                    "host_api": host_api,
                    "channels": capture_channels,
                    "ok": False,
                    "error": "no audio frames received",
                })
            except Exception as e:
                tried_devices.append({
                    "device_index": candidate_index,
                    "device_name": name,
                    "host_api": host_api,
                    "channels": capture_channels,
                    "ok": False,
                    "error": str(e)[:200],
                })
            finally:
                if stream is None and test_stream is not None:
                    try:
                        test_stream.stop()
                        test_stream.close()
                    except Exception:
                        pass

        if stream is None or first_frame is None:
            if not HOST_MIC_SDK_FALLBACK:
                raise RuntimeError(f"No usable microphone stream. Tried: {tried_devices}")
            sdk_media_available = False
            try:
                async with httpx.AsyncClient(timeout=0.6) as client:
                    status_resp = await client.get(f"{REACHY_API_URL}/api/daemon/status")
                    status_data = status_resp.json() if status_resp.status_code < 400 else {}
                    sdk_media_available = not bool(status_data.get("no_media"))
            except Exception:
                sdk_media_available = False
            if not sdk_media_available:
                tried_devices.append({
                    "device_index": None,
                    "device_name": "Reachy SDK media recorder",
                    "host_api": "sdk_media",
                    "channels": 1,
                    "ok": False,
                    "error": "daemon media is disabled; SDK recorder unavailable",
                })
                raise RuntimeError(f"No usable microphone stream. Tried: {tried_devices}")
            try:
                from urllib.parse import urlparse

                from reachy_mini import ReachyMini

                parsed = urlparse(REACHY_API_URL)
                daemon_host = parsed.hostname or "localhost"
                daemon_port = int(parsed.port or 8000)
                sdk_robot = ReachyMini(
                    host=daemon_host,
                    port=daemon_port,
                    connection_mode="localhost_only",
                    spawn_daemon=False,
                    media_backend="default",
                )
                sdk_rate = int(sdk_robot.media.get_input_audio_samplerate() or SAMPLE_RATE)
                sdk_robot.media.start_recording()
                sdk_recording = True
                sdk_first: tuple[bytes, bool, float, float] | None = None
                sdk_deadline = time.monotonic() + max(0.5, HOST_MIC_SDK_FIRST_FRAME_TIMEOUT)
                while time.monotonic() < sdk_deadline:
                    audio_frame = sdk_robot.media.get_audio_sample()
                    if audio_frame is not None:
                        pcm, rms, peak = _audio_frame_to_pcm16(audio_frame)
                        if pcm:
                            sdk_first = (pcm, False, rms, peak)
                            break
                    await asyncio.sleep(0.01)
                if sdk_first is None:
                    raise RuntimeError(
                        "SDK media recorder produced no frames. "
                        "The daemon may still be running with --no-media."
                    )

                await ws.send_json({
                    "type": "ready",
                    "rate": sdk_rate,
                    "frame_ms": frame_ms,
                    "device_index": None,
                    "device_name": "Reachy SDK media recorder",
                    "device_host_api": "sdk_media",
                    "channels": 1,
                    "wake_paused": wake_was_running,
                    "tried_devices": tried_devices,
                    "fallback": "sdk_media",
                })

                pcm, overflowed, rms, peak = sdk_first
                await ws.send_json({
                    "type": "audio",
                    "audio_b64": base64.b64encode(pcm).decode("ascii"),
                    "rate": sdk_rate,
                    "overflowed": bool(overflowed),
                    "rms": rms,
                    "peak": peak,
                })

                while True:
                    audio_frame = sdk_robot.media.get_audio_sample()
                    if audio_frame is None:
                        await asyncio.sleep(0.005)
                        continue
                    pcm, rms, peak = _audio_frame_to_pcm16(audio_frame)
                    if not pcm:
                        await asyncio.sleep(0.005)
                        continue
                    try:
                        await ws.send_json({
                            "type": "audio",
                            "audio_b64": base64.b64encode(pcm).decode("ascii"),
                            "rate": sdk_rate,
                            "overflowed": False,
                            "rms": rms,
                            "peak": peak,
                        })
                    except WebSocketDisconnect:
                        break
                    await asyncio.sleep(0)
                return
            except Exception as e:
                tried_devices.append({
                    "device_index": None,
                    "device_name": "Reachy SDK media recorder",
                    "host_api": "sdk_media",
                    "channels": 1,
                    "ok": False,
                    "error": str(e)[:300],
                })
                raise RuntimeError(f"No usable microphone stream. Tried: {tried_devices}") from e

        await ws.send_json({
            "type": "ready",
            "rate": rate,
            "frame_ms": frame_ms,
            "device_index": device_index,
            "device_name": device_name,
            "device_host_api": device_host_api,
            "channels": device_channels,
            "wake_paused": wake_was_running,
            "tried_devices": tried_devices,
        })

        pcm, overflowed, rms, peak = first_frame
        await ws.send_json({
            "type": "audio",
            "audio_b64": base64.b64encode(pcm).decode("ascii"),
            "rate": rate,
            "overflowed": bool(overflowed),
            "rms": rms,
            "peak": peak,
        })

        while True:
            pcm, overflowed, rms, peak = await audio_queue.get()
            try:
                await ws.send_json({
                    "type": "audio",
                    "audio_b64": base64.b64encode(pcm).decode("ascii"),
                    "rate": rate,
                    "overflowed": bool(overflowed),
                    "rms": rms,
                    "peak": peak,
                })
            except WebSocketDisconnect:
                break
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception as e:
        logger.warning("mic_stream_ws_error", error=str(e))
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            stream_open = False
        except Exception:
            pass
        if gst_capture is not None:
            try:
                gst_capture.stop()
            except Exception:
                pass
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if sdk_robot is not None:
            if sdk_recording:
                try:
                    sdk_robot.media.stop_recording()
                except Exception:
                    pass
            try:
                sdk_robot.media_manager.close()
            except Exception:
                pass
            try:
                sdk_robot.client.disconnect()
            except Exception:
                pass
        if wake_was_running and resume_wake_mode != "off":
            try:
                mic_idx = find_default_mic_index(PREFERRED_MIC)
                _wake_loop = _build_wake_loop(resume_wake_mode, mic_idx)
                _wake_loop.start()
                _wake_mode_actual = resume_wake_mode
            except Exception as e:
                logger.warning("mic_stream_wake_resume_failed", mode=resume_wake_mode, error=str(e))
                _wake_loop = None
                _wake_mode_actual = "off"
        try:
            await ws.close()
        except Exception:
            pass


def _on_wake_command(text: str) -> None:
    """
    Wake-loop callback (runs on the wake thread — not the asyncio loop).
    Schedules the async intent dispatch on the main event loop.
    """
    if _main_loop is None:
        logger.warning("wake_command_no_loop", text=text)
        return
    asyncio.run_coroutine_threadsafe(_dispatch_wake_command(text), _main_loop)


async def _dispatch_wake_command(text: str) -> None:
    """
    Forward a wake-triggered command to zero-api's intent router, then speak
    the response through the Reachy speaker.
    """
    url = f"{ZERO_API_URL}/api/reachy-intent/handle"
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            resp = await c.post(url, json={"text": text, "source": "reachy_wake"})
            if resp.status_code >= 400:
                logger.warning(
                    "wake_intent_forward_failed",
                    status=resp.status_code,
                    body=resp.text[:300],
                    text=text,
                )
                await _reachy_say_quiet("Sorry, I couldn't process that.")
                return
            data = resp.json()
    except Exception as e:
        logger.warning("wake_intent_unreachable", error=str(e))
        await _reachy_say_quiet("I'm having trouble reaching the Zero API.")
        return

    reply = (data.get("response_text") or data.get("text") or "").strip()
    if reply:
        await _reachy_say_quiet(reply)


@app.get("/devices")
async def devices():
    return list_audio_devices()


@app.get("/record/status")
async def record_status():
    capture = _capture
    if capture is None:
        return {
            "is_recording": False,
            "duration_seconds": 0.0,
            "audio_levels": None,
            "mic_device_name": None,
            "meeting_id": None,
        }
    return {
        "is_recording": capture.is_recording,
        "duration_seconds": capture.duration_seconds,
        "audio_levels": capture.audio_levels if capture.is_recording else None,
        "mic_device_name": capture.mic_device_name,
        "meeting_id": _active_meeting_id,
    }


@app.post("/record/start")
async def record_start(request: StartRecordingRequest):
    global _active_meeting_id
    capture = _get_capture(
        mic_device_index=request.mic_device_index,
        system_device_index=request.system_device_index,
    )
    if capture.is_recording:
        raise HTTPException(409, "Already recording")

    pool = await _db()
    meeting_id = request.meeting_id or uuid_mod.uuid4().hex
    title = request.title or f"Recording {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    start_time = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        if request.meeting_id:
            existing = await conn.fetchrow(
                "SELECT id FROM meetings WHERE id = $1",
                request.meeting_id,
            )
            if not existing:
                raise HTTPException(404, f"Meeting {request.meeting_id} not found")
            await conn.execute(
                "UPDATE meetings SET status = 'recording' WHERE id = $1",
                request.meeting_id,
            )
        else:
            await conn.execute(
                "INSERT INTO meetings (id, title, start_time, status) VALUES ($1, $2, $3, 'recording')",
                meeting_id, title, start_time,
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{meeting_id}_{timestamp}.wav"
        output_path = RECORDINGS_DIR / filename
        recording_id = uuid_mod.uuid4().hex
        await conn.execute(
            """
            INSERT INTO meeting_recordings
              (id, meeting_id, file_path, format, sample_rate, channels, source)
            VALUES ($1, $2, $3, 'wav', $4, 1, $5)
            """,
            recording_id, meeting_id, str(output_path), SAMPLE_RATE, request.source,
        )

    capture.start(output_path, source=request.source)

    # Persist device name once capture has reported it.
    if capture.mic_device_name:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE meeting_recordings SET mic_device_name = $1 WHERE id = $2",
                capture.mic_device_name, recording_id,
            )

    _active_meeting_id = meeting_id

    # Spin up live Whisper on the audio ring buffer — subscribers on
    # /ws/meeting-live-transcript get segment events as they arrive.
    try:
        get_live_transcription().start(capture)
    except Exception as e:
        logger.warning("live_transcription_start_failed", error=str(e))

    if TTS_CONFIRMATIONS:
        asyncio.create_task(_reachy_say_quiet("Recording started"))

    return {
        "meeting_id": meeting_id,
        "recording_id": recording_id,
        "file_path": str(output_path),
        "mic_device_name": capture.mic_device_name,
    }


@app.post("/record/stop")
async def record_stop():
    global _active_meeting_id
    capture = _get_capture()
    if not capture.is_recording:
        raise HTTPException(400, "No active recording")

    # Stop live Whisper before audio tears down — avoids a race where the
    # worker reads from a half-released ring buffer.
    try:
        get_live_transcription().stop()
    except Exception as e:
        logger.debug("live_transcription_stop_failed", error=str(e))

    duration = capture.duration_seconds
    output_path = capture.stop()
    if output_path is None:
        raise HTTPException(500, "Stop returned no output path")

    file_size = output_path.stat().st_size if output_path.exists() else 0

    pool = await _db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, meeting_id FROM meeting_recordings WHERE file_path = $1",
            str(output_path),
        )
        if row:
            await conn.execute(
                "UPDATE meeting_recordings SET duration_seconds = $1, file_size_bytes = $2 WHERE id = $3",
                duration, file_size, row["id"],
            )
            await conn.execute(
                """
                UPDATE meetings
                   SET status = 'processing',
                       end_time = $1,
                       duration_seconds = $2
                 WHERE id = $3
                """,
                datetime.now(timezone.utc), int(duration), row["meeting_id"],
            )

    meeting_id = _active_meeting_id
    _active_meeting_id = None

    if TTS_CONFIRMATIONS:
        asyncio.create_task(_reachy_say_quiet("Meeting saved"))

    # Hand off to Zero's processing pipeline (transcribe -> summarize -> embed).
    if meeting_id:
        asyncio.create_task(_trigger_zero_pipeline(meeting_id))

    return {
        "meeting_id": meeting_id,
        "duration_seconds": duration,
        "file_path": str(output_path),
        "file_size_bytes": file_size,
    }


async def _trigger_zero_pipeline(meeting_id: str) -> None:
    """POST to zero-api to start the Whisper + summary pipeline. Fire-and-forget."""
    url = f"{ZERO_API_URL}/api/meeting-recordings/{meeting_id}/process"
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.post(url)
            if resp.status_code >= 400:
                logger.warning(
                    "host_agent_pipeline_trigger_failed",
                    meeting_id=meeting_id,
                    status=resp.status_code,
                    body=resp.text[:200],
                )
            else:
                logger.info("host_agent_pipeline_triggered", meeting_id=meeting_id)
    except Exception as e:
        logger.warning(
            "host_agent_pipeline_trigger_unreachable",
            meeting_id=meeting_id,
            error=str(e),
        )


@app.websocket("/record/live-transcript")
async def live_transcript_ws(ws: WebSocket):
    """
    Legacy VU-meter stub kept so older clients that still poll this path
    don't break. New clients should use /ws/meeting-live-transcript, which
    emits real Whisper segment messages.
    """
    await ws.accept()
    try:
        while True:
            capture = _capture
            if capture is not None and capture.is_recording:
                await ws.send_json({
                    "type": "status",
                    "is_recording": True,
                    "duration_seconds": capture.duration_seconds,
                    "audio_levels": capture.audio_levels,
                    "mic_device_name": capture.mic_device_name,
                })
            else:
                await ws.send_json({"type": "status", "is_recording": False})
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return


@app.websocket("/ws/meeting-recording")
async def meeting_recording_ws(ws: WebSocket):
    """
    Recording status stream shaped for the frontend's useMeetingRecordingWS.
    Emits {is_recording, meeting_id, duration_seconds, audio_levels,
    mic_device_name} every ~100ms while the capture is active. Idle frames
    are emitted at 1s so the frontend still sees heartbeats.
    """
    await ws.accept()
    try:
        while True:
            capture = _capture
            if capture is not None and capture.is_recording:
                await ws.send_json({
                    "is_recording": True,
                    "meeting_id": _active_meeting_id,
                    "duration_seconds": capture.duration_seconds,
                    "audio_levels": capture.audio_levels,
                    "mic_device_name": capture.mic_device_name,
                })
                await asyncio.sleep(0.1)
            else:
                await ws.send_json({
                    "is_recording": False,
                    "meeting_id": None,
                    "duration_seconds": 0.0,
                    "audio_levels": None,
                    "mic_device_name": None,
                })
                await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.warning("meeting_recording_ws_error", error=str(e))


@app.websocket("/ws/meeting-live-transcript")
async def meeting_live_transcript_ws(ws: WebSocket):
    """
    Real live-transcript stream. Subscribes to the LiveTranscriptionService
    and forwards each new segment to the client in the shape
    useMeetingLiveTranscriptWS expects: {type:"segment", id, start, end, text}.
    """
    await ws.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=64)

    def _on_segment(msg: dict) -> None:
        # Called from the LiveTranscriptionService worker thread.
        try:
            loop.call_soon_threadsafe(queue.put_nowait, msg)
        except Exception:
            pass

    live = get_live_transcription()
    live.subscribe(_on_segment)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=25.0)
                await ws.send_json(msg)
            except asyncio.TimeoutError:
                # Keep the connection warm so reverse proxies don't evict it.
                await ws.send_json({"type": "keepalive"})
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.warning("meeting_live_transcript_ws_error", error=str(e))
    finally:
        live.unsubscribe(_on_segment)


# ---------------------------------------------------------------------------
# Reachy speaker stream — raw PCM playback to the Reachy USB audio output.
# ---------------------------------------------------------------------------
# Used by zero-api during Interactive Mode so the assistant's voice comes out
# of the robot, not the user's PC. The Reachy daemon's media API only
# supports ``play_sound`` against pre-uploaded files, which is unusable for
# realtime audio (50ms PCM chunks). host_agent runs on the host and has
# direct USB access, so it owns this pipe.

_speaker_stream: Optional[SpeakerProcessSink] = None
_speaker_lock = asyncio.Lock()


def _speaker_matches(
    speaker: Optional[SpeakerProcessSink],
    *,
    rate: int,
    device_index: Optional[int],
) -> bool:
    if speaker is None:
        return False
    info = speaker.info()
    if not info.get("active"):
        return False
    if int(info.get("input_rate") or rate) != int(rate):
        return False
    return device_index is None or int(info.get("device_index") or -1) == int(device_index)


async def _get_or_start_speaker(rate: int = 24000, device_index: Optional[int] = None) -> SpeakerProcessSink:
    global _speaker_stream
    if _speaker_matches(_speaker_stream, rate=rate, device_index=device_index):
        return _speaker_stream
    s = SpeakerProcessSink(rate=rate, device_index=device_index)
    await _start_speaker_off_loop(s)
    _speaker_stream = s
    return s


async def _start_speaker_off_loop(speaker: SpeakerProcessSink, *, timeout_s: float = 10.0) -> dict:
    """Start the PortAudio speaker worker without blocking host_agent.

    Windows audio drivers can occasionally hang while opening the Reachy USB
    speaker. If that happens on the asyncio event loop, /health and /mic/stream
    stop responding and the whole assistant looks dead. Keep the driver work in
    a thread and fail the speaker path softly.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(speaker.start, timeout_s),
            timeout=timeout_s + 2.0,
        )
    except Exception:
        try:
            await asyncio.to_thread(speaker.stop)
        except Exception:
            pass
        raise


async def _stop_speaker_off_loop(speaker: SpeakerProcessSink, *, timeout_s: float = 3.0) -> None:
    try:
        await asyncio.wait_for(asyncio.to_thread(speaker.stop), timeout=timeout_s)
    except Exception:
        pass


async def _speaker_info_off_loop(speaker: SpeakerProcessSink, *, timeout_s: float = 1.0) -> dict:
    try:
        return await asyncio.wait_for(asyncio.to_thread(speaker.info), timeout=timeout_s)
    except Exception as e:
        return {
            "active": False,
            "transport": "subprocess",
            "last_error": f"speaker_status_timeout:{type(e).__name__}",
        }


async def _speaker_flush_off_loop(speaker: SpeakerProcessSink, *, timeout_s: float = 1.0) -> bool:
    await asyncio.wait_for(asyncio.to_thread(speaker.flush), timeout=timeout_s)
    return True


async def _speaker_write_off_loop(
    speaker: SpeakerProcessSink,
    pcm_bytes: bytes,
    *,
    timeout_s: float = 1.0,
) -> bool:
    await asyncio.wait_for(
        asyncio.to_thread(speaker.write_pcm16, pcm_bytes),
        timeout=timeout_s,
    )
    return True


@app.get("/speaker/devices")
async def speaker_list_devices():
    """Enumerate output devices visible to host_agent."""
    return {"devices": list_output_devices()}


@app.get("/speaker/status")
async def speaker_status():
    s = _speaker_stream
    if s is None:
        return {"active": False}
    return await _speaker_info_off_loop(s)


class SpeakerStartRequest(BaseModel):
    rate: int = 24000
    device_index: Optional[int] = None


@app.post("/speaker/start")
async def speaker_start(req: SpeakerStartRequest):
    global _speaker_stream
    async with _speaker_lock:
        if _speaker_matches(_speaker_stream, rate=req.rate, device_index=req.device_index):
            return _speaker_stream.info()
        if _speaker_stream is not None:
            await _stop_speaker_off_loop(_speaker_stream)
            _speaker_stream = None
        s = SpeakerProcessSink(rate=req.rate, device_index=req.device_index)
        try:
            await _start_speaker_off_loop(s)
        except Exception as e:
            try:
                logger.warning("speaker_start_failed", error_message=str(e), error_type=type(e).__name__, error_repr=repr(e))
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"speaker_start_failed: {type(e).__name__}: {repr(e)}")
        _speaker_stream = s
        return s.info()


@app.post("/speaker/stop")
async def speaker_stop():
    global _speaker_stream
    async with _speaker_lock:
        if _speaker_stream is not None:
            await _stop_speaker_off_loop(_speaker_stream)
            _speaker_stream = None
    return {"active": False}


@app.post("/speaker/flush")
async def speaker_flush():
    global _speaker_stream
    """Drop any queued PCM frames — for barge-in / interrupt."""
    s = _speaker_stream
    if s is not None:
        try:
            await _speaker_flush_off_loop(s)
        except Exception as e:
            if _speaker_stream is s:
                _speaker_stream = None
            asyncio.create_task(_stop_speaker_off_loop(s, timeout_s=1.0))
            return {
                "ok": False,
                "error": f"speaker_flush_timeout:{type(e).__name__}",
            }
    return {"ok": True}


@app.websocket("/speaker/stream")
async def speaker_stream_ws(ws: WebSocket):
    """
    Persistent PCM16 sink. The first JSON frame configures the stream:
        {"type": "start", "rate": 24000, "device_index": null}
    Subsequent frames are either binary (raw PCM16 mono LE) or JSON:
        {"type": "audio", "audio_b64": "<base64 PCM16>", "rate": 24000}
        {"type": "flush"}                 # drop queued frames (barge-in)
        {"type": "stop"}                  # end the stream
    """
    import base64
    global _speaker_stream
    await ws.accept()
    rate = 24000
    device_index: Optional[int] = None
    speaker: Optional[SpeakerProcessSink] = None
    speaker_start_failed = False

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            if "bytes" in msg and msg["bytes"] is not None:
                if speaker is None:
                    if speaker_start_failed:
                        continue
                    # Lazy-start with defaults if the client skipped the start
                    # handshake (still useful for quick smoke tests).
                    try:
                        async with _speaker_lock:
                            speaker = await _get_or_start_speaker(rate=rate, device_index=device_index)
                    except Exception as e:
                        speaker_start_failed = True
                        await ws.send_json({
                            "type": "error",
                            "message": f"speaker_start_failed: {type(e).__name__}: {repr(e)}",
                        })
                        continue
                    await ws.send_json({"type": "ready", **(await _speaker_info_off_loop(speaker))})
                try:
                    await _speaker_write_off_loop(speaker, msg["bytes"])
                except Exception as e:
                    speaker_start_failed = True
                    await ws.send_json({
                        "type": "error",
                        "message": f"speaker_write_timeout: {type(e).__name__}: {repr(e)}",
                    })
                continue
            text = msg.get("text")
            if text is None:
                continue
            try:
                import json
                evt = json.loads(text)
            except Exception:
                continue
            etype = evt.get("type")
            if etype == "start":
                rate = int(evt.get("rate") or rate)
                device_index = evt.get("device_index")
                async with _speaker_lock:
                    existing = _speaker_stream
                    existing_info = await _speaker_info_off_loop(existing) if existing is not None else {}
                    requested_matches_existing = (
                        bool(existing_info.get("active"))
                        and int(existing_info.get("input_rate") or rate) == int(rate)
                        and (
                            device_index is None
                            or int(existing_info.get("device_index") or -1) == int(device_index)
                        )
                    )
                    if requested_matches_existing:
                        speaker = existing
                        speaker_start_failed = False
                    else:
                        if _speaker_stream is not None:
                            await _stop_speaker_off_loop(_speaker_stream)
                            _speaker_stream = None
                        speaker = SpeakerProcessSink(rate=rate, device_index=device_index)
                        try:
                            await _start_speaker_off_loop(speaker)
                        except Exception as e:
                            speaker_start_failed = True
                            await ws.send_json({
                                "type": "error",
                                "message": f"speaker_start_failed: {type(e).__name__}: {repr(e)}",
                            })
                            speaker = None
                            continue
                        _speaker_stream = speaker
                        speaker_start_failed = False
                await ws.send_json({"type": "ready", **(await _speaker_info_off_loop(speaker))})
            elif etype == "audio":
                if speaker is None:
                    if speaker_start_failed:
                        continue
                    try:
                        async with _speaker_lock:
                            speaker = await _get_or_start_speaker(rate=rate, device_index=device_index)
                    except Exception as e:
                        speaker_start_failed = True
                        await ws.send_json({
                            "type": "error",
                            "message": f"speaker_start_failed: {type(e).__name__}: {repr(e)}",
                        })
                        continue
                    await ws.send_json({"type": "ready", **(await _speaker_info_off_loop(speaker))})
                b64 = evt.get("audio_b64") or ""
                if b64:
                    try:
                        await _speaker_write_off_loop(speaker, base64.b64decode(b64))
                    except Exception as e:
                        logger.debug("speaker_ws_decode_failed", error=str(e))
            elif etype == "flush":
                if speaker is not None:
                    try:
                        await _speaker_flush_off_loop(speaker)
                    except Exception as e:
                        await ws.send_json({
                            "type": "error",
                            "message": f"speaker_flush_timeout: {type(e).__name__}: {repr(e)}",
                        })
            elif etype == "stop":
                async with _speaker_lock:
                    if speaker is not None:
                        await _stop_speaker_off_loop(speaker)
                        if _speaker_stream is speaker:
                            _speaker_stream = None
                        speaker = None
                break
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.warning("speaker_ws_error", error=str(e))
    finally:
        async with _speaker_lock:
            if speaker is not None:
                await _stop_speaker_off_loop(speaker)
                if _speaker_stream is speaker:
                    _speaker_stream = None
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Reachy TTS (fire-and-forget)
# ---------------------------------------------------------------------------

async def _reachy_say_quiet(text: str) -> None:
    """Synth via edge-tts and play on the Reachy speaker. Never raises."""
    try:
        wav_bytes = await _tts_synthesize(text)
    except Exception as e:
        logger.debug("host_agent_tts_synth_failed", error=str(e))
        return

    filename = f"zero_tts_{uuid_mod.uuid4().hex[:12]}.wav"
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            up = await c.post(
                f"{REACHY_API_URL}/api/media/sounds/upload",
                files={"file": (filename, io.BytesIO(wav_bytes), "audio/wav")},
            )
            if up.status_code >= 400:
                return
            await c.post(
                f"{REACHY_API_URL}/api/media/play_sound",
                json={"file": filename},
            )

        # Best-effort cleanup after expected playback. The daemon returns 500
        # on delete occasionally; we swallow that.
        delay = max(2.0, min(30.0, 0.12 * len(text) + 1.0))
        await asyncio.sleep(delay)
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.delete(f"{REACHY_API_URL}/api/media/sounds/{filename}")
    except Exception as e:
        logger.debug("host_agent_reachy_say_failed", text=text, error=str(e))


async def _tts_synthesize(text: str) -> bytes:
    """Synthesize WAV audio via edge-tts. 24kHz mono PCM WAV."""
    import edge_tts
    voice = os.getenv("TTS_EDGE_VOICE", "en-US-AriaNeural")
    comm = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    mp3_bytes = buf.getvalue()
    if not mp3_bytes:
        raise RuntimeError("edge-tts returned empty audio")

    import soundfile as sf
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as t:
        t.write(mp3_bytes)
        tmp_path = t.name
    try:
        data, samplerate = sf.read(tmp_path)
        out = io.BytesIO()
        sf.write(out, data, samplerate, format="WAV")
        return out.getvalue()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Reachy daemon supervisor
# ---------------------------------------------------------------------------

class WatchdogRequest(BaseModel):
    enabled: bool


@app.get("/daemon/status")
async def daemon_status():
    return await asyncio.to_thread(get_supervisor().status)


@app.post("/daemon/start")
async def daemon_start():
    try:
        return await get_supervisor().start()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/daemon/stop")
async def daemon_stop():
    return await get_supervisor().stop()


@app.post("/daemon/restart")
async def daemon_restart():
    try:
        return await get_supervisor().restart(reason="manual")
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/daemon/logs")
async def daemon_logs(tail: int = 100):
    return get_supervisor().logs(tail=tail)


@app.get("/daemon/issues")
async def daemon_issues():
    return get_supervisor().known_issues()


@app.get("/daemon/diagnostics")
async def daemon_diagnostics():
    return await get_supervisor().diagnostics()


@app.post("/daemon/audio/reset")
async def daemon_audio_reset():
    return await get_supervisor().reset_audio()


@app.get("/daemon/watchdog")
async def daemon_watchdog_status():
    return get_supervisor().watchdog_info()


@app.post("/daemon/watchdog")
async def daemon_watchdog_set(request: WatchdogRequest):
    return await get_supervisor().set_watchdog(request.enabled)


# ---------------------------------------------------------------------------
# Docker readiness — exposed for the Smart Re-link UI
# ---------------------------------------------------------------------------

@app.get("/host/docker_status")
async def host_docker_status():
    readiness = get_docker_readiness()
    if readiness is None:
        return {
            "state": "unknown",
            "last_check": None,
            "last_ready": None,
            "last_error": "readiness_probe_not_initialized",
            "consecutive_failures": 0,
            "consecutive_ready": 0,
            "probe_count": 0,
            "next_probe_in_s": 0.0,
            "backend_url": ZERO_API_URL,
        }
    return readiness.get_status()


@app.post("/daemon/relink")
async def daemon_relink():
    """Smart Re-link: re-probe Docker, clear watchdog churn, restart if Docker is up.

    This is the single recovery primitive the UI calls when the user wants
    the system to "try again." Behaviour:
      * If Docker is not yet ready -> trigger an immediate readiness probe,
        clear sticky watchdog failure state, return ``action: "waiting"``.
      * If Docker is ready -> reset watchdog state and restart the daemon
        with reason ``relink``, return ``action: "restarted"``.
    """
    readiness = get_docker_readiness()
    if readiness is None:
        raise HTTPException(503, "Docker readiness probe is not initialized")
    docker_state = await readiness.probe_now()
    sup = get_supervisor()
    reset_result = await sup.reset_state(reason="relink")
    if docker_state.get("state") != "ready":
        return {
            "action": "waiting",
            "docker": docker_state,
            "watchdog": reset_result.get("watchdog"),
            "detail": (
                "Backend (Docker) is still warming up. host_agent will keep "
                "checking and link Reachy automatically once it is ready."
            ),
        }
    try:
        restart_result = await sup.restart(reason="relink")
    except Exception as e:
        raise HTTPException(500, f"daemon restart failed: {e}")
    return {
        "action": "restarted",
        "docker": docker_state,
        "daemon": restart_result,
        "watchdog": sup.watchdog_info(),
        "detail": "Backend is up; restarted the Reachy daemon.",
    }


# ---------------------------------------------------------------------------
# Camera — owns the USB cam on the Windows host. See camera_worker.py.
# ---------------------------------------------------------------------------

@app.get("/camera/status")
async def camera_status():
    return get_camera_worker().status()


@app.get("/camera/frame.jpg")
async def camera_frame():
    """Single JPEG snapshot of the latest frame. Starts the worker on demand."""
    jpeg = get_camera_worker().latest_jpeg(wait_s=3.0)
    if not jpeg:
        raise HTTPException(503, "No frame available (camera unavailable or starting)")
    return Response(content=jpeg, media_type="image/jpeg")


@app.get("/camera/mjpeg")
async def camera_mjpeg():
    """multipart/x-mixed-replace MJPEG stream for `<img src>` consumption."""
    worker = get_camera_worker()
    worker.ensure_started()
    return StreamingResponse(
        worker.mjpeg_chunks(),
        media_type=f"multipart/x-mixed-replace; boundary=zero-frame",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST_AGENT_HOST, port=HOST_AGENT_PORT)
