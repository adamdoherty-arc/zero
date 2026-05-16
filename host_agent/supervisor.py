"""
Reachy daemon supervisor — host_agent-side process manager for the
``run_reachy_daemon.py`` launcher.

Owns the subprocess lifecycle (start/stop/restart), tails stdout into a ring
buffer + rotating log file, and exposes diagnostics about the Windows audio /
USB / motor state so the UI can tell the user *why* Reachy is offline.

Daemon lifecycle (start / stop / restart) is now triggered exclusively from
the UI — there is no auto-restart watchdog. An atexit hook reaps the daemon
subprocess if host_agent exits unexpectedly so :8000 doesn't leak.

Meant to be instantiated once at host_agent startup and reused.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import structlog

logger = structlog.get_logger()


# --- paths --------------------------------------------------------------

_HOST_AGENT_DIR = Path(__file__).parent
_LAUNCHER_SCRIPT = _HOST_AGENT_DIR / "run_reachy_daemon.py"
# pythonw.exe is the Windows-subsystem variant of Python. It allocates no
# console of its own, which is the only way to suppress the Windows
# Terminal tab that pops up under Windows 11 (default console host = WT)
# whenever a console-subsystem app is spawned — STARTUPINFO + SW_HIDE,
# DETACHED_PROCESS, and CREATE_NO_WINDOW all *fail* to hide the tab
# because WT shows it regardless. The cost: pythonw leaves
# sys.stdout/stderr as None unless explicitly restored. The launcher
# (run_reachy_daemon.py) re-binds sys.stdout/stderr to fd 1/2 first thing
# so logging still flows out through the pipe the supervisor sets up.
_VENV_PYTHON = _HOST_AGENT_DIR / ".venv" / "Scripts" / "pythonw.exe"

# The Pollen Reachy Mini Control desktop app ships its own Python 3.12 venv
# with reachy_mini pre-installed. When host_agent's own venv is on a Python
# version incompatible with reachy_mini's native deps (libusb_package ships
# wheels only through py3.12), we fall back to the desktop app's venv — it
# has the same SDK that run_reachy_daemon.py needs.
_REACHY_CONTROL_VENV_CANDIDATES = (
    Path(os.getenv("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"))
    / "Reachy Mini Control" / ".venv" / "Scripts" / "pythonw.exe",
    Path(os.getenv("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"))
    / "Reachy Mini Control" / "apps_venv" / "Scripts" / "pythonw.exe",
)

_LOG_DIR = _HOST_AGENT_DIR / "logs"
_STATE_DIR = _HOST_AGENT_DIR / "state"
# Legacy state file from the deleted auto-restart watchdog. Cleaned up on
# first init so it doesn't confuse future debugging.
_LEGACY_WATCHDOG_STATE_PATH = _STATE_DIR / "watchdog.json"

_LOG_DIR.mkdir(parents=True, exist_ok=True)
_STATE_DIR.mkdir(parents=True, exist_ok=True)


# --- constants ---------------------------------------------------------

DAEMON_URL = os.getenv("REACHY_API_URL", "http://localhost:8000").rstrip("/")
# Timeout for the daemon-up probe used by diagnostics() and the recovery
# helpers. Keep generous: a status call that does two sequential HTTP
# requests can exceed 3 s under motor-fault load and false-positive a
# "host_agent isn't responding" alert in the UI.
DAEMON_PROBE_TIMEOUT_S = 25.0
# After CTRL_BREAK the daemon's child uvicorn worker, motor serial thread,
# and the COM port handle take a moment to release. Spawning immediately
# races the previous owner and the new daemon dies with exit 1 (COM3 busy).
RESTART_COOLDOWN_S = 8.0
SPAWN_RETRY_DELAYS_S = (0.0, 4.0, 8.0)
RING_BUFFER_LINES = 500
RESTART_HISTORY_LIMIT = 20
# Daemon log files were observed at 132 MB in a single day when the robot was
# unplugged and the daemon spam-logged motor failures. Rotate at 50 MB; keep
# one prior segment as <name>.1 (older segments are dropped).
LOG_MAX_BYTES = 50 * 1024 * 1024


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _daemon_env_args() -> list[str]:
    raw = os.getenv("ZERO_REACHY_DAEMON_ARGS")
    if raw is None or not raw.strip():
        return ["--no-preload", "--no-media"]
    return raw.split()


def _safe_log(log_fn, *args, **kwargs) -> None:
    try:
        log_fn(*args, **kwargs)
    except Exception:
        pass


def _console_python_for(python_path: Path) -> Path:
    if python_path.name.lower() == "pythonw.exe":
        console_python = python_path.with_name("python.exe")
        if console_python.exists():
            return console_python
    return python_path


def _version_sort_key(version: str | None) -> tuple[int, ...]:
    if not version:
        return (0,)
    parts = [int(part) for part in re.findall(r"\d+", version)]
    return tuple(parts) if parts else (0,)


def _isolated_python_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
        "__PYVENV_LAUNCHER__",
    ):
        env.pop(key, None)
    return env


def _reachy_mini_version(python_path: Path) -> str | None:
    """Return the installed reachy_mini version without importing the SDK."""
    if not python_path.exists():
        return None
    console_python = _console_python_for(python_path)
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
    try:
        result = subprocess.run(
            [
                str(console_python),
                "-c",
                (
                    "import importlib.metadata as m; "
                    "print(m.version('reachy_mini'))"
                ),
            ],
            cwd=str(_HOST_AGENT_DIR),
            capture_output=True,
            text=True,
            timeout=5.0,
            env=_isolated_python_env(),
            creationflags=creationflags,
            startupinfo=startupinfo,
            check=False,
        )
    except Exception as e:
        _safe_log(
            logger.warning,
            "reachy_python_version_probe_failed",
            python=str(python_path),
            error=str(e),
        )
        return None
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:500]
        _safe_log(
            logger.warning,
            "reachy_python_version_probe_unavailable",
            python=str(python_path),
            stderr=stderr,
        )
        return None
    version = (result.stdout or "").strip().splitlines()[-1:]
    return version[0].strip() if version else None


def _select_reachy_python_candidate(
    candidates: list[Path],
    version_lookup: Callable[[Path], str | None] = _reachy_mini_version,
) -> tuple[Path, str | None] | None:
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return None

    best: tuple[tuple[int, ...], int, Path, str] | None = None
    for index, candidate in enumerate(existing):
        version = version_lookup(candidate)
        if not version:
            continue
        ranked = (_version_sort_key(version), -index, candidate, version)
        if best is None or ranked[:2] > best[:2]:
            best = ranked

    if best is not None:
        _, _, candidate, version = best
        return candidate, version

    return existing[0], None


class DaemonSupervisor:
    """Manages the Reachy Mini daemon subprocess on the Windows host."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._ring: deque[str] = deque(maxlen=RING_BUFFER_LINES)
        self._log_fh = None
        self._child_stdout_fh = None
        self._log_path: Path | None = None
        self._log_bytes_written = 0
        self._started_at: datetime | None = None
        self._last_exit_code: int | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = asyncio.Lock()

        self._restart_history: deque[dict[str, Any]] = deque(
            maxlen=RESTART_HISTORY_LIMIT
        )

        # One-shot cleanup of the legacy auto-restart watchdog state file.
        # The whole watchdog was removed when daemon lifecycle moved into
        # the UI; the stale file would only confuse future debugging.
        try:
            if _LEGACY_WATCHDOG_STATE_PATH.exists():
                _LEGACY_WATCHDOG_STATE_PATH.unlink()
        except Exception:
            pass

        # Ensure the daemon subprocess is reaped if host_agent exits without
        # going through the normal /daemon/stop path. Without this, killing
        # the host_agent console window leaks a Reachy daemon process that
        # owns :8000 and motor COM port — the symptom the user reported as
        # "pid exists but :8000 is not responding."
        import atexit
        atexit.register(self._atexit_stop)

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------

    def _python_executable(self) -> str:
        """
        Pick the Python that can actually spawn the daemon. Precedence:
        1. ``ZERO_REACHY_PYTHON`` env override.
        2. Newest installed ``reachy_mini`` SDK across known venvs.
        3. First known venv if version probing is unavailable.
        4. Bare ``sys.executable`` as a last resort.

        Version probing uses ``importlib.metadata`` only, not a cold SDK import,
        so it stays fast while still letting the updated Reachy desktop app
        SDK replace Zero's older bundled SDK.
        """
        override = os.getenv("ZERO_REACHY_PYTHON")
        if override and Path(override).exists():
            return override

        selected = _select_reachy_python_candidate(
            [_VENV_PYTHON, *_REACHY_CONTROL_VENV_CANDIDATES]
        )
        if selected is not None:
            python_path, version = selected
            _safe_log(
                logger.info,
                "reachy_python_selected",
                python=str(python_path),
                reachy_mini_version=version,
            )
            return str(python_path)

        return sys.executable

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def start(self, extra_args: list[str] | None = None) -> dict[str, Any]:
        async with self._lock:
            if self.is_running():
                return {
                    "running": True,
                    "already_running": True,
                    "pid": self._proc.pid,  # type: ignore[union-attr]
                }
            if await asyncio.to_thread(_probe_daemon_up_sync):
                return {
                    "running": True,
                    "already_running": True,
                    "pid": await asyncio.to_thread(_find_daemon_listen_pid),
                    "adopted": True,
            }
            orphan_pid = await asyncio.to_thread(_find_daemon_listen_pid)
            if orphan_pid is not None:
                _safe_log(logger.warning, "daemon_port_held_by_unhealthy_process", pid=orphan_pid)
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    _kill_process_tree,
                    orphan_pid,
                )
                await asyncio.sleep(RESTART_COOLDOWN_S)
            return await self._start_locked(extra_args or [])

    async def _start_locked(self, extra_args: list[str]) -> dict[str, Any]:
        if not _LAUNCHER_SCRIPT.exists():
            raise RuntimeError(f"launcher script missing: {_LAUNCHER_SCRIPT}")

        today = datetime.now().strftime("%Y%m%d")
        log_path = _LOG_DIR / f"reachy-daemon-{today}.log"
        try:
            self._log_fh = open(log_path, "a", encoding="utf-8", buffering=1)
            self._log_bytes_written = log_path.stat().st_size if log_path.exists() else 0
        except Exception as e:
            _safe_log(logger.warning, "daemon_log_open_failed", path=str(log_path), error=str(e))
            self._log_fh = None
            self._log_bytes_written = 0
        self._log_path = log_path

        # Default args from environment: ZERO_REACHY_DAEMON_ARGS="--mockup-sim --no-preload".
        # If the hidden scheduled-task runner loses the env, keep the daemon
        # on the same safe no-media path used by auto-restart.bat.
        env_args = _daemon_env_args()
        # -u forces unbuffered stdout so our reader thread sees output immediately
        # (Python pipes stdout to a PIPE by default, which buffers heavily).
        cmd = [
            self._python_executable(),
            "-u",
            str(_LAUNCHER_SCRIPT),
            *env_args,
            *extra_args,
        ]
        creationflags = 0
        if os.name == "nt":
            # CREATE_NEW_PROCESS_GROUP lets us send CTRL_BREAK_EVENT to the
            # child. CREATE_NEW_PROCESS_GROUP alone does NOT block CTRL_CLOSE_EVENT
            # (window-close), which was killing the daemon when host_agent's
            # console window closed — Fortran runtime in numpy/scipy/MKL traps
            # the close and aborts. DETACHED_PROCESS + CREATE_NO_WINDOW fully
            # detaches from any inherited console so close events can't reach.
            #
            # The launcher (run_reachy_daemon.py) installs a subprocess
            # monkey-patch on Windows that adds CREATE_NO_WINDOW to every
            # child the daemon spawns — that's what suppresses the GStreamer
            # / ffprobe / git-lfs terminal-flash storm without needing the
            # daemon itself to inherit a hidden console.
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )

        # Windows 11 with Windows Terminal as the default console host
        # flashes a WT tab whenever a console-subsystem app (python.exe)
        # is spawned, even with DETACHED_PROCESS + CREATE_NO_WINDOW.
        # STARTUPINFO with STARTF_USESHOWWINDOW + SW_HIDE explicitly tells
        # ConHost (and WT, which respects this) NOT to surface a window
        # for this child. The flag is also propagated to subprocesses the
        # daemon itself spawns via the launcher's monkey-patch.
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]

        def _spawn_with_options(
            flags: int,
            proc_startupinfo: subprocess.STARTUPINFO | None,
            stdout_target: Any = subprocess.PIPE,
        ) -> subprocess.Popen:
            # Byte-mode pipe + bufsize=0. On Windows, text=True with bufsize=1
            # combined with `for line in proc.stdout` exhibited a read-ahead
            # stall where the reader thread never got lines until the pipe
            # closed. Raw bytes + explicit readline() fixes it.
            return subprocess.Popen(
                cmd,
                cwd=str(_HOST_AGENT_DIR),
                stdout=stdout_target,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=_isolated_python_env(),
                creationflags=flags,
                startupinfo=proc_startupinfo,
                bufsize=0,
            )

        try:
            fallback_flags = 0
            if os.name == "nt":
                fallback_flags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.CREATE_NO_WINDOW
                )
            attempts: list[tuple[str, int, subprocess.STARTUPINFO | None]] = [
                ("preferred", creationflags, startupinfo),
                ("compatible_flags", fallback_flags, startupinfo),
                ("no_flags", 0, startupinfo),
            ]
            if os.name == "nt":
                # Under the hidden scheduled-task runner, Windows can reject
                # STARTUPINFO + redirected stdio with WinError 22 even though
                # the same flags work from an interactive console. Retry
                # without STARTUPINFO before declaring the daemon unrecoverable.
                attempts.extend(
                    [
                        ("preferred_no_startupinfo", creationflags, None),
                        ("compatible_flags_no_startupinfo", fallback_flags, None),
                        ("no_flags_no_startupinfo", 0, None),
                    ]
                )

            last_spawn_error: OSError | None = None
            for retry_index, delay_s in enumerate(SPAWN_RETRY_DELAYS_S):
                if delay_s > 0:
                    time.sleep(delay_s)
                for attempt_name, flags, attempt_startupinfo in attempts:
                    try:
                        self._proc = _spawn_with_options(flags, attempt_startupinfo)
                        if last_spawn_error is not None:
                            _safe_log(
                                logger.warning,
                                "daemon_spawn_recovered_with_fallback",
                                attempt=attempt_name,
                                retry=retry_index,
                            )
                        break
                    except OSError as e:
                        if os.name != "nt" or getattr(e, "errno", None) != 22:
                            raise
                        last_spawn_error = e
                        self._append_line(
                            "--- daemon spawn attempt failed "
                            f"attempt={attempt_name} retry={retry_index} error={e} ---"
                        )
                        _safe_log(
                            logger.warning,
                            "daemon_spawn_retrying_after_invalid_argument",
                            attempt=attempt_name,
                            retry=retry_index,
                            error=str(e),
                        )
                if self._proc is not None:
                    break
            if self._proc is None and os.name == "nt" and last_spawn_error is not None:
                # Hidden scheduled-task runs can reject inherited/redirected pipe
                # handles with WinError 22 even after flag fallbacks. As a final
                # recovery path, attach the child directly to the rotating daemon
                # log file. We lose the in-memory ring for that child, but
                # /daemon/logs still reads the same file and the daemon comes up.
                child_stdout = open(log_path, "ab", buffering=0)
                for retry_index, delay_s in enumerate(SPAWN_RETRY_DELAYS_S):
                    if delay_s > 0:
                        time.sleep(delay_s)
                    for attempt_name, flags, attempt_startupinfo in attempts:
                        try:
                            self._proc = _spawn_with_options(
                                flags,
                                attempt_startupinfo,
                                stdout_target=child_stdout,
                            )
                            self._child_stdout_fh = child_stdout
                            _safe_log(
                                logger.warning,
                                "daemon_spawn_recovered_with_log_file_stdout",
                                attempt=attempt_name,
                                retry=retry_index,
                            )
                            break
                        except OSError as e:
                            if os.name != "nt" or getattr(e, "errno", None) != 22:
                                child_stdout.close()
                                raise
                            last_spawn_error = e
                            self._append_line(
                                "--- daemon log-file spawn attempt failed "
                                f"attempt={attempt_name} retry={retry_index} error={e} ---"
                            )
                    if self._proc is not None:
                        break
                if self._proc is None:
                    child_stdout.close()
            if self._proc is None:
                assert last_spawn_error is not None
                raise last_spawn_error
        except Exception as e:
            self._log_fh and self._log_fh.close()
            self._log_fh = None
            _safe_log(logger.error, "daemon_spawn_failed", error=str(e))
            raise

        self._started_at = datetime.now(timezone.utc)
        self._last_exit_code = None
        self._last_extra_args = list(extra_args)
        self._ring.clear()
        self._append_line(
            f"--- daemon spawned pid={self._proc.pid} args={cmd[2:]!r} at {_utcnow_iso()} ---"
        )

        if self._proc.stdout is not None:
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                args=(self._proc,),
                daemon=True,
                name="reachy-daemon-reader",
            )
            try:
                self._reader_thread.start()
            except Exception as e:
                self._reader_thread = None
                self._append_line(
                    f"--- daemon reader thread unavailable; continuing without ring tail: {e} ---"
                )
                _safe_log(
                    logger.warning,
                    "daemon_reader_thread_start_failed",
                    error=str(e),
                )
        else:
            self._reader_thread = None
            self._append_line(
                "--- daemon stdout is attached directly to log file "
                "(pipe unavailable in hidden runner) ---"
            )

        _safe_log(logger.info, "reachy_daemon_spawned", pid=self._proc.pid, log=str(log_path))
        return {"running": True, "pid": self._proc.pid, "log_path": str(log_path)}

    async def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        async with self._lock:
            return await self._stop_locked(timeout)

    @property
    def last_extra_args(self) -> list[str]:
        return list(getattr(self, "_last_extra_args", []))

    async def _stop_locked(self, timeout: float) -> dict[str, Any]:
        if not self.is_running():
            orphan_pid = _find_daemon_listen_pid()
            if orphan_pid is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _kill_process_tree, orphan_pid)
                self._append_line(
                    f"--- daemon orphan stopped pid={orphan_pid} at {_utcnow_iso()} ---"
                )
                self._last_exit_code = None
                self._proc = None
                self._started_at = None
                _safe_log(logger.info, "reachy_daemon_orphan_stopped", pid=orphan_pid)
                return {
                    "running": False,
                    "was_running": True,
                    "orphan_pid": orphan_pid,
                }
            return {"running": False, "was_running": False}

        proc = self._proc
        assert proc is not None
        pid = proc.pid

        try:
            proc.terminate()
        except Exception as e:
            _safe_log(logger.warning, "daemon_terminate_failed", pid=pid, error=str(e))

        # Wait for exit off the event loop thread.
        loop = asyncio.get_running_loop()
        try:
            code = await asyncio.wait_for(
                loop.run_in_executor(None, proc.wait),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            _safe_log(logger.warning, "daemon_terminate_timeout", pid=pid)
            try:
                proc.kill()
            except Exception:
                pass
            code = await loop.run_in_executor(None, proc.wait)

        # The daemon launches its own uvicorn worker as a child process and
        # the reachy_mini media_server spawns GStreamer plugin scanners. When
        # the parent dies via CTRL_BREAK these children outlive it and keep
        # holding COM3 + the WASAPI capture handle. Force-kill the whole tree.
        if os.name == "nt":
            await loop.run_in_executor(None, _kill_process_tree, pid)

        self._last_exit_code = code
        self._append_line(f"--- daemon exited pid={pid} code={code} at {_utcnow_iso()} ---")

        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None
        if self._child_stdout_fh is not None:
            try:
                self._child_stdout_fh.close()
            except Exception:
                pass
            self._child_stdout_fh = None

        self._proc = None
        self._started_at = None
        _safe_log(logger.info, "reachy_daemon_stopped", pid=pid, code=code)
        return {"running": False, "was_running": True, "exit_code": code}

    async def restart(
        self,
        reason: str = "manual",
        extra_args: list[str] | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            healthy = _probe_daemon_up_sync()
            orphan_pid = _find_daemon_listen_pid()
            was_running = self.is_running() or healthy or orphan_pid is not None
            if self.is_running() or healthy:
                await self._stop_locked(5.0)
                # Let the previous daemon's COM3 handle, GStreamer pipeline,
                # and uvicorn child fully release before respawning.
                await asyncio.sleep(RESTART_COOLDOWN_S)
            elif orphan_pid is not None:
                _safe_log(logger.warning, "daemon_port_held_by_unhealthy_process", pid=orphan_pid)
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    _kill_process_tree,
                    orphan_pid,
                )
                self._append_line(
                    f"--- daemon unhealthy port owner stopped pid={orphan_pid} at {_utcnow_iso()} ---"
                )
                await asyncio.sleep(RESTART_COOLDOWN_S)
            args = extra_args if extra_args is not None else self.last_extra_args
            result = await self._start_locked(args)
            event = {
                "at": _utcnow_iso(),
                "reason": reason,
                "was_running_before": was_running,
                "new_pid": result.get("pid"),
                "args": args,
            }
            self._restart_history.append(event)
            return {**result, "restart_event": event}

    # ------------------------------------------------------------------
    # Reader (runs in daemon thread)
    # ------------------------------------------------------------------

    def _reader_loop(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            while True:
                raw = proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                self._append_line(line)
        except Exception as e:
            self._append_line(f"--- reader error: {e} ---")
        finally:
            rc = proc.poll()
            if rc is None:
                try:
                    rc = proc.wait(timeout=1.0)
                except Exception:
                    rc = -1
            if self._proc is proc:
                self._last_exit_code = rc
                self._append_line(
                    f"--- daemon process ended code={rc} at {_utcnow_iso()} ---"
                )

    def _append_line(self, line: str) -> None:
        self._ring.append(line)
        if self._log_fh is None:
            return
        payload = line + "\n"
        try:
            self._log_fh.write(payload)
            self._log_bytes_written += len(payload.encode("utf-8", errors="replace"))
            if self._log_bytes_written >= LOG_MAX_BYTES and self._log_path is not None:
                self._rotate_log()
        except Exception:
            pass

    def _rotate_log(self) -> None:
        if self._log_path is None or self._log_fh is None:
            return
        rolled = self._log_path.with_suffix(self._log_path.suffix + ".1")
        try:
            self._log_fh.close()
        except Exception:
            pass
        self._log_fh = None
        try:
            if rolled.exists():
                rolled.unlink()
            self._log_path.rename(rolled)
        except Exception as e:
            logger.warning("daemon_log_rotate_failed", path=str(self._log_path), error=str(e))
        try:
            self._log_fh = open(self._log_path, "a", encoding="utf-8", buffering=1)
            self._log_bytes_written = 0
        except Exception as e:
            logger.warning("daemon_log_reopen_failed", path=str(self._log_path), error=str(e))
            self._log_fh = None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        running = self.is_running()
        adopted = False
        adopted_pid: int | None = None
        probe_healthy = False
        probe_blocker: dict[str, Any] | None = None
        listening_pid = self._proc.pid if running and self._proc else None
        if running:
            listening_pid = _find_daemon_listen_pid()
            probe_healthy = _probe_daemon_up_sync()
            if not probe_healthy:
                probe_blocker = _daemon_known_blocker_sync()
        else:
            listening_pid = _find_daemon_listen_pid()
            probe_healthy = _probe_daemon_up_sync()
            if not probe_healthy:
                probe_blocker = _daemon_known_blocker_sync()
            if probe_healthy:
                running = True
                adopted = True
                adopted_pid = listening_pid
            elif probe_blocker and listening_pid is not None:
                running = True
                adopted = True
                adopted_pid = listening_pid
        uptime_s: float | None = None
        if running and self._started_at is not None:
            uptime_s = (datetime.now(timezone.utc) - self._started_at).total_seconds()
        return {
            "running": running,
            "pid": self._proc.pid if running and self._proc else adopted_pid,
            "adopted": adopted,
            "probe_healthy": probe_healthy,
            "probe_blocker": probe_blocker,
            "listening_pid": listening_pid,
            "port_held_by_unhealthy_process": bool(
                listening_pid is not None and not running and probe_blocker is None
            ),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "uptime_seconds": uptime_s,
            "last_exit_code": self._last_exit_code,
            "log_path": str(self._log_path) if self._log_path else None,
            "daemon_url": DAEMON_URL,
        }

    def logs(self, tail: int = 100) -> dict[str, Any]:
        tail = max(1, min(RING_BUFFER_LINES, tail))
        ring_lines = list(self._ring)
        lines = ring_lines[-tail:]
        source = "ring"
        log_path = self._log_path

        fallback_path = self._log_path
        if fallback_path is None:
            today = datetime.now().strftime("%Y%m%d")
            candidate = _LOG_DIR / f"reachy-daemon-{today}.log"
            fallback_path = candidate if candidate.exists() else None
        if fallback_path is not None and fallback_path.exists():
            try:
                file_lines = fallback_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if not lines:
                    lines = file_lines[-tail:]
                    source = "file"
                elif len(lines) < tail:
                    lines = (file_lines + lines)[-tail:]
                    source = "file+ring"
                log_path = fallback_path
            except Exception as e:
                logger.warning("daemon_log_read_failed", path=str(fallback_path), error=str(e))
        return {
            "lines": lines,
            "count": len(lines),
            "total_buffered": len(ring_lines),
            "log_path": str(log_path) if log_path else None,
            "source": source,
        }

    def known_issues(self) -> dict[str, Any]:
        """Return lightweight daemon issue hints without running full diagnostics."""
        return self._scan_known_issues()

    # ------------------------------------------------------------------
    # Recovery + atexit reaping
    # ------------------------------------------------------------------

    def restart_history(self) -> list[dict[str, Any]]:
        """Return the daemon's recent start/restart events (newest last)."""
        return list(self._restart_history)

    async def reset_state(self, reason: str = "manual") -> dict[str, Any]:
        """Smart Re-link primitive: nudge the started-at clock + log the event.

        With the auto-restart watchdog removed, "reset state" no longer
        clears failure counters (there are none). It still bumps the
        started_at timestamp so any UI-side "starting…" progress indicator
        re-engages, and emits a structured log line we can grep.
        """
        if self.is_running():
            self._started_at = datetime.now(timezone.utc)
        _safe_log(
            logger.info,
            "reachy_supervisor_state_reset",
            reason=reason,
        )
        return {
            "ok": True,
            "reason": reason,
            "supervisor": self.status(),
        }

    def _atexit_stop(self) -> None:
        """Reap the daemon subprocess on host_agent shutdown.

        Without this, killing the host_agent console window (or any
        uvicorn crash) leaves the Reachy daemon child running, which
        keeps :8000 bound and the motor COM port held. The next launch
        then fails to spawn a fresh daemon — surfaced in the UI as
        "pid exists but :8000 is not responding."
        """
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        # Best-effort tree kill of anything still bound to :8000 — covers
        # uvicorn workers and GStreamer subprocesses the daemon spawned.
        try:
            pid = _find_daemon_listen_pid()
            if pid is not None:
                _kill_process_tree(pid)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def diagnostics(self) -> dict[str, Any]:
        daemon_info: dict[str, Any] = {"reachable": False}
        try:
            async with httpx.AsyncClient(timeout=DAEMON_PROBE_TIMEOUT_S) as client:
                resp = await client.get(f"{DAEMON_URL}/api/daemon/status")
                if resp.status_code < 400:
                    daemon_info = {"reachable": True, **resp.json()}
                else:
                    daemon_info = {"reachable": False, "status_code": resp.status_code}
        except Exception as e:
            daemon_info = {"reachable": False, "error": str(e)}

        loop = asyncio.get_running_loop()
        audio = await loop.run_in_executor(None, _enumerate_audio_devices)
        usb = await loop.run_in_executor(None, _enumerate_usb_reachy)
        host = await loop.run_in_executor(None, _host_metrics)

        return {
            "daemon": daemon_info,
            "audio_devices": audio,
            "usb_devices": usb,
            "host": host,
            "supervisor": self.status(),
            "restart_history": list(self._restart_history),
            "known_issues": self._scan_known_issues(),
        }

    def _scan_known_issues(self) -> dict[str, Any]:
        """
        Scan the daemon log ring buffer for patterns we've seen cause trouble
        and return a structured summary. Each entry pairs a boolean with a
        short human-readable hint the DaemonPanel can render.
        """
        lines = list(self.logs(tail=RING_BUFFER_LINES).get("lines") or [])
        blob = "\n".join(lines).lower()

        issues: list[dict[str, Any]] = []

        if "gst-stream-error-quark" in blob or "ksvideosrc" in blob:
            issues.append({
                "id": "media_server_error",
                "severity": "warning",
                "title": "Media server failed (webcam/GStreamer)",
                "hint": "Motion and emotions still work. Launch the daemon "
                        "with --no-media (set ZERO_REACHY_DAEMON_ARGS to "
                        "include --no-media) to silence this.",
            })
        if "no module named 'reachy_mini'" in blob:
            issues.append({
                "id": "missing_reachy_mini",
                "severity": "error",
                "title": "reachy_mini package not installed",
                "hint": "Point the supervisor at the Reachy Mini Control "
                        "desktop app's venv, or run "
                        "`.venv\\Scripts\\pip install -r requirements.txt` "
                        "in host_agent/.",
            })
        if ("could not find a reachy mini" in blob
                or "no serial port" in blob
                or "hardware config" in blob and "error" in blob):
            issues.append({
                "id": "hardware_missing",
                "severity": "warning",
                "title": "No Reachy hardware detected",
                "hint": "Launch with --mockup-sim for development, or plug in "
                        "the Reachy Mini USB cable.",
            })
        no_motors_index = blob.rfind("no motors detected")
        clean_start_index = blob.rfind("daemon started successfully")
        if no_motors_index >= 0 and clean_start_index < no_motors_index:
            issues.append({
                "id": "motors_unpowered",
                "severity": "error",
                "title": "Reachy motors are not powered",
                "hint": "The USB serial bridge is visible, but the motor bus "
                        "is empty. Turn on the Reachy Mini power supply and "
                        "then run start-zero.bat again.",
            })

        return {
            "count": len(issues),
            "items": issues,
        }

    # ------------------------------------------------------------------
    # Audio reset
    # ------------------------------------------------------------------

    async def reset_audio(self) -> dict[str, Any]:
        """
        Re-enumerate Windows audio devices. The host_agent's ``AudioCapture``
        instance is recreated lazily on the next ``/record/start`` by
        ``_get_capture()`` so we don't need to destroy it here — we just
        report what the host sees now.
        """
        loop = asyncio.get_running_loop()
        devices = await loop.run_in_executor(None, _enumerate_audio_devices)
        return {"ok": True, "audio_devices": devices}


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _daemon_port() -> int:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(DAEMON_URL)
        return parsed.port or (443 if parsed.scheme == "https" else 80)
    except Exception:
        return 8000


def _find_daemon_listen_pid() -> int | None:
    """Return the process holding the daemon HTTP port, if any.

    The host agent can restart independently from the Reachy daemon. In that
    case the daemon is healthy but this supervisor has no ``Popen`` handle.
    Treat the listening port as an adopted daemon instead of reporting stopped.
    """
    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:
        return None

    port = _daemon_port()
    try:
        conns = psutil.net_connections(kind="inet")
    except Exception:
        return None
    for conn in conns:
        try:
            if conn.status != psutil.CONN_LISTEN:
                continue
            if not conn.laddr or conn.laddr.port != port:
                continue
            return conn.pid
        except Exception:
            continue
    return None


def _kill_process_tree(root_pid: int) -> None:
    """Best-effort kill of a process and all its descendants. Used after the
    daemon's own ``terminate()`` because reachy_mini spawns a uvicorn child
    plus GStreamer subprocesses that hold COM3 and audio device handles.
    """
    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:
        return
    try:
        root = psutil.Process(root_pid)
    except psutil.NoSuchProcess:
        return
    roots = [root]
    try:
        parent = root.parent()
        parent_cmd = " ".join(parent.cmdline()).lower() if parent else ""
        if parent and "run_reachy_daemon.py" in parent_cmd:
            roots.insert(0, parent)
    except Exception:
        pass

    seen: set[int] = set()
    for proc in roots:
        if proc.pid in seen:
            continue
        seen.add(proc.pid)
        try:
            children = proc.children(recursive=True)
        except Exception:
            children = []
        for child in children:
            if child.pid in seen:
                continue
            seen.add(child.pid)
            try:
                child.kill()
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass


async def _probe_daemon_up() -> bool:
    return await asyncio.to_thread(_probe_daemon_up_sync)


def _daemon_http_get_json_sync(
    api_path: str,
    timeout_s: float | None = None,
    read_limit: int = 32768,
) -> tuple[int, dict[str, Any] | None]:
    import http.client
    from urllib.parse import urlparse

    parsed = urlparse(DAEMON_URL)
    host = parsed.hostname or "127.0.0.1"
    if host in {"localhost", "::1"}:
        host = "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base_path = parsed.path.rstrip("/") if parsed.path else ""
    path = base_path + api_path
    conn_cls = (
        http.client.HTTPSConnection
        if parsed.scheme == "https"
        else http.client.HTTPConnection
    )
    conn = conn_cls(
        host,
        port,
        # Use DAEMON_PROBE_TIMEOUT_S (25 s). Status() does two sequential
        # HTTP requests (/api/daemon/status + /api/state/full); under daemon
        # load a single round trip can exceed 3 s, the zero-api proxy returns
        # 5xx, and the UI renders a false-positive "host_agent isn't responding"
        # alert in DaemonPanel.
        timeout=timeout_s or DAEMON_PROBE_TIMEOUT_S,
    )
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read(read_limit)
        status = int(resp.status)
    finally:
        conn.close()
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        data = None
    return status, data if isinstance(data, dict) else None


def _probe_daemon_up_sync() -> bool:
    try:
        status_code, status_data = _daemon_http_get_json_sync(
            "/api/daemon/status",
            read_limit=4096,
        )
        if status_code >= 400 or not status_data:
            return False

        state_code, state_data = _daemon_http_get_json_sync(
            "/api/state/full?with_head_pose=true"
            "&with_body_yaw=true"
            "&with_antenna_positions=true"
            "&with_doa=false"
            "&with_head_joints=false"
            "&with_target_head_pose=false"
            "&use_pose_matrix=false",
        )
        if state_code >= 400 or not state_data:
            return False
        state_keys = {
            "head_pose",
            "body_yaw",
            "antennas_position",
            "antenna_positions",
            "control_mode",
        }
        return any(key in state_data for key in state_keys)
    except Exception:
        return False


def _daemon_blocker_from_status_data(status_data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(status_data, dict):
        return None
    text = " ".join(
        str(value or "")
        for value in (
            status_data.get("state"),
            status_data.get("error"),
            status_data.get("detail"),
        )
    ).lower()
    if (
        "no motors detected" in text
        or "motor bus" in text
        or ("power supply" in text and "motor" in text)
    ):
        return {
            "id": "motors_unpowered",
            "severity": "error",
            "detail": (
                status_data.get("error")
                or "Reachy motor bus is not detected; check motor power and connector."
            ),
        }
    return None


def _daemon_known_blocker_sync() -> dict[str, Any] | None:
    try:
        status_code, status_data = _daemon_http_get_json_sync(
            "/api/daemon/status",
            timeout_s=2.0,
            read_limit=4096,
        )
        if status_code >= 400:
            return None
        return _daemon_blocker_from_status_data(status_data)
    except Exception:
        return None


def _enumerate_audio_devices() -> list[dict[str, Any]]:
    try:
        import pyaudiowpatch as pyaudio  # type: ignore[import-not-found]
    except Exception as e:
        return [{"error": f"pyaudiowpatch unavailable: {e}"}]

    try:
        pa = pyaudio.PyAudio()
    except Exception as e:
        return [{"error": f"pyaudio init failed: {e}"}]

    # Windows MME names are truncated to 31 chars, so "Echo Cancelling Speakerphone
    # (Reachy Mini Audio)" shows up as "Echo Cancelling Speakerphone (R". Match any
    # of these hint substrings (shared with audio_capture.REACHY_DEVICE_HINTS).
    hints = (
        "reachy",
        "echo cancelling speakerphone",
        "xmos",
        "xvf",
        "pollen",
    )
    try:
        devices: list[dict[str, Any]] = []
        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
            except Exception:
                continue
            name = info.get("name") or ""
            lname = name.lower()
            devices.append(
                {
                    "index": i,
                    "name": name,
                    "is_input": int(info.get("maxInputChannels", 0)) > 0,
                    "is_output": int(info.get("maxOutputChannels", 0)) > 0,
                    "sample_rate": int(info.get("defaultSampleRate", 0)),
                    "host_api": info.get("hostApi"),
                    "is_reachy": any(h in lname for h in hints),
                }
            )
        return devices
    finally:
        try:
            pa.terminate()
        except Exception:
            pass


def _enumerate_usb_reachy() -> dict[str, Any]:
    """
    Best-effort list of USB serial ports. When the Reachy USB cable is
    unplugged, the daemon can't find a COM port and crashes at startup —
    surfacing this in diagnostics pinpoints the exact reason.
    """
    ports: list[dict[str, Any]] = []
    try:
        from serial.tools import list_ports  # type: ignore[import-not-found]

        for p in list_ports.comports():
            ports.append(
                {
                    "device": p.device,
                    "description": p.description,
                    "vid": getattr(p, "vid", None),
                    "pid": getattr(p, "pid", None),
                    "manufacturer": getattr(p, "manufacturer", None),
                    "serial_number": getattr(p, "serial_number", None),
                }
            )
    except Exception as e:
        return {"error": f"pyserial unavailable: {e}", "ports": []}

    # Reachy Mini uses a WCH CH343 USB-to-serial chip for motor control. Older
    # Reachys used FTDI. Match either so hardware detection works on both.
    def _looks_reachy(p: dict[str, Any]) -> bool:
        mfr = (p.get("manufacturer") or "").lower()
        desc = (p.get("description") or "").lower()
        return any(
            marker in mfr or marker in desc
            for marker in ("ftdi", "wch", "ch343", "ch340", "ch341", "reachy")
        )

    likely = [p for p in ports if _looks_reachy(p)]
    return {"ports": ports, "likely_reachy": likely}


def _host_metrics() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        import psutil  # type: ignore[import-not-found]

        out["cpu_percent"] = psutil.cpu_percent(interval=0.0)
        mem = psutil.virtual_memory()
        out["mem_used_mb"] = int(mem.used / (1024 * 1024))
        out["mem_total_mb"] = int(mem.total / (1024 * 1024))
        out["mem_percent"] = mem.percent
    except Exception as e:
        out["psutil_error"] = str(e)
    out["timestamp"] = _utcnow_iso()
    return out


# Global singleton
_supervisor: DaemonSupervisor | None = None


def get_supervisor() -> DaemonSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = DaemonSupervisor()
    return _supervisor
