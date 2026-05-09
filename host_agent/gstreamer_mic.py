"""
GStreamer-backed Reachy mic capture for host_agent.

Why this exists:
    The Reachy Mini USB speakerphone registers with Windows as a
    *Communications* audio endpoint. Opened through PortAudio /
    sounddevice in shared mode, Windows runs an extra AEC + AGC + noise
    suppression pass on top of the XMOS chip's own processing — and when
    no speaker reference signal is playing, that chain dead-mutes vowel
    energy. The signal that reaches Whisper has speech-like peak/RMS
    ratio but absolute levels ~20× below normal speech, which Whisper
    rejects as silence (or worse, hallucinates YouTube outros against).

    Pollen's reachy_mini SDK avoids this entirely by capturing through
    GStreamer's ``wasapi2src`` element, which uses Windows' modern
    WASAPI2 API and requests the *multimedia* role of the device. That
    bypasses comms-mode processing and gives the raw chip stream.

    This module is a drop-in equivalent: it spawns ``gst-launch-1.0``
    as a subprocess running ``wasapi2src ! audioconvert ! audioresample
    ! audio/x-raw,format=S16LE,channels=1,rate=<rate> ! fdsink``, reads
    raw PCM from its stdout in fixed-size frames, and invokes the same
    callback host_agent's existing pipeline already understands.

Subprocess vs in-process gi bindings:
    Subprocess wins on simplicity and isolation. ``pip install pygobject``
    on Windows needs GTK headers and is fragile. A subprocess crash here
    just kills the mic stream — host_agent stays up. Latency overhead
    is one process boundary plus the queue, ~5 ms; negligible against
    the 30 ms frame size.

Configuration:
    GSTREAMER_BIN_DIR (env, optional): path to the directory containing
        gst-launch-1.0.exe. If unset, ``gst-launch-1.0`` is looked up on
        PATH (Chocolatey's GStreamer install puts it there via the
        ``GSTREAMER_1_0_ROOT_MSVC_X86_64`` env var + Path manipulation
        in install-gstreamer.ps1).
    REACHY_MIC_DEVICE_HINT (env, optional): substring used to match the
        Reachy device in gst-device-monitor's output. Default: a
        permissive list (``reachy mini``, ``echo cancelling``,
        ``xmos``).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import structlog

logger = structlog.get_logger()


def _candidate_bin_dirs() -> list[str]:
    """Locations where gst-launch-1.0.exe may live, in priority order."""
    out: list[str] = []
    env_dir = os.getenv("GSTREAMER_BIN_DIR")
    if env_dir:
        out.append(env_dir)
    root = os.getenv("GSTREAMER_1_0_ROOT_MSVC_X86_64")
    if root:
        out.append(str(Path(root) / "bin"))
    # Standard Chocolatey install path
    out.append(r"C:\gstreamer\1.0\msvc_x86_64\bin")
    out.append(r"C:\gstreamer\1.0\mingw_x86_64\bin")
    # Pollen-bundled fallback (kept last because its plugin set is
    # incomplete; only works if all needed DLL deps happen to be there)
    local = os.getenv("LOCALAPPDATA")
    if local:
        out.append(str(Path(local) / "Reachy Mini Control" / ".venv" /
                       "Lib" / "site-packages" / "gstreamer_cli" / "bin"))
    # PATH lookup
    on_path = shutil.which("gst-launch-1.0")
    if on_path:
        out.append(str(Path(on_path).parent))
    return [d for d in out if d and Path(d, "gst-launch-1.0.exe").exists()]


def find_gstreamer_bin() -> Optional[str]:
    dirs = _candidate_bin_dirs()
    return dirs[0] if dirs else None


def is_available() -> bool:
    return find_gstreamer_bin() is not None


_DEFAULT_DEVICE_HINTS = (
    "reachy mini",
    "echo cancelling speakerphone",
    "xmos",
    "xvf",
)


@dataclass
class GStreamerDevice:
    name: str
    api: str          # "wasapi2", "wasapi", "directsound", etc.
    device_id: str    # The wasapi2-specific device id usable with `device=`
    channels: int
    rate: int
    is_loopback: bool = False  # True for "what's playing on the speakers" capture


def list_audio_sources(bin_dir: Optional[str] = None) -> list[GStreamerDevice]:
    """Run gst-device-monitor-1.0 and parse its Audio/Source output.

    Output is a list of devices with their wasapi2 id, which is what
    ``wasapi2src device=<id>`` accepts. Falls back to the default device
    if no Reachy match is found.
    """
    bin_dir = bin_dir or find_gstreamer_bin()
    if not bin_dir:
        return []
    monitor = Path(bin_dir, "gst-device-monitor-1.0.exe")
    if not monitor.exists():
        return []
    env = _gst_subprocess_env(bin_dir)
    try:
        proc = subprocess.run(
            [str(monitor), "Audio/Source"],
            capture_output=True,
            text=True,
            timeout=20.0,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        logger.warning("gstreamer_device_monitor_failed", error=str(e))
        return []
    return _parse_device_monitor(proc.stdout or "")


def _parse_device_monitor(text: str) -> list[GStreamerDevice]:
    devices: list[GStreamerDevice] = []
    # gst-device-monitor output has "Device found:" headers followed by
    # name/class/properties. Each block looks like:
    #
    #     Device found:
    #         name  : Echo Cancelling Speakerphone (Reachy Mini Audio)
    #         class : Audio/Source
    #         properties:
    #             device.api = wasapi2
    #             wasapi2.device.id = "{0.0.1.00000000}.{...}"
    #             ...
    blocks = re.split(r"\n\s*Device found:\s*\n", "\n" + text)
    for block in blocks[1:]:
        name_match = re.search(r"name\s*:\s*(.+)", block)
        if not name_match:
            continue
        name = name_match.group(1).strip()
        api_match = re.search(r"device\.api\s*=\s*(\S+)", block)
        api = api_match.group(1).strip().strip('"') if api_match else "unknown"
        # The wasapi2 plugin advertises the device id under both
        # `device.id` (newer GStreamer) and `wasapi2.device.id` (older).
        # Try both; prefer the namespaced form because non-wasapi2 entries
        # also carry a generic device.id field that we don't want to match.
        id_match = (
            re.search(r"wasapi2\.device\.id\s*=\s*(?:\"([^\"]+)\"|(\S+))", block)
            or re.search(r"^\s*device\.id\s*=\s*(?:\"([^\"]+)\"|(\S+))", block, re.MULTILINE)
        )
        device_id = ""
        if id_match:
            device_id = (id_match.group(1) or id_match.group(2) or "").strip()
        loopback_match = re.search(r"wasapi2\.device\.loopback\s*=\s*(\S+)", block)
        is_loopback = bool(loopback_match) and loopback_match.group(1).strip().lower() == "true"
        channels = 1
        rate = 16000
        ch_match = re.search(r"audio\.channels\s*=\s*(\d+)", block)
        if ch_match:
            try:
                channels = int(ch_match.group(1))
            except ValueError:
                pass
        rate_match = re.search(r"audio\.rate\s*=\s*(\d+)", block)
        if rate_match:
            try:
                rate = int(rate_match.group(1))
            except ValueError:
                pass
        devices.append(GStreamerDevice(
            name=name, api=api, device_id=device_id,
            channels=channels, rate=rate, is_loopback=is_loopback,
        ))
    return devices


def find_reachy_device(
    devices: list[GStreamerDevice],
    hints: tuple[str, ...] = _DEFAULT_DEVICE_HINTS,
) -> Optional[GStreamerDevice]:
    env_hint = os.getenv("REACHY_MIC_DEVICE_HINT")
    user_hints = (env_hint.lower(),) if env_hint else hints
    # Prefer wasapi2 over wasapi over directsound — wasapi2 bypasses
    # comms-mode processing entirely. Always skip loopback devices —
    # those capture what's PLAYING on the speakers, not what the user
    # is saying. With wasapi2 the same physical mic appears as both a
    # loopback and a non-loopback device; we want the latter.
    api_priority = {"wasapi2": 0, "wasapi": 1, "directsound": 2, "mme": 3}

    def score(d: GStreamerDevice) -> tuple[int, int, int, str]:
        name_l = d.name.lower()
        hint_match = 0 if any(h in name_l for h in user_hints) else 1
        loopback_penalty = 1 if d.is_loopback else 0
        return (hint_match, loopback_penalty, api_priority.get(d.api.lower(), 9), d.name)

    matched = sorted(devices, key=score)
    if matched and any(h in matched[0].name.lower() for h in user_hints) and not matched[0].is_loopback:
        return matched[0]
    return None


def _gst_subprocess_env(bin_dir: str) -> dict[str, str]:
    """Construct a child env that lets gst-launch find its DLLs + plugins."""
    env = os.environ.copy()
    # Prepend bin_dir to PATH so the dependent DLLs (gstreamer-1.0-0.dll,
    # glib-2.0-0.dll, ...) resolve.
    env["PATH"] = f"{bin_dir};{env.get('PATH', '')}"
    # Plugin path: GST_PLUGIN_PATH from the installer wins; if missing,
    # try the standard Chocolatey lib/gstreamer-1.0 layout.
    if "GST_PLUGIN_PATH" not in env:
        guess = Path(bin_dir).parent / "lib" / "gstreamer-1.0"
        if guess.exists():
            env["GST_PLUGIN_PATH"] = str(guess)
    return env


class GStreamerMicCapture:
    """Spawn gst-launch-1.0 as a subprocess and stream PCM16 frames.

    The callback receives ``(pcm_bytes, overflowed_flag, rms_norm,
    peak_norm)`` matching sounddevice.InputStream's contract used in
    ``host_agent/main.py``.
    """

    def __init__(
        self,
        rate: int = 16000,
        channels: int = 1,
        frame_samples: int = 480,    # 30ms at 16kHz
        callback: Optional[Callable[[bytes, bool, float, float], None]] = None,
        device_id: Optional[str] = None,
        bin_dir: Optional[str] = None,
        low_latency: bool = True,
    ) -> None:
        self._rate = rate
        self._channels = channels
        self._frame_bytes = frame_samples * channels * 2  # int16
        self._callback = callback
        self._device_id = device_id
        self._bin_dir = bin_dir or find_gstreamer_bin()
        self._low_latency = low_latency
        self._proc: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._device_name: str | None = None

    @property
    def device_name(self) -> str | None:
        return self._device_name

    def start(self) -> None:
        if not self._bin_dir:
            raise RuntimeError(
                "GStreamer not installed. Run host_agent/install-gstreamer.ps1 from "
                "an elevated PowerShell."
            )
        if self._proc is not None:
            return
        # Resolve the Reachy device if no explicit id was passed.
        if not self._device_id:
            devs = list_audio_sources(self._bin_dir)
            chosen = find_reachy_device(devs)
            if chosen and chosen.device_id:
                self._device_id = chosen.device_id
                self._device_name = chosen.name
                logger.info(
                    "gstreamer_mic_chose_device",
                    name=chosen.name,
                    api=chosen.api,
                    device_id=chosen.device_id,
                )
            else:
                logger.warning(
                    "gstreamer_mic_no_reachy_match",
                    candidate_count=len(devs),
                    candidates=[d.name for d in devs[:5]],
                    hint="Set REACHY_MIC_DEVICE_HINT or pass device_id explicitly",
                )

        gst_launch = str(Path(self._bin_dir, "gst-launch-1.0.exe"))
        # Pipeline: wasapi2src (multimedia role, not communications)
        # → audioconvert → audioresample → caps to PCM16 mono 16kHz
        # → fdsink fd=1 (stdout). low-latency=true asks WASAPI2 for
        # event-driven capture, lowest possible buffer.
        src = "wasapi2src"
        if self._low_latency:
            src += " low-latency=true"
        if self._device_id:
            src += f' device="{self._device_id}"'
        # role=2 = eMultimedia (the whole point of using wasapi2src)
        src += " role=2"

        caps = f"audio/x-raw,format=S16LE,channels={self._channels},rate={self._rate}"
        pipeline = (
            f"{src} ! audioconvert ! audioresample ! {caps} ! fdsink fd=1 sync=false"
        )

        env = _gst_subprocess_env(self._bin_dir)
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]

        # Use -q (quiet) to suppress the "Setting pipeline to PAUSED..."
        # banner; -e signals an EOS to flush on Ctrl+C.
        cmd = [gst_launch, "-q", "-e", *pipeline.split(" ")]
        # Note: shlex would split the device id quotes wrong; we already
        # built the pipeline as space-separated tokens that Popen handles.

        # Actually pipeline tokens quoted-string handling is tricky.
        # Easier: pass the whole pipeline as a single argument list via
        # shell=False, with the pipeline parsed by gst-launch's own
        # parser. So pass it as one big string in a single argv slot.
        cmd = [gst_launch, "-q", "-e", pipeline]

        logger.info(
            "gstreamer_mic_starting",
            rate=self._rate,
            channels=self._channels,
            device_id=self._device_id,
            bin_dir=self._bin_dir,
        )
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=env,
            bufsize=0,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )

        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="gstreamer-mic-reader", daemon=True
        )
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, name="gstreamer-mic-stderr", daemon=True
        )
        self._stderr_thread.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop_event.set()
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("gstreamer_mic_stop_error", error=str(e))
        for t in (self._reader_thread, self._stderr_thread):
            if t and t.is_alive():
                t.join(timeout=1.0)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _reader_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        buf = bytearray()
        target = self._frame_bytes
        last_log = 0.0
        try:
            while not self._stop_event.is_set():
                chunk = proc.stdout.read(target - len(buf))
                if not chunk:
                    if self._stop_event.is_set():
                        break
                    # gst-launch ended; treat as EOF
                    break
                buf.extend(chunk)
                while len(buf) >= target:
                    frame = bytes(buf[:target])
                    del buf[:target]
                    rms_norm, peak_norm = _i16_stats(frame)
                    cb = self._callback
                    if cb is not None:
                        try:
                            cb(frame, False, rms_norm, peak_norm)
                        except Exception as cb_err:
                            now = time.monotonic()
                            if now - last_log > 5.0:
                                logger.warning(
                                    "gstreamer_mic_callback_error",
                                    error=str(cb_err)[:200],
                                )
                                last_log = now
        except Exception as e:
            logger.warning("gstreamer_mic_reader_error", error=str(e))

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                if self._stop_event.is_set():
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                # Plugin-load warnings are noise; only surface real errors.
                if "WARNING" in line and "Failed to load plugin" in line:
                    continue
                if "ERROR" in line or "FATAL" in line or "Setting pipeline" in line:
                    logger.info("gstreamer_mic_stderr", line=line[:300])
        except Exception:
            pass


def _i16_stats(frame: bytes) -> tuple[float, float]:
    """Compute (rms_norm, peak_norm) for an int16 PCM frame, matching
    the convention used in main.py: values normalized to [0, 1] by
    32768."""
    import numpy as np
    if not frame:
        return 0.0, 0.0
    samples = np.frombuffer(frame, dtype="<i2").astype(np.float32)
    if samples.size == 0:
        return 0.0, 0.0
    rms = float(np.sqrt(np.mean(samples * samples))) / 32768.0
    peak = float(np.max(np.abs(samples))) / 32768.0
    return rms, peak
