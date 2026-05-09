"""
Audio capture for the Zero Host Audio Agent. Trimmed fork of Zero's
backend/app/services/meeting_audio_capture.py with the Zero imports removed
so this process can run with a minimal dependency footprint.
"""

import queue
import threading
import time
import os
from pathlib import Path

import numpy as np
import soundfile as sf
import structlog

from audio_buffer import RingBuffer

logger = structlog.get_logger(__name__)


REACHY_DEVICE_HINTS = (
    "reachy mini",
    "reachy_mini",
    "xmos",
    "xvf",
    "pollen",
    # MME truncates device names to 31 chars so "Echo Cancelling Speakerphone
    # (Reachy Mini Audio)" shows up as "Echo Cancelling Speakerphone (R".
    # Match on the distinctive prefix so MME variants are still picked up.
    "echo cancelling speakerphone",
)


def list_audio_devices() -> dict:
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
            mic_devices.append({
                "index": idx,
                "name": name,
                "host_api": host_api_name,
                "max_input_channels": int(dev.get("max_input_channels", 0)),
                "default_samplerate": int(dev.get("default_samplerate", 0)),
                "is_reachy": any(h in name.lower() for h in REACHY_DEVICE_HINTS),
            })
    except ImportError:
        logger.debug("sounddevice_not_installed")
    except Exception as e:
        logger.warning("mic_enumeration_failed", error=str(e))

    try:
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        try:
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
        finally:
            p.terminate()
    except ImportError:
        logger.debug("pyaudiowpatch_not_installed")
    except Exception as e:
        logger.warning("loopback_enumeration_failed", error=str(e))

    return {"mic": mic_devices, "system_loopback": loopback_devices}


def preferred_mic_indices(preferred_name: str | None = None) -> list[int]:
    """Return mic device indices in the order live Reachy sessions should try.

    The Reachy Mini exposes the same physical microphone through several
    Windows host APIs. For live assistant sessions, the native 16 kHz WASAPI
    device gives cleaner speech levels than the old MME alias, but Windows
    audio drivers vary, so callers should try the ordered fallbacks rather than
    assuming one index is always usable.
    """
    devs = list_audio_devices().get("mic", [])
    explicit_index = os.getenv("ZERO_PREFERRED_MIC_DEVICE_INDEX")
    if explicit_index:
        try:
            idx = int(explicit_index)
            if any(int(d["index"]) == idx for d in devs):
                return [idx] + [int(d["index"]) for d in devs if int(d["index"]) != idx]
        except ValueError:
            logger.warning("preferred_mic_index_invalid", value=explicit_index)

    if preferred_name:
        needle = preferred_name.lower()
        preferred = [d for d in devs if needle in d["name"].lower()]
        if preferred:
            devs = preferred

    # Prefer the native 16 kHz Reachy mic path first. MME is kept as a fallback:
    # it is broadly compatible, but on this machine it captured ordinary speech
    # too quietly/noisily for reliable live assistant transcription.
    host_api_priority = {
        "windows wasapi": 0,
        "windows wdm-ks": 1,
        "mme": 2,
        "windows directsound": 3,
    }

    def _rank(d: dict) -> tuple[int, int, int, str]:
        host_api = d.get("host_api", "").lower()
        rate = int(d.get("default_samplerate") or 0)
        native_16k = 0 if 15000 <= rate <= 17000 else 1
        return (
            0 if d.get("is_reachy") else 1,
            native_16k,
            host_api_priority.get(host_api, 99),
            str(d.get("name") or ""),
        )

    ordered = sorted(devs, key=_rank)
    return [int(d["index"]) for d in ordered]


def find_default_mic_index(preferred_name: str | None = None) -> int | None:
    candidates = preferred_mic_indices(preferred_name)
    if candidates:
        return candidates[0]
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
