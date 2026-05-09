"""
Streaming PCM speaker output to a USB audio device — typically the Reachy
Mini's built-in speakerphone.

The Reachy daemon only exposes ``/api/media/play_sound`` (filename-based),
which is unusable for the realtime voice loop where assistant audio arrives
as ~50 ms PCM chunks. host_agent runs on the Windows host with direct USB
access, so it's the right place to push raw PCM to the speaker.

Public surface:
    SpeakerStream(rate=24000)
    speaker.start()
    speaker.write_pcm16(bytes)         # mono int16 little-endian
    speaker.stop()

Device selection mirrors ``find_default_mic_index``: prefer
``ZERO_PREFERRED_SPEAKER_DEVICE`` (substring match), fall back to a Reachy
device hint scan, then to the system default output.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Optional

import numpy as np
import structlog

from audio_capture import REACHY_DEVICE_HINTS

logger = structlog.get_logger(__name__)


def list_output_devices() -> list[dict]:
    """Enumerate output-capable devices, with a Reachy-match flag."""
    out: list[dict] = []
    try:
        import sounddevice as sd
        host_apis = sd.query_hostapis()
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_output_channels", 0) < 1:
                continue
            name = dev.get("name", "")
            host_api_idx = dev.get("hostapi", 0)
            host_api_name = (
                host_apis[host_api_idx].get("name", "?")
                if host_api_idx < len(host_apis)
                else "?"
            )
            out.append({
                "index": idx,
                "name": name,
                "host_api": host_api_name,
                "max_output_channels": int(dev.get("max_output_channels", 0)),
                "default_samplerate": int(dev.get("default_samplerate", 0)),
                "is_reachy": any(h in name.lower() for h in REACHY_DEVICE_HINTS),
            })
    except ImportError:
        logger.debug("sounddevice_not_installed")
    except Exception as e:
        logger.warning("speaker_enumeration_failed", error=str(e))
    return out


def find_default_speaker_index(preferred_name: Optional[str] = None) -> Optional[int]:
    devs = list_output_devices()
    if preferred_name:
        needle = preferred_name.lower()
        for d in devs:
            if needle in d["name"].lower():
                return d["index"]
    # Prefer modern Windows host APIs for output. MME is broadly compatible,
    # but the Reachy USB speakerphone can hang while opening through MME after
    # host_agent restarts; WASAPI/DirectSound open quickly and avoid that
    # stale-device state.
    host_api_priority = {
        "windows wasapi": 0,
        "windows directsound": 1,
        "mme": 2,
        "windows wdm-ks": 3,
    }

    def _rank(d: dict) -> int:
        return host_api_priority.get(d.get("host_api", "").lower(), 99)

    reachy_devs = sorted([d for d in devs if d.get("is_reachy")], key=_rank)
    if reachy_devs:
        return reachy_devs[0]["index"]
    return None


class SpeakerStream:
    """Persistent sounddevice OutputStream for raw PCM16 mono audio.

    Frames pushed via ``write_pcm16`` are queued and drained by the audio
    callback. A bounded queue caps memory if the producer outpaces the
    device — old frames are dropped rather than blocking the realtime path.
    """

    def __init__(
        self,
        *,
        rate: int = 24000,
        device_index: Optional[int] = None,
        max_queued_frames: int = 140,
        prebuffer_ms: int = 260,
    ) -> None:
        self.rate = rate
        self.device_index = device_index
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_queued_frames)
        self._stream = None
        self._stopped = threading.Event()
        self._device_name: Optional[str] = None
        self._prebuffer_ms = max(0, int(prebuffer_ms))
        self._prebuffer_samples = 0
        self._queued_samples = 0
        self._queue_lock = threading.Lock()
        self._leftover = np.zeros(0, dtype=np.float32)
        self._playing = False
        self._underflows = 0
        self._dropped_frames = 0
        self._last_status_log = 0.0

    @property
    def device_name(self) -> Optional[str]:
        return self._device_name

    def start(self) -> dict:
        import sounddevice as sd

        if self._stream is not None:
            return self.info()

        idx = self.device_index
        if idx is None:
            preferred = os.getenv("ZERO_PREFERRED_SPEAKER_DEVICE") or None
            idx = find_default_speaker_index(preferred)
        if idx is None:
            raise RuntimeError(
                "No usable output device found. "
                "Set ZERO_PREFERRED_SPEAKER_DEVICE or plug the Reachy speaker in."
            )

        info = sd.query_devices(idx)
        self.device_index = idx
        self._device_name = info.get("name", f"#{idx}")

        # Use the device's native samplerate when possible — sounddevice will
        # raise if we open a device at a rate it doesn't support, and the
        # callback tone is much cleaner without resampling. Most USB
        # speakerphones support 16k/24k/48k natively.
        device_rate = int(info.get("default_samplerate") or self.rate)
        # We need to give sounddevice the rate of the data we'll write. If the
        # device prefers a different rate we resample on the way in.
        self._device_rate = device_rate
        self._needs_resample = device_rate != self.rate

        self._prebuffer_samples = int(device_rate * (self._prebuffer_ms / 1000.0))

        def callback(outdata, frames, _time, status):
            if status:
                now = time.monotonic()
                if now - self._last_status_log > 5.0:
                    self._last_status_log = now
                    logger.debug("speaker_callback_status", status=str(status))
            with self._queue_lock:
                available = int(self._queued_samples + self._leftover.size)
                if not self._playing and available < self._prebuffer_samples:
                    outdata.fill(0)
                    return
                self._playing = True
            need = frames
            chunks: list[np.ndarray] = []
            with self._queue_lock:
                if self._leftover.size:
                    chunks.append(self._leftover)
                    need -= self._leftover.size
                    self._leftover = np.zeros(0, dtype=np.float32)
            while need > 0:
                try:
                    frame = self._queue.get_nowait()
                except queue.Empty:
                    break
                with self._queue_lock:
                    self._queued_samples = max(0, self._queued_samples - int(frame.size))
                chunks.append(frame)
                need -= frame.size
            if not chunks:
                outdata.fill(0)
                with self._queue_lock:
                    self._playing = False
                    self._underflows += 1
                return
            buf = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            if buf.size > frames:
                outdata[:, 0] = buf[:frames]
                with self._queue_lock:
                    self._leftover = buf[frames:]
            else:
                outdata[: buf.size, 0] = buf
                outdata[buf.size :, 0] = 0
                with self._queue_lock:
                    self._playing = False
                    self._underflows += 1

        self._stream = sd.OutputStream(
            samplerate=device_rate,
            channels=1,
            dtype="float32",
            blocksize=max(512, int(device_rate * 0.04)),
            latency="high",
            device=idx,
            callback=callback,
        )
        self._stream.start()
        logger.info(
            "speaker_stream_started",
            device_index=idx,
            device_name=self._device_name,
            rate=device_rate,
            input_rate=self.rate,
            resample=self._needs_resample,
            prebuffer_ms=self._prebuffer_ms,
        )
        return self.info()

    def write_pcm16(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or self._stream is None:
            return
        try:
            samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32) / 32768.0
        except Exception as e:
            logger.debug("speaker_decode_dropped", error=str(e))
            return
        if self._needs_resample and samples.size > 0:
            # Cheap linear resample. Realtime audio is short (~50 ms chunks)
            # so the artefacts are inaudible, and we avoid pulling in scipy.
            ratio = self._device_rate / float(self.rate)
            new_len = max(1, int(round(samples.size * ratio)))
            xs = np.linspace(0, samples.size - 1, num=new_len, dtype=np.float32)
            samples = np.interp(xs, np.arange(samples.size, dtype=np.float32), samples).astype(np.float32)
        try:
            self._queue.put_nowait(samples)
            with self._queue_lock:
                self._queued_samples += int(samples.size)
        except queue.Full:
            # Drop oldest, push newest. Keeps latency from unbounded growth
            # if the device underruns or the producer floods us.
            try:
                dropped = self._queue.get_nowait()
                with self._queue_lock:
                    self._queued_samples = max(0, self._queued_samples - int(dropped.size))
                    self._dropped_frames += 1
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(samples)
                with self._queue_lock:
                    self._queued_samples += int(samples.size)
            except queue.Full:
                pass

    def flush(self) -> None:
        """Drop any queued frames (e.g. when the user barges in)."""
        try:
            while True:
                dropped = self._queue.get_nowait()
                with self._queue_lock:
                    self._queued_samples = max(0, self._queued_samples - int(dropped.size))
        except queue.Empty:
            pass
        with self._queue_lock:
            self._leftover = np.zeros(0, dtype=np.float32)
            self._playing = False

    def stop(self) -> None:
        self._stopped.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.debug("speaker_stop_failed", error=str(e))
            self._stream = None
        logger.info("speaker_stream_stopped")

    def info(self) -> dict:
        with self._queue_lock:
            queued_samples = int(self._queued_samples + self._leftover.size)
            device_rate = getattr(self, "_device_rate", None) or self.rate
            queued_ms = int(round((queued_samples / float(device_rate)) * 1000)) if device_rate else 0
        return {
            "active": self._stream is not None,
            "device_index": self.device_index,
            "device_name": self._device_name,
            "input_rate": self.rate,
            "device_rate": getattr(self, "_device_rate", None),
            "resample": getattr(self, "_needs_resample", False),
            "queued_frames": self._queue.qsize(),
            "queued_ms": queued_ms,
            "prebuffer_ms": self._prebuffer_ms,
            "playing": self._playing,
            "underflows": self._underflows,
            "dropped_frames": self._dropped_frames,
        }
