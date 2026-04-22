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
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("reachy_daemon_launcher")


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
    ap.add_argument("--dataset-refresh-hours", type=float, default=24.0,
                    help="How often to refresh HF datasets (0 = never)")
    args = ap.parse_args()

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
        autostart=True,
        desktop_app_daemon=False,      # we are NOT wrapped by Tauri
        preload_datasets=not args.no_preload,
        dataset_update_interval_hours=args.dataset_refresh_hours,
        wake_up_on_start=True,
        goto_sleep_on_stop=True,
    )

    logger.info(
        "Starting Reachy Mini daemon  port=%d  mockup=%s  preload=%s",
        args.port, args.mockup_sim, not args.no_preload,
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
