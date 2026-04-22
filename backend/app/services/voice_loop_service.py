"""
Voice loop service — orchestrates the full voice pipeline.

Pipeline: listen → transcribe (STT) → think (LLM) → speak (TTS)
Optionally drives Reachy Mini robot actions when connected.

Persona and gesture tags: the active persona's system prompt is prepended to
the user turn, and inline gesture markers in the LLM reply
(`[emotion:happy]`, `[dance:simple_nod]`, `[look:0.5,0,0.1]`) are stripped
from the spoken text and dispatched to the Reachy daemon in parallel with TTS
playback.
"""

import asyncio
from typing import Optional, Dict, Any
import structlog

from app.services.audio_service import get_audio_service
from app.services.tts_service import get_tts_service
from app.services.reachy_service import get_reachy_service
from app.services.reachy_personas import build_full_prompt, get_persona, PERSONAS
from app.services.reachy_emotion_parser import (
    GestureAction,
    action_to_motion_request,
    parse_and_strip,
)
from app.services.reachy_persona_state import get_reachy_persona_state
from app.services.reachy_presence_service import get_reachy_presence_service

logger = structlog.get_logger()


class VoiceLoopService:
    """Orchestrates listen → transcribe → think → speak pipeline."""

    _instance: Optional["VoiceLoopService"] = None

    # Default persona on fresh boot. Can be changed via set_persona().
    _DEFAULT_PERSONA = "cosmic_kitchen"

    def __init__(self):
        self._listening = False
        self._listen_task: Optional[asyncio.Task] = None
        self._active_persona_id: str = self._DEFAULT_PERSONA
        self._audio_service = get_audio_service()
        self._tts_service = get_tts_service()
        self._reachy_service = get_reachy_service()

    # --- Persona management ---

    def get_active_persona_id(self) -> str:
        return self._active_persona_id

    def set_persona(self, persona_id: str) -> bool:
        """Switch active persona. Returns True if the id is known."""
        if get_persona(persona_id) is None:
            return False
        self._active_persona_id = persona_id
        logger.info("voice_loop_persona_changed", persona=persona_id)
        return True

    @classmethod
    def get_instance(cls) -> "VoiceLoopService":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def process_voice_input(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        Full voice pipeline: transcribe → think → speak.

        Args:
            audio_bytes: Raw audio bytes (WAV/MP3/etc.)

        Returns:
            Dict with transcription, llm_response, and audio_response
        """
        result: Dict[str, Any] = {
            "transcription": None,
            "llm_response": None,
            "audio_response": None,
            "robot_connected": False,
        }

        # Step 1: Transcribe audio (STT)
        try:
            transcription = await self._audio_service.transcribe_upload(
                audio_bytes, "voice_input.wav"
            )
            result["transcription"] = {
                "text": transcription.text,
                "language": transcription.language,
                "duration": transcription.duration_seconds,
            }
            user_text = transcription.text
        except Exception as e:
            logger.error("voice_stt_failed", error=str(e))
            result["error"] = f"Transcription failed: {e}"
            return result

        if not user_text or not user_text.strip():
            result["error"] = "No speech detected"
            return result

        # Mark activity so the presence watcher does not trigger boredom gestures.
        try:
            get_reachy_presence_service().mark_voice_activity()
        except Exception:
            pass

        logger.info("voice_transcribed", text=user_text[:100])

        # Step 2: Get LLM response via orchestration graph
        try:
            response_text = await self._get_llm_response(user_text)
            result["llm_response"] = response_text
        except Exception as e:
            logger.error("voice_llm_failed", error=str(e))
            response_text = "I'm sorry, I had trouble processing that."
            result["llm_response"] = response_text
            result["llm_error"] = str(e)

        # Step 3: Synthesize response (TTS)
        try:
            audio_response = await self._tts_service.synthesize(response_text)
            result["audio_response_size"] = len(audio_response)
            result["audio_response"] = audio_response
        except Exception as e:
            logger.error("voice_tts_failed", error=str(e))
            result["tts_error"] = str(e)

        # Step 4: Strip gesture markers, dispatch to the robot, speak cleaned text
        clean_text, actions = parse_and_strip(response_text)
        result["llm_response"] = clean_text
        result["raw_llm_response"] = response_text
        result["gesture_actions"] = [
            {"kind": a.kind, "payload": a.payload, "offset": a.offset} for a in actions
        ]
        result["persona"] = self._active_persona_id

        try:
            robot_connected = await self._reachy_service.is_connected()
            result["robot_connected"] = robot_connected
            if robot_connected:
                # Fire gestures in parallel; don't block TTS on them.
                asyncio.create_task(self._dispatch_gestures(actions))
                await self._reachy_service.say(clean_text)
        except Exception as e:
            logger.debug("voice_robot_skipped", error=str(e))

        # Bump persona state; auto-rotate if the user configured a rotation.
        try:
            state = get_reachy_persona_state()
            n_emotions = sum(1 for a in actions if a.kind == "emotion")
            n_dances = sum(1 for a in actions if a.kind == "dance")
            suggested = state.record_interaction(
                self._active_persona_id, gestures=n_emotions, dances=n_dances
            )
            if suggested and suggested != self._active_persona_id:
                if self.set_persona(suggested):
                    result["persona_rotated_to"] = suggested
        except Exception as e:
            logger.debug("persona_state_update_failed", error=str(e))

        return result

    async def _dispatch_gestures(self, actions: list[GestureAction]) -> None:
        """Run each gesture marker sequentially so they layer cleanly."""
        for action in actions:
            req = action_to_motion_request(action)
            if not req:
                logger.debug("voice_gesture_malformed", payload=action.payload, kind=action.kind)
                continue
            try:
                kind = req["kind"]
                if kind == "look":
                    await self._reachy_service.look_at(
                        x=req["x"], y=req["y"], z=req["z"], duration=0.6
                    )
                elif kind == "dance":
                    await self._reachy_service.play_dance(req["name"])
                elif kind == "emotion":
                    await self._reachy_service.play_emotion(req["name"])
                elif kind == "motion":
                    await self._reachy_service.play_motion(req["name"])
            except Exception as e:
                logger.warning("voice_gesture_failed", kind=action.kind, payload=action.payload, error=str(e))

    async def _get_llm_response(self, text: str) -> str:
        """Route text through LLM orchestration and get response."""
        system_prompt = build_full_prompt(self._active_persona_id)

        # Append calendar / time / mode-aware situational hints so every turn
        # is grounded in the user's current reality. Cheap — local cache hit.
        try:
            from app.services.reachy_context_service import build_context_hint
            hint = await build_context_hint(self._active_persona_id)
            if hint and system_prompt:
                system_prompt = system_prompt + hint
        except Exception:
            pass

        # Preferred path: chat_service owns orchestration, memory, and tooling.
        try:
            from app.services.chat_service import get_chat_service
            chat_service = get_chat_service()
            try:
                # chat_service.chat may accept system_prompt via kwarg; fall back to
                # plain form if not supported so we stay compatible.
                response = await chat_service.chat(text, system_prompt=system_prompt)
            except TypeError:
                response = await chat_service.chat(text)
            if isinstance(response, dict):
                return response.get("response", response.get("text", str(response)))
            return str(response)
        except ImportError:
            logger.warning("chat_service_unavailable", fallback="direct_llm")

        # Fallback: use the unified LLM client directly, including the persona
        # prompt. The router itself is a resolver, not a chat caller — the
        # unified client wraps routing + provider dispatch + retries.
        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            client = get_unified_llm_client()
            response = await client.chat(
                prompt=text,
                system=system_prompt or None,
                task_type="voice_reply",
                temperature=0.6,
                max_tokens=400,
            )
            if isinstance(response, dict):
                return response.get("content") or response.get("response") or str(response)
            return str(response)
        except Exception as e:
            raise RuntimeError(f"No LLM backend available: {e}")

    async def start_listening(self):
        """Start continuous voice loop (listens for audio input)."""
        if self._listening:
            logger.info("voice_loop_already_running")
            return

        self._listening = True
        logger.info("voice_loop_started")

        # Note: Actual microphone capture requires platform-specific audio input
        # (e.g., sounddevice, PyAudio). This is a framework that processes
        # audio chunks as they arrive via the API.
        # For continuous listening, the frontend/client sends audio chunks
        # to POST /api/reachy/say or a WebSocket endpoint.

    async def stop_listening(self):
        """Stop continuous voice loop."""
        if not self._listening:
            return

        self._listening = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        self._listen_task = None
        logger.info("voice_loop_stopped")

    def get_status(self) -> dict:
        """Get voice loop status."""
        return {
            "listening": self._listening,
            "active_persona": self._active_persona_id,
            "known_personas": [p.id for p in PERSONAS],
            "tts": self._tts_service.get_status(),
        }


def get_voice_loop_service() -> VoiceLoopService:
    """Get singleton VoiceLoopService instance."""
    return VoiceLoopService.get_instance()
