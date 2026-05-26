"""
Camera worker for the host agent.

Opens a USB/DirectShow camera on the Windows host, polls frames in a
background thread, and exposes the latest JPEG-encoded frame plus an
iterator that yields multipart/x-mixed-replace chunks for MJPEG streaming.

Any FastAPI route can:
  worker = get_camera_worker()
  worker.ensure_started()
  jpeg = worker.latest_jpeg()
  async for chunk in worker.mjpeg_chunks(): ...

The worker is lazy: it only opens the camera when a consumer asks for a
frame or the stream. It auto-stops after a few idle seconds so the USB
device is not held open when nobody is watching.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import structlog

logger = structlog.get_logger()


_BOUNDARY = "zero-frame"

# Configurable via env so users with multiple cams can pick.
# -1 = auto-detect: find the Reachy Mini Camera by name; fall back to index 0.
_DEFAULT_INDEX = int(os.getenv("ZERO_REACHY_CAMERA_DEVICE", "-1"))
_DEFAULT_WIDTH = int(os.getenv("ZERO_REACHY_CAMERA_WIDTH", "1280"))
_DEFAULT_HEIGHT = int(os.getenv("ZERO_REACHY_CAMERA_HEIGHT", "720"))
_DEFAULT_FPS = int(os.getenv("ZERO_REACHY_CAMERA_FPS", "15"))
_DEFAULT_JPEG_Q = int(os.getenv("ZERO_REACHY_CAMERA_JPEG_QUALITY", "80"))
_IDLE_SHUTDOWN_S = float(os.getenv("ZERO_REACHY_CAMERA_IDLE_SHUTDOWN_S", "15"))

# Keywords in the Windows PnP device name that identify the robot camera.
_REACHY_NAME_KEYWORDS = ["reachy", "38fb"]  # VID_38FB = Pollen Robotics USB VID

# Module-level cache so repeated calls to _find_reachy_device_index() don't
# re-run the expensive PowerShell + cv2 probe after the first resolution.
_resolved_device_index: Optional[int] = None

# Reachy daemon grabs the USB camera on boot and won't release it unless asked.
# We hit /api/media/release before opening so cv2 can actually get the device.
_REACHY_API_URL = os.getenv("REACHY_API_URL", "http://localhost:8000").rstrip("/")


def _release_reachy_media() -> None:
    """Best-effort: ask the Reachy daemon to release its media hold.

    Silent no-op if the daemon isn't running or doesn't respond. Called before
    every OpenCV open attempt — cheap, idempotent, and avoids a handshake
    failure where the daemon is holding the camera.
    """
    try:
        import urllib.request

        req = urllib.request.Request(
            f"{_REACHY_API_URL}/api/media/release",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            logger.debug("reachy_media_released", status=resp.status)
    except Exception as e:
        logger.debug("reachy_media_release_skipped", error=str(e))


@dataclass
class CameraStatus:
    active: bool = False
    backend: str = "none"
    device_index: int = _DEFAULT_INDEX
    width: int = 0
    height: int = 0
    fps: float = 0.0
    last_frame_ts: float = 0.0
    consumers: int = 0
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "active": self.active,
            "backend": self.backend,
            "device_index": self.device_index,
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 2),
            "age_seconds": max(0.0, time.time() - self.last_frame_ts) if self.last_frame_ts else None,
            "consumers": self.consumers,
            "last_error": self.last_error,
        }


class _GStreamerCameraAdapter:
    """
    Wraps `reachy_mini.media.camera_gstreamer.GStreamerCamera` so it quacks
    like `cv2.VideoCapture`: `.read() → (ok, frame)` and `.release()`.
    """

    def __init__(self, cam, first_frame):
        self._cam = cam
        self._first_frame = first_frame  # consumed on the next .read()
        self.last_error: Optional[str] = None

    def read(self):
        if self._first_frame is not None:
            frame = self._first_frame
            self._first_frame = None
            return True, frame
        try:
            frame = self._cam.read()
        except Exception as e:
            self.last_error = str(e)[:180]
            logger.warning("camera_gstreamer_read_failed", error=self.last_error)
            return False, None
        return (frame is not None), frame

    def release(self):
        try:
            self._cam.close()
        except Exception:
            pass

    def get(self, _prop):  # cv2.VideoCapture.get parity
        return 0


class CameraWorker:
    _instance: Optional["CameraWorker"] = None

    def __init__(self) -> None:
        self._status = CameraStatus()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_lock = threading.Lock()
        self._frame_event = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consumers_lock = threading.Lock()
        self._last_consumer_ts: float = 0.0
        # Per-instance device index; -1 means "auto-detect on next open"
        self._device_index: int = _DEFAULT_INDEX

    @classmethod
    def instance(cls) -> "CameraWorker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # --- Lifecycle ---------------------------------------------------------

    def ensure_started(self) -> None:
        """Idempotently spin up the capture thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="CameraWorker", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def switch_device(self, index: int) -> dict:
        """Stop the current capture, switch to the given device index, restart."""
        logger.info("camera_switch_device", from_index=self._device_index, to_index=index)
        self._device_index = index
        self.stop()
        # Clear stale frame so consumers don't get stale bytes from old device
        with self._latest_lock:
            self._latest_jpeg = None
            self._status = CameraStatus()
            self._status.device_index = index
        self._stop.clear()
        self._frame_event.clear()
        self.ensure_started()
        return {"switched": True, "device_index": index}

    def _active_device_index(self) -> int:
        """Return the resolved device index (auto-detect if still -1)."""
        if self._device_index >= 0:
            return self._device_index
        resolved = _find_reachy_device_index()
        self._device_index = resolved
        return resolved

    def status(self) -> dict:
        data = self._status.to_dict()
        with self._latest_lock:
            data["frame_available"] = bool(self._latest_jpeg)
        return data

    # --- Consumer helpers --------------------------------------------------

    def _add_consumer(self) -> None:
        with self._consumers_lock:
            self._status.consumers += 1
            self._last_consumer_ts = time.time()

    def _drop_consumer(self) -> None:
        with self._consumers_lock:
            self._status.consumers = max(0, self._status.consumers - 1)
            self._last_consumer_ts = time.time()

    def latest_jpeg(self, wait_s: float = 2.0) -> Optional[bytes]:
        """Return the most recent JPEG bytes, blocking up to wait_s for the first frame."""
        self.ensure_started()
        self._add_consumer()
        try:
            if self._latest_jpeg is None:
                self._frame_event.wait(timeout=wait_s)
            with self._latest_lock:
                return self._latest_jpeg
        finally:
            self._drop_consumer()

    async def mjpeg_chunks(self) -> AsyncIterator[bytes]:
        """
        Async generator yielding multipart/x-mixed-replace chunks.
        One chunk per frame. Caller is responsible for the outer response.
        """
        self.ensure_started()
        self._add_consumer()
        try:
            last_ts = 0.0
            # Yield an empty preamble so clients see the boundary immediately.
            yield b""
            while True:
                jpeg = None
                for _ in range(20):  # wait up to ~2s for a frame
                    with self._latest_lock:
                        if self._status.last_frame_ts > last_ts:
                            jpeg = self._latest_jpeg
                            last_ts = self._status.last_frame_ts
                            break
                    await asyncio.sleep(0.05)
                if jpeg is None:
                    # No fresh frame — emit a tiny keep-alive boundary instead of closing.
                    await asyncio.sleep(0.1)
                    continue
                chunk = (
                    f"--{_BOUNDARY}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode("ascii") + jpeg + b"\r\n"
                yield chunk
                # Soft target cadence — the capture thread drives real fps.
                await asyncio.sleep(1.0 / max(1, _DEFAULT_FPS))
        finally:
            self._drop_consumer()

    # --- Capture loop ------------------------------------------------------

    # --- Capture backends --------------------------------------------------

    def _open_gstreamer(self):
        """
        Preferred on Windows when the Reachy daemon is running: read BGR
        frames from the daemon's `win32ipcvideosrc` shared-memory pipe via
        the SDK's `GStreamerCamera`. Zero contention — the daemon keeps
        the camera open and pushes frames into the pipe; we're a passive
        reader.

        Returns an adapter that quacks like `cv2.VideoCapture`
        (`.read() → (ok, frame)`, `.release()`), or None if unavailable.
        """
        try:
            from reachy_mini.media.camera_gstreamer import GStreamerCamera
        except Exception as e:
            logger.debug("camera_gstreamer_unavailable", error=str(e)[:180])
            return None

        try:
            cam = GStreamerCamera(log_level="WARNING")
            cam.open()
        except Exception as e:
            logger.info("camera_gstreamer_open_failed", error=str(e)[:180])
            return None

        # Probe: we need the daemon to be actively pushing frames, otherwise
        # `read()` returns None forever.
        got_frame = False
        first_frame = None
        for _ in range(30):  # ~1.5s
            try:
                first_frame = cam.read()
            except Exception as e:
                logger.info("camera_gstreamer_probe_failed", error=str(e)[:180])
                try:
                    cam.close()
                except Exception:
                    pass
                return None
            if first_frame is not None:
                got_frame = True
                break
            time.sleep(0.05)
        if not got_frame:
            logger.info("camera_gstreamer_no_frames_yet")
            try:
                cam.close()
            except Exception:
                pass
            return None

        adapter = _GStreamerCameraAdapter(cam, first_frame)
        self._status.backend = "gstreamer_ipc"
        return adapter

    def _open_capture(self):
        """Fallback: open cv2.VideoCapture on Windows DirectShow / MSMF / default."""
        import cv2

        # Silence OpenCV's C++ logger so a busy/locked device doesn't flood stdout.
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:
            pass

        # Reachy's daemon holds the USB camera by default — we have to ask
        # before cv2 can open the device.
        _release_reachy_media()

        device_idx = self._active_device_index()
        self._status.device_index = device_idx

        backends = [
            (cv2.CAP_DSHOW, "dshow"),
            (cv2.CAP_MSMF, "msmf"),
            (cv2.CAP_ANY, "any"),
        ]
        for backend, name in backends:
            cap = cv2.VideoCapture(device_idx, backend)
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, _DEFAULT_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _DEFAULT_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, _DEFAULT_FPS)
            # Probe: a backend can isOpened() == True yet fail every read. Take
            # up to 20 tries (~1s) to get an actual frame before we consider it.
            got_frame = False
            for _ in range(20):
                ok, frame = cap.read()
                if ok and frame is not None:
                    got_frame = True
                    break
                time.sleep(0.05)
            if got_frame:
                self._status.backend = name
                return cap
            logger.info("camera_worker_backend_no_frames", backend=name)
            cap.release()
        return None

    def _run(self) -> None:
        try:
            import cv2
        except ImportError as e:
            self._status.last_error = f"opencv not installed: {e}"
            logger.warning("camera_worker_opencv_missing", error=str(e))
            return

        cap = None
        try:
            # 1) Only try GStreamer IPC when the daemon is reachable — avoids
            #    a multi-second hang when GST env vars are present but the
            #    daemon is down (the gi/GStreamer .pth double-prepend can freeze
            #    the import in the uvicorn process context).
            daemon_up = False
            try:
                import urllib.request as _ur
                _ur.urlopen(f"{_REACHY_API_URL}/health", timeout=0.4).close()
                daemon_up = True
            except Exception:
                pass

            if daemon_up:
                cap = self._open_gstreamer()
            # 2) Fall back to directly opening the USB device (only usable
            #    if the daemon has released it, which _open_capture does).
            if cap is None:
                cap = self._open_capture()
            if cap is None:
                self._status.last_error = f"could not open camera device {self._status.device_index}"
                logger.warning("camera_worker_open_failed", device=self._status.device_index)
                return

            self._status.active = True
            self._status.last_error = None
            first_ok, first_frame = cap.read()
            if first_ok and first_frame is not None:
                self._status.height, self._status.width = first_frame.shape[:2]
            else:
                self._status.width = int(getattr(cap, "get", lambda *_: 0)(cv2.CAP_PROP_FRAME_WIDTH) or _DEFAULT_WIDTH)
                self._status.height = int(getattr(cap, "get", lambda *_: 0)(cv2.CAP_PROP_FRAME_HEIGHT) or _DEFAULT_HEIGHT)
            logger.info(
                "camera_worker_started",
                backend=self._status.backend,
                device=self._status.device_index,
                width=self._status.width,
                height=self._status.height,
            )

            frame_times: list[float] = []
            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), _DEFAULT_JPEG_Q]
            consecutive_read_failures = 0
            max_consecutive_failures = 40  # ~2s at 20fps polling

            # Re-encode the probe frame so consumers see something immediately.
            if first_ok and first_frame is not None:
                ok_enc, buf = cv2.imencode(".jpg", first_frame, encode_params)
                if ok_enc:
                    with self._latest_lock:
                        self._latest_jpeg = bytes(buf)
                        self._status.last_frame_ts = time.time()
                    self._frame_event.set()

            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    consecutive_read_failures += 1
                    cap_error = str(getattr(cap, "last_error", "") or "")
                    gstreamer_invalid_arg = (
                        self._status.backend == "gstreamer_ipc"
                        and ("Invalid argument" in cap_error or "Errno 22" in cap_error)
                    )
                    if consecutive_read_failures >= max_consecutive_failures:
                        self._status.last_error = (
                            f"camera stopped producing frames after {consecutive_read_failures} "
                            f"consecutive read failures (backend={self._status.backend})"
                        )
                        logger.warning(
                            "camera_worker_read_exhausted",
                            backend=self._status.backend,
                            failures=consecutive_read_failures,
                        )
                        if self._status.backend == "gstreamer_ipc":
                            fallback = self._restart_with_direct_capture(cap, cv2, reason=self._status.last_error)
                            if fallback is not None:
                                cap = fallback
                                consecutive_read_failures = 0
                                continue
                        break
                    if gstreamer_invalid_arg:
                        fallback = self._restart_with_direct_capture(cap, cv2, reason=cap_error)
                        if fallback is not None:
                            cap = fallback
                            consecutive_read_failures = 0
                            continue
                    time.sleep(0.05)
                    continue
                consecutive_read_failures = 0

                ok, buf = cv2.imencode(".jpg", frame, encode_params)
                if not ok:
                    continue
                jpeg = bytes(buf)
                now = time.time()
                with self._latest_lock:
                    self._latest_jpeg = jpeg
                    self._status.last_frame_ts = now
                self._frame_event.set()

                frame_times.append(now)
                frame_times = [t for t in frame_times if now - t < 2.0]
                if len(frame_times) >= 2:
                    window = frame_times[-1] - frame_times[0]
                    if window > 0:
                        self._status.fps = (len(frame_times) - 1) / window

                # Idle shutdown: if nobody has asked for a frame in a while,
                # release the device so the daemon / other tools can use it.
                if (
                    self._status.consumers == 0
                    and self._last_consumer_ts
                    and (now - self._last_consumer_ts) > _IDLE_SHUTDOWN_S
                ):
                    logger.info("camera_worker_idle_shutdown", idle_s=_IDLE_SHUTDOWN_S)
                    break
        except Exception as e:
            self._status.last_error = str(e)
            logger.warning("camera_worker_crashed", error=str(e))
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            self._status.active = False
            self._status.fps = 0.0
            self._frame_event.set()
            logger.info("camera_worker_stopped")

    def _restart_with_direct_capture(self, current_cap, cv2, *, reason: str):
        """Fallback when the gstreamer IPC reader dies mid-session."""
        logger.warning("camera_worker_gstreamer_fallback", reason=reason)
        try:
            current_cap.release()
        except Exception:
            pass
        fallback = self._open_capture()
        if fallback is None:
            self._status.last_error = (
                "gstreamer_ipc failed and direct camera fallback could not open"
                + (f": {reason}" if reason else "")
            )
            return None
        ok, frame = fallback.read()
        if ok and frame is not None:
            self._status.height, self._status.width = frame.shape[:2]
            ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), _DEFAULT_JPEG_Q])
            if ok_enc:
                with self._latest_lock:
                    self._latest_jpeg = bytes(buf)
                    self._status.last_frame_ts = time.time()
                self._frame_event.set()
        self._status.active = True
        self._status.last_error = None
        logger.info("camera_worker_direct_fallback_started", backend=self._status.backend)
        return fallback


def list_devices() -> list[dict]:
    """
    Enumerate available camera devices with names and OpenCV indices.

    Uses WinRT DeviceInformation (MSMF order) to get names, then probes
    each index with OpenCV to confirm readability and get native resolution.
    Adds an `is_reachy` flag for the robot body camera.
    """
    import json
    import subprocess

    try:
        import cv2
    except ImportError:
        return []

    # --- Step 1: get ordered device names from Windows (WinRT = MSMF order) ---
    names: list[str] = []
    try:
        script = (
            "$ErrorActionPreference = 'SilentlyContinue';"
            "Add-Type -AssemblyName 'System.Runtime.WindowsRuntime';"
            "$t = [Windows.Devices.Enumeration.DeviceInformation];"
            "$devs = $t::FindAllAsync("
            "[Windows.Devices.Enumeration.DeviceClass]::VideoCapture"
            ").GetAwaiter().GetResult();"
            "$devs | ForEach-Object { $_.Name } | ConvertTo-Json -Compress"
        )
        r = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, timeout=8,
        )
        raw = (r.stdout or "").strip()
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                parsed = [parsed]
            names = [str(n) for n in parsed]
    except Exception as e:
        logger.debug("camera_list_names_failed", error=str(e)[:120])

    # Fallback: try PnP device class "Camera"
    if not names:
        try:
            r2 = subprocess.run(
                ["powershell", "-Command",
                 "Get-PnpDevice -Class Camera -Status OK | Select-Object -ExpandProperty FriendlyName | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=6,
            )
            raw2 = (r2.stdout or "").strip()
            if raw2:
                parsed2 = json.loads(raw2)
                if isinstance(parsed2, str):
                    parsed2 = [parsed2]
                names = [str(n) for n in parsed2]
        except Exception as e2:
            logger.debug("camera_list_pnp_failed", error=str(e2)[:120])

    # --- Step 2: probe OpenCV indices to confirm availability ---
    devices: list[dict] = []
    probe_count = max(len(names), 4)  # always probe at least 4 slots
    for i in range(probe_count):
        name = names[i] if i < len(names) else f"Camera {i}"
        available = False
        width = height = 0

        for backend, bname in [(cv2.CAP_DSHOW, "dshow"), (cv2.CAP_MSMF, "msmf")]:
            try:
                cap = cv2.VideoCapture(i, backend)
            except Exception:
                continue
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                continue
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            ok, _ = cap.read()
            cap.release()
            if ok:
                available = True
                width, height = w, h
                break

        is_reachy = any(kw in name.lower() for kw in _REACHY_NAME_KEYWORDS)
        devices.append(
            {
                "index": i,
                "name": name,
                "available": available,
                "width": width,
                "height": height,
                "is_reachy": is_reachy,
            }
        )

    return devices


def _find_reachy_device_index() -> int:
    """
    Return the OpenCV device index for the Reachy body camera.

    Strategy:
    1. If ZERO_REACHY_CAMERA_DEVICE is set to a non-negative value, trust it (no enumeration).
    2. Otherwise use the module-level cache if already resolved this session.
    3. Else enumerate devices, find one named "Reachy Mini Camera", cache it.
    4. Fall back to first available device, then index 0.
    """
    global _resolved_device_index

    if _DEFAULT_INDEX >= 0:
        return _DEFAULT_INDEX

    if _resolved_device_index is not None:
        return _resolved_device_index

    try:
        devs = list_devices()
        for d in devs:
            if d.get("is_reachy") and d.get("available"):
                logger.info("camera_reachy_autodetected", index=d["index"], name=d["name"])
                _resolved_device_index = d["index"]
                return d["index"]
        for d in devs:
            if d.get("available"):
                logger.info("camera_reachy_fallback_first_available", index=d["index"], name=d["name"])
                _resolved_device_index = d["index"]
                return d["index"]
    except Exception as e:
        logger.warning("camera_reachy_detection_failed", error=str(e)[:120])

    logger.info("camera_reachy_fallback_index_0")
    _resolved_device_index = 0
    return 0


def get_camera_worker() -> "CameraWorker":
    return CameraWorker.instance()
