"""
Reachy Mini streaming bridge to Zero's realtime WebSocket.

Replaces the legacy 5 s chunked POST loop in ``main.py`` with a continuous
WebSocket stream against ``/api/reachy/realtime/ws``. This is the path that
makes conversation through the physical robot feel as alive as the browser
realtime surface — no more turn-bashed lag, partial transcripts arrive while
the user is still talking, and TTS plays back as it's synthesised.

Usage on the Reachy Mini:

    from reachy_mini_zero.streaming import ReachyMiniZeroStreaming
    app = ReachyMiniZeroStreaming()
    app.run(reachy_mini, stop_event)

Environment:

    ZERO_API_URL          default http://host.docker.internal:18792
    ZERO_GATEWAY_TOKEN    required; bearer token for the WS handshake
    ZERO_REALTIME_PROFILE optional persona profile id (default: "default")

This is intentionally minimal — heavy lifting (VAD, STT, LLM, TTS) lives on
Zero. Reachy is the I/O surface: audio in, audio out, motors driven by
gesture frames returned by the server.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import threading
import time
import wave
from typing import Any, Optional

import numpy as np

try:  # Make the file importable from outside the Reachy Mini env (e.g. CI).
    from reachy_mini import ReachyMini, ReachyMiniApp  # type: ignore
except Exception:  # pragma: no cover
    ReachyMini = object  # type: ignore
    ReachyMiniApp = object  # type: ignore


INPUT_SAMPLE_RATE = 16_000  # Zero realtime expects PCM16 @ 16k
FRAME_MS = 20
FRAME_SAMPLES = INPUT_SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * 2


class ReachyMiniZeroStreaming(ReachyMiniApp):
    """Stream the Reachy mic to Zero realtime, play returned audio, fire gestures."""

    custom_app_url: Optional[str] = None

    def run(self, reachy_mini: "ReachyMini", stop_event: threading.Event) -> None:
        zero_url = os.environ.get("ZERO_API_URL", "http://host.docker.internal:18792").rstrip("/")
        token = os.environ.get("ZERO_GATEWAY_TOKEN", "")
        if not token:
            print("[reachy_mini_zero/stream] ZERO_GATEWAY_TOKEN not set — aborting.")
            return

        ws_url = zero_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/reachy/realtime/ws"
        profile = os.environ.get("ZERO_REALTIME_PROFILE", "default")

        print(f"[reachy_mini_zero/stream] connecting → {ws_url} profile={profile}")

        try:
            asyncio.run(self._run_async(reachy_mini, stop_event, ws_url, token, profile))
        except KeyboardInterrupt:
            pass
        finally:
            print("[reachy_mini_zero/stream] stopped.")

    async def _run_async(
        self,
        reachy_mini: "ReachyMini",
        stop_event: threading.Event,
        ws_url: str,
        token: str,
        profile: str,
    ) -> None:
        try:
            import websockets  # type: ignore
        except ImportError:
            print("[reachy_mini_zero/stream] missing dep: pip install websockets")
            return

        retry_s = 1.0
        while not stop_event.is_set():
            try:
                async with websockets.connect(ws_url, max_size=None) as ws:
                    await ws.send(json.dumps({
                        "type": "start",
                        "auth": token,
                        "profile": profile,
                        "client": "reachy_mini_zero/streaming",
                        "input_sample_rate": INPUT_SAMPLE_RATE,
                    }))

                    sender = asyncio.create_task(self._mic_sender(reachy_mini, ws, stop_event))
                    receiver = asyncio.create_task(self._receiver(reachy_mini, ws, stop_event))
                    await asyncio.gather(sender, receiver)
                retry_s = 1.0
            except Exception as e:
                if stop_event.is_set():
                    break
                print(f"[reachy_mini_zero/stream] WS error: {e!r} — retry in {retry_s:.1f}s")
                await asyncio.sleep(retry_s)
                retry_s = min(retry_s * 2, 16.0)

    async def _mic_sender(
        self,
        reachy_mini: "ReachyMini",
        ws: Any,
        stop_event: threading.Event,
    ) -> None:
        """Pipe Reachy mic frames as base64-encoded PCM16 to the WS server.

        We poll the SDK's ``record`` API in tight 20 ms windows. If the SDK
        does not expose a streaming mic API, we fall back to ``sounddevice``
        and an asyncio queue.
        """
        try:
            stream = self._open_mic_stream(reachy_mini)
        except Exception as e:
            print(f"[reachy_mini_zero/stream] mic open failed: {e}")
            return

        try:
            async for frame in stream:
                if stop_event.is_set():
                    break
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(frame).decode("ascii"),
                }))
        finally:
            try:
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            except Exception:
                pass

    async def _open_mic_stream(self, reachy_mini: "ReachyMini"):
        """Yield 20 ms PCM16 mono @ 16 kHz frames from the Reachy mic.

        Tries the native SDK stream first, falls back to sounddevice when
        the SDK only exposes blocking ``record(seconds=...)``.
        """
        # Native SDK streaming hook (preferred)
        try:
            stream_fn = getattr(reachy_mini.media, "stream_input", None)
            if callable(stream_fn):
                async for chunk in stream_fn(  # type: ignore[misc]
                    sample_rate=INPUT_SAMPLE_RATE,
                    frame_ms=FRAME_MS,
                    dtype="int16",
                ):
                    yield bytes(chunk)
                return
        except Exception as e:
            print(f"[reachy_mini_zero/stream] sdk stream_input unavailable: {e}")

        # Fallback: sounddevice → asyncio queue
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            print("[reachy_mini_zero/stream] install sounddevice for fallback mic")
            return

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)

        def _cb(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                pass
            arr = np.asarray(indata).reshape(-1)
            if arr.dtype != np.int16:
                arr = np.clip(arr, -1.0, 1.0)
                arr = (arr * 32767).astype(np.int16)
            loop.call_soon_threadsafe(queue.put_nowait, arr.tobytes())

        with sd.InputStream(
            samplerate=INPUT_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            callback=_cb,
        ):
            while True:
                yield await queue.get()

    async def _receiver(
        self,
        reachy_mini: "ReachyMini",
        ws: Any,
        stop_event: threading.Event,
    ) -> None:
        """Decode server frames: audio.delta → speaker, gesture → motors,
        transcript → console."""
        async for raw in ws:
            if stop_event.is_set():
                break
            try:
                msg = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else {}
            except Exception:
                continue
            mtype = msg.get("type") or ""

            if mtype == "transcript.partial":
                # Lightweight stdout for ops; the client UI gets the same.
                txt = msg.get("text") or ""
                if txt:
                    print(f"[reachy_mini_zero/stream] partial: {txt}")
            elif mtype == "transcript":
                txt = msg.get("text") or ""
                if txt:
                    print(f"[reachy_mini_zero/stream] heard:   {txt}")
            elif mtype == "assistant.text":
                txt = msg.get("text") or ""
                if txt:
                    print(f"[reachy_mini_zero/stream] reply:   {txt[:120]}")
            elif mtype == "audio.delta":
                pcm_b64 = msg.get("audio") or ""
                rate = int(msg.get("sample_rate") or 24000)
                if pcm_b64:
                    self._play_pcm(reachy_mini, base64.b64decode(pcm_b64), rate)
            elif mtype == "gesture":
                self._fire_gesture(reachy_mini, msg.get("action") or {})
            elif mtype == "session.error":
                print(f"[reachy_mini_zero/stream] error: {msg.get('error')}")
            elif mtype == "session.end":
                break

    # ------------------------------------------------------------------
    # Output helpers — keep these short; the SDK is what ultimately drives
    # the speaker and motors. Errors are logged but not fatal — we'd rather
    # keep the conversation going than die on a single bad frame.
    # ------------------------------------------------------------------

    def _play_pcm(self, reachy_mini: "ReachyMini", pcm_bytes: bytes, sample_rate: int) -> None:
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(pcm_bytes)
            data = buf.getvalue()
            play = getattr(reachy_mini.media, "play_wav_bytes", None)
            if callable(play):
                play(data)
                return
        except Exception as e:
            print(f"[reachy_mini_zero/stream] play_pcm failed: {e}")

        # Fallback path
        try:
            import sounddevice as sd  # type: ignore
            arr = np.frombuffer(pcm_bytes, dtype=np.int16)
            sd.play(arr, samplerate=sample_rate, blocking=False)
        except Exception:
            pass

    def _fire_gesture(self, reachy_mini: "ReachyMini", action: dict) -> None:
        kind = action.get("kind") or ""
        payload = action.get("payload", "")
        try:
            if kind == "emotion":
                reachy_mini.play_emotion(payload)  # type: ignore[attr-defined]
            elif kind == "dance":
                reachy_mini.play_dance(payload)  # type: ignore[attr-defined]
            elif kind == "motion":
                reachy_mini.play_motion(payload)  # type: ignore[attr-defined]
            elif kind == "look":
                parts = [p.strip() for p in str(payload).split(",")]
                if len(parts) == 3:
                    x, y, z = (float(p) for p in parts)
                    reachy_mini.look_at(x=x, y=y, z=z, duration=0.6)  # type: ignore[attr-defined]
        except Exception as e:
            print(f"[reachy_mini_zero/stream] gesture {kind!r} failed: {e}")
