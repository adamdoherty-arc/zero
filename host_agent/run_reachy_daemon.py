"""
Standalone Reachy Mini daemon launcher — the headless equivalent of the
Tauri desktop app.

The Pollen Robotics Reachy Mini Desktop App is just a GUI wrapper around
the Python FastAPI server at ``reachy_mini.daemon.app.main``. When that
GUI crashes (which happens if a lazy dataset download hangs, or when an
untrusted recorded-move references an unknown clip), the whole process
dies and the user has to reopen the app.

Running the same daemon headless has three wins:

1. **No GUI lock** — restart is ``python run_reachy_daemon.py`` instead of
   clicking a taskbar icon.
2. **Dataset preload** — we pass ``preload_datasets=True`` so the emotions
   + dances libraries download on startup instead of on first play (which
   is what caused the crash during Zero's first dance test).
3. **Clean logging** — logs go to stdout/file, easy to tail.

Zero's backend is unaware of which daemon is serving :8000, so this is a
drop-in replacement: stop the desktop app, run this script, everything
keeps working.

Usage (after `pip install -r requirements.txt` in host_agent/.venv):

    python run_reachy_daemon.py
    python run_reachy_daemon.py --no-preload     # skip dataset preload
    python run_reachy_daemon.py --port 8000      # default
    python run_reachy_daemon.py --mockup-sim     # fake hardware for dev

Ctrl+C stops it. On hardware, the daemon auto-finds the USB serial port.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import subprocess
import sys
from pathlib import Path


def _restore_pythonw_stdio() -> None:
    """
    pythonw.exe sets sys.stdout/stderr to None because it has no console,
    which makes ``logging`` and ``print`` silently drop every line. The
    supervisor's reader thread then sees nothing and the watchdog kills
    the daemon thinking it crashed.

    Popen redirects fd 1 and fd 2 to a real pipe before exec, so the file
    descriptors *are* valid; we just need to give Python file objects on
    top of them. After this, logging + print + any subprocess that
    inherits stdout/stderr (uvicorn, reachy_mini SDK, GStreamer, etc) all
    write to the pipe and the supervisor captures them as normal.
    """
    if sys.stdout is None:
        try:
            sys.stdout = io.TextIOWrapper(
                os.fdopen(1, "wb", buffering=0), encoding="utf-8",
                line_buffering=True, write_through=True,
            )
        except Exception:
            sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        try:
            sys.stderr = io.TextIOWrapper(
                os.fdopen(2, "wb", buffering=0), encoding="utf-8",
                line_buffering=True, write_through=True,
            )
        except Exception:
            sys.stderr = open(os.devnull, "w")


_restore_pythonw_stdio()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("reachy_daemon_launcher")


def _suppress_windows_console_flashes() -> None:
    """
    Monkey-patch ``subprocess.Popen`` on Windows so every child the daemon
    (and its dependencies — reachy_mini SDK, GStreamer plugin scanner,
    huggingface_hub, ffprobe, git-lfs, pyusb helpers) spawns gets
    ``CREATE_NO_WINDOW`` automatically.

    The supervisor runs the daemon with ``DETACHED_PROCESS`` (so the daemon
    has no console of its own) — but that means any *grandchild* spawned by
    the daemon would otherwise get a fresh visible console allocated by
    Windows. This patch fixes that at the source by adding the flag to
    every ``subprocess.Popen`` call inside this process tree.

    Safe no-op on non-Windows.
    """
    if os.name != "nt":
        return
    _orig_init = subprocess.Popen.__init__
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    def _patched_init(self, *args, **kwargs):
        # Don't override caller's choice if they explicitly asked for a new
        # console — only add CREATE_NO_WINDOW when they haven't picked any
        # console-shape flag of their own.
        cf = kwargs.get("creationflags", 0)
        if not (cf & (subprocess.CREATE_NEW_CONSOLE | _NO_WINDOW)):  # type: ignore[attr-defined]
            kwargs["creationflags"] = cf | _NO_WINDOW
        return _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init  # type: ignore[method-assign]


_suppress_windows_console_flashes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--port", type=int, default=8000, help="Daemon FastAPI port (default 8000)")
    ap.add_argument("--host", type=str, default="0.0.0.0", help="Daemon bind host")
    ap.add_argument("--log-level", type=str, default="INFO")
    ap.add_argument("--serialport", type=str, default="auto",
                    help='Serial port or "auto" (default). Use "auto" unless you have multiple Reachys.')
    ap.add_argument("--mockup-sim", action="store_true",
                    help="Fake hardware for development (no USB needed)")
    ap.add_argument("--no-preload", action="store_true",
                    help="Skip preloading emotion/dance datasets on startup")
    ap.add_argument("--no-media", action="store_true",
                    help="Skip the WebRTC media server (webcam, audio stream). "
                         "Use on machines without a compatible webcam — the "
                         "reachy_mini media server otherwise fails with a "
                         "gst-stream-error and spams logs.")
    ap.add_argument("--dataset-refresh-hours", type=float, default=24.0,
                    help="How often to refresh HF datasets (0 = never)")
    ap.add_argument("--wake-on-start", action="store_true",
                    help="Play the wake-up animation when the daemon spawns. "
                         "Default OFF — the supervisor restarts the daemon on "
                         "any blip and we don't want the robot rocking through "
                         "wake-up + alive-idle every time. Wake up explicitly "
                         "from the UI when you want to interact.")
    ap.add_argument("--hardware-config-filepath", type=str, default=None,
                    help="Path to a custom Reachy Mini hardware_config.yaml. "
                         "Use this to omit a faulted motor from the daemon's "
                         "enumeration without editing the SDK install. If not "
                         "provided, run_reachy_daemon.py auto-detects "
                         "host_agent/hardware_config.local.yaml when present "
                         "and falls back to the SDK default otherwise.")
    args = ap.parse_args()

    # Auto-detect the local override sitting next to this launcher. Lets
    # operators ship a per-machine hardware override (e.g. with a faulted
    # motor removed) without changing CLI invocations or env vars.
    hardware_config_filepath = args.hardware_config_filepath
    if hardware_config_filepath is None:
        local_override = Path(__file__).parent / "hardware_config.local.yaml"
        if local_override.exists():
            hardware_config_filepath = str(local_override)
            logger.info(
                "Using local hardware override at %s (auto-detected)",
                hardware_config_filepath,
            )

    try:
        # Import lazily so an import error produces a useful hint.
        import uvicorn  # type: ignore[import-not-found]
        from reachy_mini.daemon.app.main import Args, create_app  # type: ignore[import-not-found]
    except ImportError as e:
        logger.error("Missing dependency: %s", e)
        logger.error("Install host_agent deps first:")
        logger.error("    cd host_agent && .venv\\Scripts\\pip install -r requirements.txt")
        return 2

    daemon_args = Args(
        log_level=args.log_level,
        fastapi_host=args.host,
        fastapi_port=args.port,
        serialport=args.serialport,
        mockup_sim=args.mockup_sim,
        sim=False,
        headless=False,
        no_media=args.no_media,
        autostart=True,
        desktop_app_daemon=False,      # we are NOT wrapped by Tauri
        preload_datasets=not args.no_preload,
        dataset_update_interval_hours=args.dataset_refresh_hours,
        wake_up_on_start=args.wake_on_start,
        hardware_config_filepath=hardware_config_filepath,
        goto_sleep_on_stop=True,
    )

    logger.info(
        "Starting Reachy Mini daemon  port=%d  mockup=%s  preload=%s  media=%s  wake_on_start=%s",
        args.port, args.mockup_sim, not args.no_preload, not args.no_media, args.wake_on_start,
    )
    app = create_app(daemon_args)

    # The SDK's own lifespan handles backend startup + shutdown. We just run uvicorn.
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
        workers=1,
        reload=False,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
