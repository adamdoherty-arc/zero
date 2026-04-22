"""
Reachy Mini robot API endpoints.

Thin HTTP layer over app.services.reachy_service. The service talks to the
Pollen Robotics Reachy Mini desktop daemon's REST API.
"""

from fastapi import APIRouter, HTTPException, Response, UploadFile, File
from pydantic import BaseModel, Field
from typing import Literal, Optional
import structlog

from app.services.reachy_service import get_reachy_service, EMOTION_MOVES
from app.services.reachy_motion_library import (
    ALL_CLIPS,
    DANCE_CLIPS,
    EMOTION_CLIPS,
    categories,
    clip_to_dict,
    get_clip,
    resolve_motion,
)
from app.services.reachy_personas import (
    PERSONAS,
    get_persona,
    persona_to_dict,
)
from app.services.reachy_emotion_parser import parse_and_strip
from app.services.reachy_presence_service import get_reachy_presence_service
from app.services.voice_loop_service import get_voice_loop_service

router = APIRouter()
logger = structlog.get_logger()


# --- Request Models ---

class MoveRequest(BaseModel):
    roll: float = Field(0.0, description="Roll angle in degrees")
    pitch: float = Field(0.0, description="Pitch angle in degrees")
    yaw: float = Field(0.0, description="Yaw angle in degrees")
    duration: float = Field(1.0, description="Movement duration in seconds")


class LookAtRequest(BaseModel):
    x: float = Field(..., description="X coordinate in meters")
    y: float = Field(..., description="Y coordinate in meters")
    z: float = Field(..., description="Z coordinate in meters")
    duration: float = Field(1.0, description="Movement duration in seconds")


class AntennasRequest(BaseModel):
    left_angle: float = Field(0.0, description="Left antenna angle in degrees")
    right_angle: float = Field(0.0, description="Right antenna angle in degrees")
    duration: float = Field(0.5, description="Movement duration in seconds")


class EmotionRequest(BaseModel):
    emotion: str = Field(..., description="Emotion clip name or alias (e.g. 'happy', 'cheerful1', 'thank you')")


class DanceRequest(BaseModel):
    dance: str = Field(..., description="Dance clip name or alias (e.g. 'simple_nod', 'jackson_square', 'spin')")


class MotionPlayRequest(BaseModel):
    name: str = Field(..., description="Clip name, alias, or free-form LLM tag")
    kind: Optional[Literal["emotion", "dance"]] = Field(None, description="Constrain resolution to one library")


class SayRequest(BaseModel):
    text: str = Field(..., description="Text to speak", max_length=2000)


class PlaySoundRequest(BaseModel):
    file: str = Field(..., description="Filename previously uploaded to the daemon")


class VolumeRequest(BaseModel):
    volume: int = Field(..., ge=0, le=100)


class MotorModeRequest(BaseModel):
    mode: str = Field(..., description="MotorControlMode value, e.g. 'enabled' or 'disabled'")


# --- Status / State ---

@router.get("/status")
async def get_status():
    """Reachy Mini connection + daemon status."""
    service = get_reachy_service()
    connected = await service.is_connected()
    daemon = await service.get_daemon_status() if connected else {}
    info = service.get_status_info()
    return {
        "connected": connected,
        "daemon": daemon,
        **info,
    }


@router.get("/state")
async def get_state():
    """Full robot state (head pose, body yaw, antennas, DoA)."""
    return await get_reachy_service().get_full_state()


@router.get("/doa")
async def get_doa():
    """Direction of arrival (angle in radians, speech_detected bool)."""
    return await get_reachy_service().get_doa()


@router.get("/health-check")
async def health_check():
    return await get_reachy_service().health_check()


# --- Movement ---

@router.post("/move")
async def move_head(request: MoveRequest):
    return await get_reachy_service().move_head(
        roll=request.roll,
        pitch=request.pitch,
        yaw=request.yaw,
        duration=request.duration,
    )


@router.post("/look")
async def look_at(request: LookAtRequest):
    return await get_reachy_service().look_at(
        x=request.x, y=request.y, z=request.z, duration=request.duration,
    )


@router.post("/antennas")
async def set_antennas(request: AntennasRequest):
    return await get_reachy_service().set_antennas(
        left_angle=request.left_angle,
        right_angle=request.right_angle,
        duration=request.duration,
    )


@router.post("/emotion")
async def play_emotion(request: EmotionRequest):
    result = await get_reachy_service().play_emotion(request.emotion)
    if result.get("error", "").startswith("unknown emotion"):
        raise HTTPException(400, result)
    return result


@router.post("/dance")
async def play_dance(request: DanceRequest):
    result = await get_reachy_service().play_dance(request.dance)
    if result.get("error", "").startswith("unknown dance"):
        raise HTTPException(400, result)
    return result


# ---- Motion library (emotions + dances, with aliases + resolver) ----

@router.get("/motion/library")
async def motion_library(kind: Optional[Literal["emotion", "dance"]] = None):
    """
    List every clip the robot knows how to play. Returns the flat catalog, a
    kind-split, and a category-split for UI rendering.
    """
    if kind == "emotion":
        clips = EMOTION_CLIPS
    elif kind == "dance":
        clips = DANCE_CLIPS
    else:
        clips = ALL_CLIPS
    cats: dict[str, list[dict]] = {}
    for cat, items in categories().items():
        filtered = [clip_to_dict(c) for c in items if kind is None or c.kind == kind]
        if filtered:
            cats[cat] = filtered
    return {
        "total": len(clips),
        "emotions": len(EMOTION_CLIPS),
        "dances": len(DANCE_CLIPS),
        "clips": [clip_to_dict(c) for c in clips],
        "by_category": cats,
    }


@router.post("/motion/play")
async def motion_play(request: MotionPlayRequest):
    """Play any clip by name / alias / free-form tag. Kind is optional."""
    result = await get_reachy_service().play_motion(request.name, kind=request.kind)
    if result.get("error", "").startswith("unknown motion"):
        raise HTTPException(400, result)
    return result


@router.get("/motion/resolve")
async def motion_resolve(query: str, kind: Optional[Literal["emotion", "dance"]] = None):
    """
    Resolve a free-form tag to a concrete clip without playing it. Useful for
    letting the LLM inspect what it would trigger.
    """
    clip = resolve_motion(query, kind=kind)
    if not clip:
        raise HTTPException(404, {"error": f"no clip matches {query!r}", "kind": kind})
    return clip_to_dict(clip)


# ---- Personas (Wave 2) ----

class PersonaSelectRequest(BaseModel):
    persona_id: str = Field(..., description="One of the ids from GET /reachy/personas")


class GestureParseRequest(BaseModel):
    text: str = Field(..., description="Raw LLM reply containing [emotion:..] or [dance:..] markers")


@router.get("/personas")
async def list_personas(include_prompt: bool = False):
    """List every persona the voice loop can wear."""
    vs = get_voice_loop_service()
    return {
        "active_id": vs.get_active_persona_id(),
        "personas": [persona_to_dict(p, include_prompt=include_prompt) for p in PERSONAS],
    }


@router.get("/personas/{persona_id}")
async def get_persona_detail(persona_id: str):
    p = get_persona(persona_id)
    if not p:
        raise HTTPException(404, {"error": f"unknown persona: {persona_id}"})
    return persona_to_dict(p, include_prompt=True)


@router.post("/personas/select")
async def select_persona(request: PersonaSelectRequest):
    vs = get_voice_loop_service()
    if not vs.set_persona(request.persona_id):
        raise HTTPException(400, {"error": f"unknown persona: {request.persona_id}"})
    return {"active_id": vs.get_active_persona_id()}


@router.post("/gesture/parse")
async def gesture_parse(request: GestureParseRequest):
    """
    Dev endpoint: run a raw LLM reply through the gesture-marker stripper and
    return what the voice loop would say + which gestures it would fire.
    """
    clean, actions = parse_and_strip(request.text)
    return {
        "clean_text": clean,
        "actions": [{"kind": a.kind, "payload": a.payload, "offset": a.offset} for a in actions],
    }


# ---- Presence / pomodoro (Wave 5) ----

class PomodoroStartRequest(BaseModel):
    focus_minutes: int = Field(25, ge=5, le=90)
    break_minutes: int = Field(5, ge=1, le=30)


@router.get("/presence/pomodoro")
async def pomodoro_state():
    return get_reachy_presence_service().pomodoro_state()


@router.post("/presence/pomodoro/start")
async def pomodoro_start(request: PomodoroStartRequest):
    return await get_reachy_presence_service().pomodoro_start(
        focus_minutes=request.focus_minutes,
        break_minutes=request.break_minutes,
    )


@router.post("/presence/pomodoro/stop")
async def pomodoro_stop():
    return await get_reachy_presence_service().pomodoro_stop()


# ---- Meeting mode (Wave 4) ----

class MeetingModeRequest(BaseModel):
    meeting_id: Optional[str] = Field(None, description="Zero meeting id, if any")


@router.get("/presence/meeting")
async def meeting_state():
    return get_reachy_presence_service().meeting_state()


@router.post("/presence/meeting/start")
async def meeting_start(request: MeetingModeRequest):
    return await get_reachy_presence_service().start_meeting_mode(request.meeting_id)


@router.post("/presence/meeting/stop")
async def meeting_stop():
    return await get_reachy_presence_service().stop_meeting_mode()


@router.post("/wake-up")
async def wake_up():
    return await get_reachy_service().wake_up()


@router.post("/sleep")
async def goto_sleep():
    return await get_reachy_service().goto_sleep()


@router.post("/move/stop")
async def stop_move(uuid: Optional[str] = None):
    return await get_reachy_service().stop_move(uuid)


@router.get("/move/running")
async def is_moving():
    return await get_reachy_service().is_moving()


# --- Audio / speech ---

@router.post("/say")
async def say(request: SayRequest):
    """Synthesize text and play it through the Reachy speaker."""
    result = await get_reachy_service().say(request.text)
    if result.get("error"):
        raise HTTPException(503, result)
    return result


@router.post("/test-sound")
async def test_sound():
    """Play the daemon's built-in test chime."""
    return await get_reachy_service().test_sound()


@router.get("/sounds")
async def list_sounds():
    return await get_reachy_service().list_sounds()


@router.post("/sounds/upload")
async def upload_sound(file: UploadFile = File(...)):
    content = await file.read()
    return await get_reachy_service().upload_sound(file.filename or "upload.wav", content)


@router.delete("/sounds/{filename}")
async def delete_sound(filename: str):
    return await get_reachy_service().delete_sound(filename)


@router.post("/sounds/play")
async def play_sound(request: PlaySoundRequest):
    return await get_reachy_service().play_sound(request.file)


@router.post("/sounds/stop")
async def stop_sound():
    return await get_reachy_service().stop_sound()


# --- Volume ---

@router.get("/volume")
async def get_volume():
    return await get_reachy_service().get_volume()


@router.post("/volume")
async def set_volume(request: VolumeRequest):
    return await get_reachy_service().set_volume(request.volume)


@router.get("/volume/microphone")
async def get_mic_volume():
    return await get_reachy_service().get_mic_volume()


@router.post("/volume/microphone")
async def set_mic_volume(request: VolumeRequest):
    return await get_reachy_service().set_mic_volume(request.volume)


# --- Motors ---

@router.get("/motors")
async def get_motor_status():
    return await get_reachy_service().get_motor_status()


@router.post("/motors/mode")
async def set_motor_mode(request: MotorModeRequest):
    return await get_reachy_service().set_motor_mode(request.mode)


# --- Camera (specs only — frames live on WebRTC :8443) ---

@router.get("/camera/specs")
async def camera_specs():
    return await get_reachy_service().get_camera_specs()


@router.get("/camera/stream")
async def camera_stream(fmt: str = "webrtc"):
    """
    Return the URL where the Reachy Mini daemon serves its live camera feed.
    The frontend (or an installable Reachy app) can consume the stream
    directly; Zero does not proxy pixels.
    """
    url = get_reachy_service().get_stream_url(fmt=fmt)
    return {"url": url, "format": fmt}


# ---- Vision (Wave 3) ----

@router.get("/vision/backends")
async def vision_backends():
    """Report which vision backends are available on this deployment."""
    from app.services.reachy_vision_service import get_reachy_vision_service
    return get_reachy_vision_service().backend_status()


@router.post("/vision/detect")
async def vision_detect(
    kind: Literal["face", "hands"] = "face",
    image: UploadFile = File(...),
):
    """
    Detect faces or hands in a POSTed JPEG/PNG frame. Backend selects:
    - ``face`` uses OpenCV Haar cascades (ships with opencv-python).
    - ``hands`` uses MediaPipe Hands (requires ``pip install mediapipe``).

    Returns normalized [0, 1] bounding boxes so callers can scale to any
    target resolution without knowing the input size.
    """
    from app.services.reachy_vision_service import get_reachy_vision_service
    body = await image.read()
    result = get_reachy_vision_service().detect(body, kind=kind)
    if not result.get("available"):
        raise HTTPException(503, result)
    return result


@router.get("/camera")
async def capture_image():
    """
    Capture an image from the robot's camera.

    The daemon's REST API does not expose still-frame capture — camera frames
    are streamed over WebRTC on :8443 by the desktop app. This endpoint is
    preserved for backward compatibility and always returns 503.
    """
    raise HTTPException(
        status_code=503,
        detail="Camera capture is unavailable via REST. The Reachy Mini daemon exposes "
               "only /api/camera/specs; frames are delivered over WebRTC on :8443.",
    )


# --- TTS helper (pure synthesis, no robot) ---

@router.post("/tts")
async def synthesize_tts(request: SayRequest):
    """Synthesize text to WAV audio bytes (does not play on the robot)."""
    from app.services.tts_service import get_tts_service
    tts = get_tts_service()
    try:
        audio_bytes = await tts.synthesize(request.text)
        return Response(content=audio_bytes, media_type="audio/wav")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# --- Voice loop (STT -> LLM -> TTS) ---

@router.post("/voice")
async def process_voice(audio: UploadFile = File(...)):
    """
    Process voice input through the full STT -> persona-wrapped LLM -> gesture
    marker strip -> TTS pipeline.

    The response includes the TTS WAV inline as ``audio_response_b64`` so
    HTTP-only clients like the reachy_mini_zero bridge app can play it back
    without a second round trip.
    """
    import base64
    voice_service = get_voice_loop_service()
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No audio data provided")
    result = await voice_service.process_voice_input(audio_bytes)
    audio_response: bytes | None = result.pop("audio_response", None)
    return {
        **result,
        "has_audio_response": audio_response is not None,
        "audio_response_b64": (
            base64.b64encode(audio_response).decode("ascii") if audio_response else None
        ),
    }
