"""
Reachy email voice triage endpoints.

Surface for the multi-turn email session driven by the wake-word loop and the
push-to-talk button. The session itself lives in
`app.services.email_voice_session_service`; these routes just expose it.

Routes
------
GET  /session                 Current session state, queue length, active email.
POST /voice-input             Send a WAV; transcribed and routed through the FSM.
POST /text-input              Send raw text (for debug / non-voice testing).
POST /skip                    Skip the current email without an action.
POST /reset                   Force the session back to idle. Drops any pending draft.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
import structlog

from app.services.email_voice_session_service import (
    get_email_voice_session_service,
)
from app.services.voice_intent_router import classify_intent

router = APIRouter()
logger = structlog.get_logger(__name__)


class TextInputRequest(BaseModel):
    text: str


@router.get("/session")
async def session_status() -> dict:
    """Return the current FSM state — useful for the frontend debug panel."""
    return get_email_voice_session_service().status()


@router.post("/voice-input")
async def voice_input(audio: UploadFile = File(...)) -> dict:
    """Transcribe a WAV upload and feed it into the active email session.

    Returns the transcribed text plus the FSM's next state. If the session is
    idle, the input is ignored (with a clear reason).
    """
    session = get_email_voice_session_service()
    if not session.is_active():
        return {
            "handled": False,
            "reason": "no active email session",
            "state": session.state(),
        }

    try:
        from app.services.audio_service import get_audio_service

        raw = await audio.read()
        if not raw:
            raise HTTPException(400, "empty audio upload")
        transcription = await get_audio_service().transcribe_upload(raw, audio.filename or "voice.wav")
        text = (transcription.text or "").strip()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("reachy_email_voice_stt_failed", error=str(e))
        raise HTTPException(500, f"transcription failed: {e}")

    if not text:
        return {"handled": False, "reason": "no speech detected", "state": session.state()}

    return await _drive(text)


@router.post("/text-input")
async def text_input(req: TextInputRequest) -> dict:
    """Drive the FSM from a raw text utterance (debug / testing path)."""
    session = get_email_voice_session_service()
    if not session.is_active():
        return {
            "handled": False,
            "reason": "no active email session",
            "state": session.state(),
        }
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "empty text")
    return await _drive(text)


@router.post("/skip")
async def skip_current() -> dict:
    """Skip the currently announced email without taking action."""
    session = get_email_voice_session_service()
    if not session.is_active():
        return {"handled": False, "reason": "no active email session"}
    result = await session.handle_user_intent("skip")
    return {**result, "state": session.state()}


@router.post("/reset")
async def reset_session() -> dict:
    """Force the session to idle. Drops any pending draft."""
    session = get_email_voice_session_service()
    await session.handle_user_intent("stop")
    return session.status()


async def _drive(text: str) -> dict:
    session = get_email_voice_session_service()

    # In composing_reply state, the user's text IS the reply substance — don't
    # try to classify it into an intent first (a long sentence would fail
    # classification and look like "unknown").
    if session.state() == "composing_reply":
        result = await session.submit_reply_text(text)
        return {**result, "state": session.state(), "transcription": text}

    intent = await classify_intent(text, allowed=session.allowed_intents())
    result = await session.handle_user_intent(intent.intent, raw_text=text)
    return {
        **result,
        "state": session.state(),
        "transcription": text,
        "intent": intent.intent,
        "intent_confidence": intent.confidence,
        "intent_source": intent.source,
    }
