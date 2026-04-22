"""
Reachy Mini Zero app.

Thin bridge that runs on the Reachy Mini itself (via the Reachy Mini Desktop
App store) and hands I/O back to Zero running on the user's desktop or
server:

  * captures 5 s audio chunks from the Reachy microphone
  * POSTs them to ``{ZERO_API_URL}/api/reachy/voice`` together with the
    gateway auth token
  * receives ``{transcription, llm_response, audio_response, gesture_actions}``
  * plays the synthesized audio out of the Reachy speaker
  * dispatches any returned gesture actions via the local ``ReachyMini`` SDK
    for lowest-latency response

All heavy lifting — LLM, persona, motion library lookup, TTS — happens on
Zero. Reachy is the I/O surface.

Configuration (environment variables read at start):

  ZERO_API_URL         default http://host.docker.internal:18792
  ZERO_GATEWAY_TOKEN   required; gateway auth header value
  ZERO_PUSH_TO_TALK    "1" to only record while the user presses a key;
                       default "0" (continuous 5 s windowed listening)

This app is a scaffold. On-device VAD and wake-word integration are left
open so downstream authors can plug in Whisper-base or porcupine.
"""

from __future__ import annotations

import io
import os
import threading
import time
import wave

import httpx
import numpy as np
from reachy_mini import ReachyMini, ReachyMiniApp


DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_CHUNK_SECONDS = 5.0


class ReachyMiniZero(ReachyMiniApp):
    """Proxy the Reachy mic + speaker + motors to the Zero backend."""

    custom_app_url: str | None = None

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        zero_url = os.environ.get("ZERO_API_URL", "http://host.docker.internal:18792").rstrip("/")
        token = os.environ.get("ZERO_GATEWAY_TOKEN")
        if not token:
            print("[reachy_mini_zero] ZERO_GATEWAY_TOKEN not set — aborting.")
            return

        chunk_seconds = float(os.environ.get("ZERO_CHUNK_SECONDS", DEFAULT_CHUNK_SECONDS))
        sample_rate = reachy_mini.media.get_output_audio_samplerate()

        headers = {
            "Authorization": f"Bearer {token}",
            "X-Zero-Client": "reachy_mini_zero/0.1.0",
        }
        client = httpx.Client(timeout=60.0, headers=headers)

        print(f"[reachy_mini_zero] ready — zero={zero_url} chunk={chunk_seconds:.1f}s")

        try:
            while not stop_event.is_set():
                audio_bytes = self._record_chunk(reachy_mini, sample_rate, chunk_seconds, stop_event)
                if audio_bytes is None or stop_event.is_set():
                    break
                try:
                    response = client.post(
                        f"{zero_url}/api/reachy/voice",
                        files={"audio": ("chunk.wav", audio_bytes, "audio/wav")},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as e:
                    print(f"[reachy_mini_zero] voice call failed: {e}")
                    time.sleep(2.0)
                    continue

                self._handle_response(reachy_mini, payload)
        finally:
            client.close()
            print("[reachy_mini_zero] stopped.")

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    def _record_chunk(
        self,
        reachy_mini: ReachyMini,
        sample_rate: int,
        chunk_seconds: float,
        stop_event: threading.Event,
    ) -> bytes | None:
        """
        Record `chunk_seconds` of audio from the Reachy mic.

        The Reachy SDK exposes microphone access via reachy_mini.media; we
        fall back to sounddevice when that API is not available so this
        scaffold runs even on early SDK builds.
        """
        try:
            samples = reachy_mini.media.record(seconds=chunk_seconds)  # type: ignore[attr-defined]
        except Exception:
            try:
                import sounddevice as sd  # type: ignore[import-not-found]
            except ImportError:
                print("[reachy_mini_zero] No mic API available (install sounddevice or upgrade reachy-mini).")
                return None
            samples = sd.rec(
                int(chunk_seconds * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocking=True,
            )
        if stop_event.is_set():
            return None

        # Normalize to int16 mono
        arr = np.asarray(samples)
        if arr.dtype != np.int16:
            # assume float32 in [-1, 1]
            arr = np.clip(arr, -1.0, 1.0)
            arr = (arr * 32767).astype(np.int16)
        if arr.ndim == 2:
            arr = arr[:, 0]

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(arr.tobytes())
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Dispatch — play TTS, fire gesture actions
    # ------------------------------------------------------------------

    def _handle_response(self, reachy_mini: ReachyMini, payload: dict) -> None:
        transcription = (payload.get("transcription") or {}).get("text")
        reply = payload.get("llm_response")
        if transcription:
            print(f"[reachy_mini_zero] heard: {transcription}")
        if reply:
            print(f"[reachy_mini_zero] reply:  {reply[:120]}")

        # Gestures are cheap and best-effort — fire-and-forget
        for action in payload.get("gesture_actions", []):
            try:
                self._fire_gesture(reachy_mini, action)
            except Exception as e:
                print(f"[reachy_mini_zero] gesture failed: {action} err={e}")

        # Audio response: Zero returns a base64 field in some deployments
        # and a separate /audio endpoint in others. We favour inline if
        # present, otherwise re-fetch. Fall back silently if absent.
        audio_b64 = payload.get("audio_response_b64")
        if not audio_b64:
            return
        try:
            import base64

            wav_bytes = base64.b64decode(audio_b64)
            reachy_mini.media.play_wav_bytes(wav_bytes)  # type: ignore[attr-defined]
        except Exception as e:
            print(f"[reachy_mini_zero] playback failed: {e}")

    def _fire_gesture(self, reachy_mini: ReachyMini, action: dict) -> None:
        kind = action.get("kind")
        payload = action.get("payload", "")
        # These helpers live on the local SDK so gestures are snappier than
        # round-tripping through /reachy/emotion/play over the LAN.
        if kind == "emotion":
            reachy_mini.play_emotion(payload)  # type: ignore[attr-defined]
        elif kind == "dance":
            reachy_mini.play_dance(payload)  # type: ignore[attr-defined]
        elif kind == "motion":
            reachy_mini.play_motion(payload)  # type: ignore[attr-defined]
        elif kind == "look":
            parts = [p.strip() for p in payload.split(",")]
            if len(parts) == 3:
                x, y, z = (float(p) for p in parts)
                reachy_mini.look_at(x=x, y=y, z=z, duration=0.6)  # type: ignore[attr-defined]
