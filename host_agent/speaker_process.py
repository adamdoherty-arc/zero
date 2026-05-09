"""Subprocess wrapper for the Reachy USB speaker stream."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

_STOP = 0xFFFFFFFF


def _safe_log(level: str, event: str, **fields) -> None:
    try:
        getattr(logger, level)(event, **fields)
    except Exception:
        pass


class SpeakerProcessSink:
    """PCM16 speaker sink isolated from host_agent's uvicorn process."""

    def __init__(
        self,
        *,
        rate: int = 24000,
        device_index: Optional[int] = None,
    ) -> None:
        self.rate = rate
        self.device_index = device_index
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._lock = threading.Lock()
        self._info: dict = {}
        self._stderr_thread: Optional[threading.Thread] = None

    def start(self, timeout_s: float = 20.0) -> dict:
        if self._proc is not None and self._proc.poll() is None:
            return self.info()

        host_dir = Path(__file__).resolve().parent
        python = host_dir / ".venv" / "Scripts" / "python.exe"
        if not python.exists():
            python = Path(sys.executable)
        script = host_dir / "speaker_worker.py"
        cmd = [str(python), "-u", str(script), "--rate", str(int(self.rate))]
        if self.device_index is not None:
            cmd.extend(["--device-index", str(int(self.device_index))])

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(host_dir),
                creationflags=creationflags,
            )
        except OSError as exc:
            if creationflags and getattr(exc, "errno", None) == 22:
                _safe_log("warning", "speaker_process_create_no_window_failed_retrying", error=str(exc))
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(host_dir),
                    creationflags=0,
                )
            else:
                raise RuntimeError(f"speaker worker launch failed: {exc}") from exc
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name="reachy-speaker-stderr",
            daemon=True,
        )
        self._stderr_thread.start()

        ready = self._read_ready(timeout_s=timeout_s)
        if ready.get("type") != "ready":
            self.stop()
            msg = ready.get("message") or "speaker worker did not become ready"
            raise RuntimeError(f"speaker worker failed: {msg}")
        self._info = ready
        _safe_log(
            "info",
            "speaker_process_started",
            pid=self._proc.pid,
            device_index=ready.get("device_index"),
            device_name=ready.get("device_name"),
            input_rate=ready.get("input_rate"),
            device_rate=ready.get("device_rate"),
        )
        return self.info()

    @property
    def device_name(self) -> Optional[str]:
        return self._info.get("device_name")

    def write_pcm16(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        self._write_frame(pcm_bytes)

    def flush(self) -> None:
        self._write_control(0)

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                self._write_control(_STOP, proc=proc)
        except Exception:
            pass
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _safe_log("info", "speaker_process_stopped", pid=getattr(proc, "pid", None))

    def info(self) -> dict:
        proc = self._proc
        active = bool(proc is not None and proc.poll() is None)
        return {
            **self._info,
            "active": active,
            "pid": getattr(proc, "pid", None),
            "transport": "subprocess",
        }

    def _read_ready(self, *, timeout_s: float) -> dict:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return {"type": "error", "message": "speaker worker did not start"}

        result_queue: queue.Queue[dict] = queue.Queue(maxsize=1)

        def _reader() -> None:
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        result_queue.put({
                            "type": "error",
                            "message": f"speaker worker exited early with code {proc.poll()}",
                        })
                        return
                    text = line.decode("utf-8", errors="replace").strip()
                    try:
                        event = json.loads(text)
                    except Exception:
                        _safe_log("debug", "speaker_worker_stdout", line=text)
                        continue
                    if isinstance(event, dict) and event.get("type") in ("ready", "error"):
                        result_queue.put(event)
                        return
                    _safe_log("debug", "speaker_worker_stdout_event", event=event)
            except Exception as exc:
                result_queue.put({"type": "error", "message": str(exc)})

        thread = threading.Thread(target=_reader, name="reachy-speaker-ready", daemon=True)
        thread.start()
        try:
            return result_queue.get(timeout=timeout_s)
        except queue.Empty:
            return {"type": "error", "message": "speaker worker ready timed out"}

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                if not raw:
                    break
                _safe_log("debug", "speaker_worker_stderr", line=raw.decode("utf-8", errors="replace").strip())
        except Exception:
            pass

    def _write_control(self, value: int, *, proc: Optional[subprocess.Popen[bytes]] = None) -> None:
        self._write_frame(b"", control=value, proc=proc)

    def _write_frame(
        self,
        payload: bytes,
        *,
        control: Optional[int] = None,
        proc: Optional[subprocess.Popen[bytes]] = None,
    ) -> None:
        target = proc or self._proc
        if target is None or target.poll() is not None or target.stdin is None:
            return
        length = int(control) if control is not None else len(payload)
        with self._lock:
            target.stdin.write(struct.pack("<I", length))
            if payload:
                target.stdin.write(payload)
            target.stdin.flush()
