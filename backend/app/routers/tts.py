"""
Text-to-Speech API endpoints.

Provides TTS synthesis and engine status.
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
import structlog

from app.services.tts_service import get_tts_service

router = APIRouter()
logger = structlog.get_logger()


class SynthesizeRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize to speech")


@router.post("/synthesize")
async def synthesize(request: SynthesizeRequest):
    """Synthesize text to WAV/MP3 audio."""
    tts = get_tts_service()
    try:
        audio_bytes = await tts.synthesize(request.text)
        return Response(content=audio_bytes, media_type="audio/wav")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/status")
async def tts_status():
    """Get TTS engine status and configuration."""
    tts = get_tts_service()
    # Trigger lazy init to get accurate status
    await tts.initialize()
    return tts.get_status()
