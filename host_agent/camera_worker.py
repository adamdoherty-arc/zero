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
_DEFAULT_INDEX = int(os.getenv("ZERO_REACHY_CAMERA_DEVICE", "0"))
_DEFAULT_WIDTH = int(os.getenv("ZERO_REACHY_CAMERA_WIDTH", "1280"))
_DEFAULT_HEIGHT = int(os.getenv("ZERO_REACHY_CAMERA_HEIGHT", "720"))
_DEFAULT_FPS = int(os.getenv("ZERO_REACHY_CAMERA_FPS", "15"))
_DEFAULT_JPEG_Q = int(os.getenv("ZERO_REACHY_CAMERA_JPEG_QUALITY", "80"))
_IDLE_SHUTDOWN_S = float(os.getenv("ZERO_REACHY_CAMERA_IDLE_SHUTDOWN_S", "15"))

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
        with urllib.request.urlopen(req, timeout=2.0) as resp:
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

        backends = [
            (cv2.CAP_DSHOW, "dshow"),
            (cv2.CAP_MSMF, "msmf"),
            (cv2.CAP_ANY, "any"),
        ]
        for backend, name in backends:
            cap = cv2.VideoCapture(_DEFAULT_INDEX, backend)
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
            # 1) Try the daemon's IPC pipe first — zero-contention path.
            cap = self._open_gstreamer()
            # 2) Fall back to directly opening the USB device (only usable
            #    if the daemon has released it, which _open_capture does).
            if cap is None:
                cap = self._open_capture()
            if cap is None:
                self._status.last_error = f"could not open camera device {_DEFAULT_INDEX}"
                logger.warning("camera_worker_open_failed", device=_DEFAULT_INDEX)
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
                device=_DEFAULT_INDEX,
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


def get_camera_worker() -> CameraWorker:
    return CameraWorker.instance()
