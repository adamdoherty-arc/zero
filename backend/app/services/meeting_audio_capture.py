"""Audio capture service for Windows using WASAPI loopback + microphone."""

import queue
import threading
import time
from pathlib import Path

import structlog

try:
    import numpy as np
    import soundfile as sf
    _AUDIO_AVAILABLE = True
except ImportError:
    _AUDIO_AVAILABLE = False


def _has_audio_backend() -> bool:
    """Check if at least one audio capture backend is installed."""
    try:
        import pyaudiowpatch  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import sounddevice  # noqa: F401
        return True
    except ImportError:
        pass
    return False


from app.infrastructure.config import get_settings
from app.services.meeting_audio_buffer import RingBuffer

logger = structlog.get_logger(__name__)


# Substrings that mark an input device as the Reachy Mini's on-board mic array.
# The Windows USB Audio device is reported as "Echo Cancelling Speakerphone
# (Reachy Mini Audio)" via sounddevice. We also accept Pollen / XMOS / XVF for
# future-proofing against driver-name changes.
REACHY_DEVICE_HINTS = ("reachy mini", "reachy_mini", "xmos", "xvf", "pollen")


def list_audio_devices() -> dict:
    """
    Enumerate mic and system-loopback input devices.

    Returns a dict with two lists:
      {"mic": [...], "system_loopback": [...]}

    Each entry: {
        "index": int,
        "name": str,
        "host_api": str,
        "max_input_channels": int,
        "default_samplerate": int,
        "is_reachy": bool,
    }

    On systems without sounddevice/pyaudiowpatch installed, returns empty lists
    (e.g. when Zero's backend runs in Docker — the host_agent is the real home
    for this call).
    """
    mic_devices: list[dict] = []
    loopback_devices: list[dict] = []

    try:
        import sounddevice as sd

        host_apis = sd.query_hostapis()
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) < 1:
                continue
            name = dev.get("name", "")
            host_api_idx = dev.get("hostapi", 0)
            host_api_name = host_apis[host_api_idx].get("name", "?") if host_api_idx < len(host_apis) else "?"
            entry = {
                "index": idx,
                "name": name,
                "host_api": host_api_name,
                "max_input_channels": int(dev.get("max_input_channels", 0)),
                "default_samplerate": int(dev.get("default_samplerate", 0)),
                "is_reachy": any(h in name.lower() for h in REACHY_DEVICE_HINTS),
            }
            mic_devices.append(entry)
    except ImportError:
        logger.debug("sounddevice_not_installed_skipping_mic_enumeration")
    except Exception as e:
        logger.warning("mic_enumeration_failed", error=str(e))

    try:
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if not dev.get("isLoopbackDevice"):
                    continue
                loopback_devices.append({
                    "index": int(dev["index"]),
                    "name": dev["name"],
                    "host_api": "WASAPI",
                    "max_input_channels": int(dev.get("maxInputChannels", 0)),
                    "default_samplerate": int(dev.get("defaultSampleRate", 0)),
                    "is_reachy": False,
                })
            _ = wasapi_info
        finally:
            p.terminate()
    except ImportError:
        logger.debug("pyaudiowpatch_not_installed_skipping_loopback_enumeration")
    except Exception as e:
        logger.warning("loopback_enumeration_failed", error=str(e))

    return {"mic": mic_devices, "system_loopback": loopback_devices}


def find_default_mic_index(
    preferred_name: str | None = None,
    *,
    prefer_reachy: bool = True,
) -> int | None:
    """
    Resolve a preferred mic device name (or the Reachy if present) to an index.

    Match priority:
      1. Exact preferred_name match (case-insensitive substring)
      2. Reachy device (when prefer_reachy)
      3. None — let sounddevice use system default
    """
    devs = list_audio_devices().get("mic", [])
    if preferred_name:
        needle = preferred_name.lower()
        for d in devs:
            if needle in d["name"].lower():
                return d["index"]
    if prefer_reachy:
        for d in devs:
            if d.get("is_reachy"):
                return d["index"]
    return None


class AudioCapture:
    def __init__(
        self,
        sample_rate: int = 16000,
        *,
        mic_device_index: int | None = None,
        system_device_index: int | None = None,
    ):
        self.sample_rate = sample_rate
        self.mic_device_index = mic_device_index
        self.system_device_index = system_device_index
        self._system_queue: queue.Queue = queue.Queue(maxsize=200)
        self._mic_queue: queue.Queue = queue.Queue(maxsize=200)
        self.ring_buffer = RingBuffer(capacity=sample_rate * 30)
        self._is_recording = False
        self._wav_writer: sf.SoundFile | None = None
        self._current_file: Path | None = None
        self._mixer_thread: threading.Thread | None = None
        self._system_stream = None
        self._mic_stream = None
        self._total_samples = 0
        self._device_sample_rate: int | None = None
        self._mic_device_name: str | None = None
        self._audio_levels = {"system": 0.0, "mic": 0.0, "mixed": 0.0}
        self._level_lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def duration_seconds(self) -> float:
        return self._total_samples / self.sample_rate

    @property
    def audio_levels(self) -> dict:
        with self._level_lock:
            return self._audio_levels.copy()

    @property
    def mic_device_name(self) -> str | None:
        return self._mic_device_name

    def start(self, output_path: Path, source: str = "mixed") -> None:
        if not _AUDIO_AVAILABLE:
            raise RuntimeError("Audio capture not available (numpy/soundfile not installed)")
        if not _has_audio_backend():
            raise RuntimeError(
                "No audio capture backend available. "
                "Install pyaudiowpatch (system audio) or sounddevice (microphone). "
                "Audio recording is not supported in Docker containers."
            )
        if self._is_recording:
            raise RuntimeError("Already recording")
        self._current_file = output_path
        self._total_samples = 0
        self._is_recording = True
        self._wav_writer = sf.SoundFile(
            str(output_path), mode="w", samplerate=self.sample_rate,
            channels=1, format="WAV", subtype="PCM_16",
        )
        if source in ("system", "mixed"):
            self._start_system_capture()
        if source in ("mic", "mixed"):
            self._start_mic_capture()
        self._mixer_thread = threading.Thread(
            target=self._mixer_loop, args=(source,), daemon=True, name="audio-mixer",
        )
        self._mixer_thread.start()
        logger.info("audio_capture_started", source=source, path=str(output_path))

    def stop(self) -> Path | None:
        if not self._is_recording:
            return None
        self._is_recording = False
        if self._system_stream is not None:
            try:
                self._system_stream.stop_stream()
                self._system_stream.close()
            except Exception:
                pass
            self._system_stream = None
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None
        self._device_sample_rate = None
        if self._mixer_thread is not None:
            self._mixer_thread.join(timeout=5)
            self._mixer_thread = None
        if self._wav_writer is not None:
            self._wav_writer.close()
            self._wav_writer = None
        output = self._current_file
        self._current_file = None
        logger.info("audio_capture_stopped", path=str(output), duration=self.duration_seconds)
        return output

    def _start_system_capture(self) -> None:
        try:
            import pyaudiowpatch as pyaudio
            p = pyaudio.PyAudio()
            if self.system_device_index is not None:
                chosen = p.get_device_info_by_index(self.system_device_index)
            else:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                chosen = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
                if not chosen["isLoopbackDevice"]:
                    for i in range(p.get_device_count()):
                        dev = p.get_device_info_by_index(i)
                        if dev.get("isLoopbackDevice") and dev["name"].startswith(
                            chosen["name"].split(" (")[0]
                        ):
                            chosen = dev
                            break
            self._device_sample_rate = int(chosen["defaultSampleRate"])
            self._system_stream = p.open(
                format=pyaudio.paFloat32,
                channels=chosen["maxInputChannels"],
                rate=self._device_sample_rate,
                input=True,
                input_device_index=chosen["index"],
                frames_per_buffer=1024,
                stream_callback=self._system_callback,
            )
            self._system_stream.start_stream()
            logger.info("system_audio_started", device=chosen["name"],
                       device_rate=self._device_sample_rate, target_rate=self.sample_rate)
        except ImportError:
            logger.warning("pyaudiowpatch_not_available")
        except Exception as e:
            logger.error("system_audio_failed", error=str(e))

    def _start_mic_capture(self) -> None:
        try:
            import sounddevice as sd
            kwargs = dict(
                samplerate=self.sample_rate, channels=1, dtype="float32",
                blocksize=1024, callback=self._mic_callback,
            )
            if self.mic_device_index is not None:
                kwargs["device"] = self.mic_device_index
                try:
                    info = sd.query_devices(self.mic_device_index)
                    self._mic_device_name = info.get("name")
                except Exception:
                    self._mic_device_name = f"index={self.mic_device_index}"
            else:
                try:
                    default_in = sd.default.device[0]
                    if default_in is not None and default_in != -1:
                        self._mic_device_name = sd.query_devices(default_in).get("name")
                except Exception:
                    self._mic_device_name = None
            self._mic_stream = sd.InputStream(**kwargs)
            self._mic_stream.start()
            logger.info(
                "mic_capture_started",
                rate=self.sample_rate,
                device=self._mic_device_name,
                device_index=self.mic_device_index,
            )
        except ImportError:
            logger.warning("sounddevice_not_available")
        except Exception as e:
            logger.error(
                "mic_capture_failed",
                error=str(e),
                requested_device_index=self.mic_device_index,
            )

    def _system_callback(self, in_data, frame_count, time_info, status):
        if not self._is_recording:
            return (None, 0)
        try:
            audio = np.frombuffer(in_data, dtype=np.float32)
            if len(audio) > frame_count:
                audio = audio.reshape(-1, audio.shape[0] // frame_count)[:, 0]
            self._system_queue.put_nowait(audio)
        except queue.Full:
            pass
        return (None, 0)

    def _mic_callback(self, indata, frames, time_info, status):
        if not self._is_recording:
            return
        try:
            self._mic_queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def _mixer_loop(self, source: str) -> None:
        while self._is_recording:
            try:
                mixed = None
                if source == "system":
                    try:
                        chunk = self._system_queue.get(timeout=0.1)
                        mixed = self._resample_if_needed(chunk)
                        self._update_level("system", chunk)
                    except queue.Empty:
                        continue
                elif source == "mic":
                    try:
                        chunk = self._mic_queue.get(timeout=0.1)
                        mixed = chunk
                        self._update_level("mic", chunk)
                    except queue.Empty:
                        continue
                elif source == "mixed":
                    system_chunk = mic_chunk = None
                    try:
                        system_chunk = self._system_queue.get(timeout=0.05)
                        system_chunk = self._resample_if_needed(system_chunk)
                        self._update_level("system", system_chunk)
                    except queue.Empty:
                        pass
                    try:
                        mic_chunk = self._mic_queue.get(timeout=0.05)
                        self._update_level("mic", mic_chunk)
                    except queue.Empty:
                        pass
                    if system_chunk is not None and mic_chunk is not None:
                        min_len = min(len(system_chunk), len(mic_chunk))
                        mixed = (system_chunk[:min_len] * 0.7) + (mic_chunk[:min_len] * 0.3)
                    elif system_chunk is not None:
                        mixed = system_chunk
                    elif mic_chunk is not None:
                        mixed = mic_chunk
                    else:
                        continue
                if mixed is not None:
                    mixed = np.clip(mixed, -1.0, 1.0)
                    self._update_level("mixed", mixed)
                    self.ring_buffer.write(mixed)
                    if self._wav_writer is not None:
                        self._wav_writer.write(mixed)
                        self._total_samples += len(mixed)
                        if self._total_samples % (self.sample_rate * 5) < 1024:
                            self._wav_writer.flush()
            except Exception as e:
                logger.error("mixer_error", error=str(e))
                time.sleep(0.01)

    def _resample_if_needed(self, audio: np.ndarray) -> np.ndarray:
        if self._device_sample_rate is None or self._device_sample_rate == self.sample_rate:
            return audio
        ratio = self.sample_rate / self._device_sample_rate
        new_length = int(len(audio) * ratio)
        if new_length == 0:
            return audio
        old_indices = np.arange(len(audio))
        new_indices = np.linspace(0, len(audio) - 1, new_length)
        return np.interp(new_indices, old_indices, audio).astype(np.float32)

    def _update_level(self, channel: str, audio: np.ndarray) -> None:
        level = float(np.abs(audio).mean())
        with self._level_lock:
            self._audio_levels[channel] = level
