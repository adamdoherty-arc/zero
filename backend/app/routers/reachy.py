"""
Reachy Mini robot API endpoints.

Provides head movement, emotion playback, TTS speech,
camera capture, and connection status.
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from typing import Optional
import structlog

from app.services.reachy_service import get_reachy_service
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


class EmotionRequest(BaseModel):
    emotion: str = Field(..., description="Emotion name: happy, sad, curious, surprised, angry, thinking")


class SayRequest(BaseModel):
    text: str = Field(..., description="Text to speak")


# --- Endpoints ---

@router.get("/status")
async def get_status():
    """Get Reachy Mini connection status."""
    service = get_reachy_service()
    connected = await service.is_connected()
    info = service.get_status_info()
    return {
        "connected": connected,
        **info,
    }


@router.post("/move")
async def move_head(request: MoveRequest):
    """Move the robot's head to specified orientation."""
    service = get_reachy_service()
    result = await service.move_head(
        roll=request.roll,
        pitch=request.pitch,
        yaw=request.yaw,
        duration=request.duration,
    )
    return result


@router.post("/look")
async def look_at(request: LookAtRequest):
    """Make the robot look at a point in 3D space."""
    service = get_reachy_service()
    result = await service.look_at(
        x=request.x,
        y=request.y,
        z=request.z,
        duration=request.duration,
    )
    return result


@router.post("/emotion")
async def play_emotion(request: EmotionRequest):
    """Play an emotion animation on the robot."""
    service = get_reachy_service()
    result = await service.play_emotion(request.emotion)
    return result


@router.post("/say")
async def say(request: SayRequest):
    """Speak text using TTS and robot speaker."""
    service = get_reachy_service()
    result = await service.say(request.text)
    return result


@router.get("/camera")
async def capture_image():
    """Capture an image from the robot's camera."""
    service = get_reachy_service()
    image_bytes = await service.capture_image()
    if not image_bytes:
        raise HTTPException(status_code=503, detail="Camera not available or robot not connected")
    return Response(content=image_bytes, media_type="image/jpeg")


@router.post("/tts")
async def synthesize_tts(request: SayRequest):
    """Synthesize text to audio (returns WAV/MP3 audio)."""
    from app.services.tts_service import get_tts_service
    tts = get_tts_service()
    try:
        audio_bytes = await tts.synthesize(request.text)
        return Response(content=audio_bytes, media_type="audio/wav")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/voice")
async def process_voice(audio: bytes = None):
    """Process voice input through full pipeline: STT → LLM → TTS."""
    from fastapi import UploadFile, File

    voice_service = get_voice_loop_service()
    # This endpoint expects raw audio bytes in the request body
    # For file uploads, use the /api/audio/transcribe endpoint
    if not audio:
        raise HTTPException(status_code=400, detail="No audio data provided")

    result = await voice_service.process_voice_input(audio)

    # If audio response is present, return it separately
    audio_response = result.pop("audio_response", None)
    return {
        **result,
        "has_audio_response": audio_response is not None,
    }
