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
import re
import time
from typing import Optional, Dict, Any
import structlog


# Per-stage timeouts (seconds). Keep these well inside the frontend's outer
# AbortController timeout (50 s) so the backend fails cleanly before the
# browser aborts. STT sits at 25 s to absorb first-turn cold starts when the
# user picks a larger Whisper size; pre-warm on startup keeps normal turns
# well under that.
_STT_TIMEOUT = 25.0
_LLM_TIMEOUT = 20.0
_TTS_TIMEOUT = 10.0

# Canned fallback lines so the user *hears* the failure mode instead of
# staring at a spinner.
_FALLBACK_STT = "I had trouble hearing that. Could you try again?"
_FALLBACK_LLM = "I'm having trouble thinking right now. Try me again in a moment?"
_FALLBACK_TTS = None  # no audio possible when TTS itself fails


_VISION_QUESTION_PATTERNS = [
    re.compile(r"\bwhat\s+(do|can)\s+you\s+see\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+am\s+i\s+(looking at|holding|wearing)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+is\s+this\b", re.IGNORECASE),
    re.compile(r"\bread\s+(this|the)\b.*\b(note|sign|label|receipt|sticker|paper|screen|recipe|whiteboard)\b", re.IGNORECASE),
    re.compile(r"\bdescribe\s+(this|the)\s+(room|scene|view|image|picture)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+many\s+.*\b(see|visible|on|in|around)\b", re.IGNORECASE),
]


def _is_vision_question(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _VISION_QUESTION_PATTERNS)

from app.services.audio_service import get_audio_service
from app.services.tts_service import get_tts_service
from app.services.reachy_service import get_reachy_service
from app.services.reachy_personas import build_full_prompt, get_persona, PERSONAS
from app.services.reachy_voice_config_service import get_reachy_voice_config
from app.services.reachy_emotion_parser import (
    GestureAction,
    action_to_motion_request,
    parse_and_strip,
)
from app.services.reachy_persona_state import get_reachy_persona_state
from app.services.reachy_presence_service import get_reachy_presence_service

logger = structlog.get_logger()


async def _vault_lines_for_turn(user_text: str) -> Optional[str]:
    """Return a compact "related notes" block from the Obsidian vault, or
    None when nothing relevant is found / the vault is offline.

    Cap: top-3 chunks, ~200 chars each, ~600 chars total — fits cleanly in
    the working_context budget without crowding the persona / human blocks.
    """
    if not user_text or len(user_text.strip()) < 4:
        return None
    try:
        from app.services.vault_retrieval_service import VaultRetrievalService
    except Exception:
        return None
    try:
        svc = VaultRetrievalService()
        # No partition filter — voice context should pull from anywhere the
        # user has written (the actual partition mix in this vault is
        # personal / inbox / zero-dev / reference, not the spec defaults).
        result = await asyncio.wait_for(
            svc.search(user_text, top_k=3, per_side_k=20),
            timeout=2.5,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug("vault_search_skipped", error=str(e))
        return None

    hits = (result or {}).get("hits") or []
    if not hits:
        return None

    lines: list[str] = []
    for c in hits[:3]:
        path = c.get("path") or "?"
        body = (c.get("content") or "").strip().replace("\n", " ")
        if len(body) > 200:
            body = body[:200].rstrip() + "…"
        lines.append(f"- ({path}) {body}")
    return "\n".join(lines)


class VoiceLoopService:
    """Orchestrates listen → transcribe → think → speak pipeline."""

    _instance: Optional["VoiceLoopService"] = None

    # Default persona on fresh boot. Can be changed via set_persona().
    _DEFAULT_PERSONA = "companion"

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

    async def _safe_synthesize(self, text: str, phase_log: list) -> Optional[bytes]:
        """TTS with timeout; returns bytes or None. Appends to phase_log with engine+voice metadata.

        Uses the active persona's voice as ``voice_override`` so picking
        Sally on the Voice Settings page actually plays Jenny instead of
        the global TTS default. Falls back to the default when the persona
        has no voice bound.
        """
        t0 = time.monotonic()
        try:
            persona_voice: Optional[str] = None
            try:
                # Filesystem voice.txt wins (it's user-editable from the
                # Voice Settings page), then PERSONAS table voice as fallback.
                from pathlib import Path as _Path
                vfile = (
                    _Path(__file__).resolve().parents[1]
                    / "data" / "reachy_profiles" / self._active_persona_id / "voice.txt"
                )
                if vfile.exists():
                    persona_voice = vfile.read_text(encoding="utf-8").strip() or None
                if not persona_voice:
                    p = get_persona(self._active_persona_id)
                    persona_voice = p.voice if p else None
            except Exception:
                persona_voice = None
            audio, meta = await asyncio.wait_for(
                self._tts_service.synthesize_with_meta(
                    text, voice_override=persona_voice
                ),
                timeout=_TTS_TIMEOUT,
            )
            phase_log.append({
                "phase": "tts",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": True,
                "provider": meta.get("engine"),
                "model": meta.get("voice"),
            })
            return audio
        except asyncio.TimeoutError:
            logger.error("voice_tts_timeout", seconds=_TTS_TIMEOUT)
            phase_log.append({
                "phase": "tts",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": False,
                "error": "timeout",
                "provider": self._tts_service.get_status().get("engine"),
                "model": self._tts_service.get_status().get("model"),
            })
            return None
        except Exception as e:
            logger.error("voice_tts_failed", error=str(e))
            phase_log.append({
                "phase": "tts",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": False,
                "error": str(e)[:200],
                "provider": self._tts_service.get_status().get("engine"),
                "model": self._tts_service.get_status().get("model"),
            })
            return None

    async def process_voice_input(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        Full voice pipeline: transcribe → think → speak.

        Each stage has its own timeout and records timing + success to
        ``phase_log``. On timeout at any stage, we fall back to a canned line
        so the user hears *what* failed instead of a silent spinner.
        """
        phase_log: list = []
        voice_cfg = get_reachy_voice_config()
        stt_model = voice_cfg.get_stt_model()
        tts_voice = voice_cfg.get_tts_voice()

        # Resolve the LLM that will run for this turn. `resolve_provider_model`
        # is cheap (in-memory lookup) and lets us surface the intended model in
        # the response envelope before the LLM phase even starts.
        try:
            from app.infrastructure.llm_router import get_llm_router
            llm_provider, llm_model, _fbs = get_llm_router().resolve_provider_model("voice_reply")
        except Exception:
            llm_provider, llm_model = None, None

        active_models = {
            "stt": {"provider": "faster-whisper", "model": stt_model},
            "llm": {"provider": llm_provider, "model": llm_model},
            "tts": {"provider": self._tts_service.get_status().get("engine"), "model": tts_voice},
        }
        result: Dict[str, Any] = {
            "transcription": None,
            "llm_response": None,
            "audio_response": None,
            "robot_connected": False,
            "phase_log": phase_log,
            "active_models": active_models,
        }

        # Step 1: Transcribe audio (STT)
        t0 = time.monotonic()
        try:
            transcription = await asyncio.wait_for(
                self._audio_service.transcribe_upload(audio_bytes, "voice_input.wav", model=stt_model),
                timeout=_STT_TIMEOUT,
            )
            phase_log.append({
                "phase": "stt",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": True,
                "provider": "faster-whisper",
                "model": transcription.model_used or stt_model,
            })
            result["transcription"] = {
                "text": transcription.text,
                "language": transcription.language,
                "duration": transcription.duration_seconds,
            }
            user_text = transcription.text
        except asyncio.TimeoutError:
            logger.error("voice_stt_timeout", seconds=_STT_TIMEOUT, model=stt_model)
            phase_log.append({
                "phase": "stt",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": False,
                "error": "timeout",
                "provider": "faster-whisper",
                "model": stt_model,
            })
            result["error"] = {"stage": "stt", "message": "Speech recognition timed out"}
            result["llm_response"] = _FALLBACK_STT
            result["audio_response"] = await self._safe_synthesize(_FALLBACK_STT, phase_log)
            return result
        except Exception as e:
            logger.error("voice_stt_failed", error=str(e))
            phase_log.append({
                "phase": "stt",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": False,
                "error": str(e)[:200],
                "provider": "faster-whisper",
                "model": stt_model,
            })
            result["error"] = {"stage": "stt", "message": f"Transcription failed: {e}"}
            result["llm_response"] = _FALLBACK_STT
            result["audio_response"] = await self._safe_synthesize(_FALLBACK_STT, phase_log)
            return result

        if not user_text or not user_text.strip():
            result["error"] = {"stage": "stt", "message": "No speech detected"}
            return result

        # Mark activity so the presence watcher does not trigger boredom gestures.
        try:
            get_reachy_presence_service().mark_voice_activity()
        except Exception:
            pass

        logger.info("voice_transcribed", text=user_text[:100])

        # Step 1.5: If an email triage session is active, route the user's
        # speech through the FSM instead of the chat LLM. The session itself
        # speaks via reachy.say internally, so we short-circuit and return
        # without going through the full chat path.
        try:
            from app.services.email_voice_session_service import (
                get_email_voice_session_service,
            )
            email_session = get_email_voice_session_service()
            if email_session.is_active():
                if email_session.state() == "composing_reply":
                    handled = await email_session.submit_reply_text(user_text)
                else:
                    from app.services.voice_intent_router import classify_intent
                    intent = await classify_intent(
                        user_text, allowed=email_session.allowed_intents()
                    )
                    handled = await email_session.handle_user_intent(
                        intent.intent, raw_text=user_text
                    )
                    handled["intent"] = intent.intent
                    handled["intent_confidence"] = intent.confidence
                result["email_session"] = handled
                result["email_session_state"] = email_session.state()
                # Mark voice activity so presence watcher doesn't kick in mid-triage.
                try:
                    get_reachy_presence_service().mark_voice_activity()
                except Exception:
                    pass
                return result
        except Exception as e:
            logger.debug("voice_email_session_skipped", error=str(e))

        # Step 1.6: "What do you see?" style intercept — route grounded
        # vision questions directly to the VLM instead of hallucinating.
        if _is_vision_question(user_text):
            try:
                from app.services.reachy_vision_service import get_reachy_vision_service
                scene = await get_reachy_vision_service().analyze_scene(question=user_text)
                vlm_answer = (scene.get("answer") or scene.get("caption") or "").strip()
                if vlm_answer:
                    result["vision_intercept"] = {
                        "provider": scene.get("provider"),
                        "caption": scene.get("caption"),
                        "actionable": scene.get("actionable"),
                    }
                    # Prefix with a subtle observe beat so Reachy reacts.
                    response_text = "[observe] " + vlm_answer
                    # Fall through to gesture parsing + TTS below.
                    result["llm_response"] = response_text
                    clean, actions = parse_and_strip(response_text)
                    asyncio.create_task(self._dispatch_gestures(actions))
                    result["audio_response"] = await self._safe_synthesize(clean, phase_log)
                    return result
            except Exception as e:
                logger.debug("vision_intercept_skipped", error=str(e))

        # Step 2: Get LLM response via orchestration graph (with timeout)
        t0 = time.monotonic()
        try:
            response_text = await asyncio.wait_for(
                self._get_llm_response(user_text), timeout=_LLM_TIMEOUT
            )
            phase_log.append({
                "phase": "llm",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": True,
                "provider": llm_provider,
                "model": llm_model,
            })
            result["llm_response"] = response_text
        except asyncio.TimeoutError:
            logger.error("voice_llm_timeout", seconds=_LLM_TIMEOUT)
            phase_log.append({
                "phase": "llm",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": False,
                "error": "timeout",
                "provider": llm_provider,
                "model": llm_model,
            })
            response_text = _FALLBACK_LLM
            result["llm_response"] = response_text
            result["error"] = {"stage": "llm", "message": "LLM timed out"}
        except Exception as e:
            logger.error("voice_llm_failed", error=str(e))
            phase_log.append({
                "phase": "llm",
                "ms": int((time.monotonic() - t0) * 1000),
                "ok": False,
                "error": str(e)[:200],
                "provider": llm_provider,
                "model": llm_model,
            })
            response_text = _FALLBACK_LLM
            result["llm_response"] = response_text
            result["llm_error"] = str(e)

        # Step 3: Synthesize response (TTS) — timed via helper
        audio_response = await self._safe_synthesize(response_text, phase_log)
        if audio_response is not None:
            result["audio_response_size"] = len(audio_response)
            result["audio_response"] = audio_response

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
            result["played_on_robot"] = False
            if robot_connected:
                # Fire gestures in parallel; don't block TTS on them.
                asyncio.create_task(self._dispatch_gestures(actions))
                # If the LLM didn't emit any gesture markers, play a subtle
                # baseline sway so Reachy still looks alive while speaking.
                # Keeps the robot from reading as a static speaker.
                if not actions:
                    asyncio.create_task(
                        self._reachy_service.play_emotion("attentive1")
                    )
                # Reuse the audio bytes we already synthesized instead of
                # re-synthesizing via say(). Halves TTS cost and guarantees
                # the same voice plays out of Reachy as went into audio_b64.
                if audio_response:
                    play_res = await self._reachy_service.play_audio_bytes(
                        audio_response, label="voice_turn"
                    )
                    if not play_res.get("error"):
                        result["played_on_robot"] = True
                else:
                    # Fallback: no bytes (TTS timed out) — try say() which
                    # will re-synthesize with the fallback line.
                    await self._reachy_service.say(clean_text)
                    result["played_on_robot"] = True
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

        # Log the turn to cross-session memory and kick off note extraction.
        # Both are best-effort; we never want them to break a voice turn.
        try:
            from app.services.reachy_user_memory_service import (
                get_reachy_user_memory_service,
            )
            mem = get_reachy_user_memory_service()
            gestures_fired = [f"{a.kind}:{a.payload}" for a in actions]
            await mem.log_turn(
                persona_id=self._active_persona_id,
                user_text=user_text,
                reachy_text=clean_text,
                gestures=gestures_fired,
            )
            await mem.maybe_extract()
        except Exception as e:
            logger.debug("memory_log_skipped", error=str(e))

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
        """Route text through LLM orchestration and get response.

        System prompt is assembled by ``compose_system_prompt`` which stitches
        together: core identity, active persona, human block, relationship
        block, the per-turn working context (calendar / sight / fresh notes /
        vault hits), gesture instructions, and the voice-length suffix.
        """
        from app.services.reachy_memory_blocks import compose_system_prompt

        # ----- Build working context (per-turn, ephemeral) ------------------
        wc_parts: list[str] = []

        # Calendar / time / mode-aware situational hints. Cheap — local cache.
        try:
            from app.services.reachy_context_service import build_context_hint
            hint = await build_context_hint(self._active_persona_id)
            if hint:
                # build_context_hint returns "\n\n### CURRENT CONTEXT\n..." —
                # strip the duplicate header since compose adds its own.
                wc_parts.append(
                    hint.replace("### CURRENT CONTEXT\n", "").strip()
                )
        except Exception:
            pass

        # Fresh notes from user_memory (learned within the last 24h, before
        # the nightly synthesis job folds them into the human block).
        try:
            from app.services.reachy_user_memory_service import (
                get_reachy_user_memory_service,
            )
            mem = get_reachy_user_memory_service()
            relevant = await mem.relevant_notes_async(text, k=5)
            if relevant:
                wc_parts.append(
                    "Recent learned notes:\n"
                    + "\n".join(f"- ({n.category}) {n.text}" for n in relevant)
                )
        except Exception as e:
            logger.debug("memory_inject_skipped", error=str(e))

        # Phase-3 hook: vault retrieval. Plugged in by Phase 3 — kept here
        # so the call site never moves and unit tests can patch it cleanly.
        try:
            vault_lines = await _vault_lines_for_turn(text)
            if vault_lines:
                wc_parts.append("Related notes from your vault:\n" + vault_lines)
        except Exception as e:
            logger.debug("vault_inject_skipped", error=str(e))

        working_context = "\n\n".join(p for p in wc_parts if p)

        system_prompt = compose_system_prompt(
            self._active_persona_id,
            working_context=working_context,
            include_voice_suffix=True,
        )

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
