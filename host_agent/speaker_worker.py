"""Isolated Reachy speaker worker.

Runs outside uvicorn so Windows/PortAudio output-driver failures cannot wedge
the host_agent event loop. Protocol over stdin:

    uint32 little-endian length
    length bytes of PCM16 mono audio

Length 0 flushes queued audio. Length 0xFFFFFFFF stops the worker.
The first stdout line is JSON: {"type": "ready", ...} or {"type": "error"}.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

import structlog

from speaker_stream import SpeakerStream


def _configure_logs() -> None:
    try:
        structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    except Exception:
        pass


def _write_event(payload: dict) -> None:
    os.write(1, (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))


def _read_exact(size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sys.stdin.buffer.read(remaining)
        if not chunk:
            raise EOFError
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def main() -> int:
    _configure_logs()
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=int, default=24000)
    parser.add_argument("--device-index", type=int, default=None)
    args = parser.parse_args()

    speaker = SpeakerStream(rate=args.rate, device_index=args.device_index)
    try:
        info = speaker.start()
    except Exception as exc:
        _write_event({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 2

    _write_event({"type": "ready", **info})
    try:
        while True:
            header = _read_exact(4)
            (length,) = struct.unpack("<I", header)
            if length == 0xFFFFFFFF:
                break
            if length == 0:
                speaker.flush()
                continue
            speaker.write_pcm16(_read_exact(length))
    except EOFError:
        pass
    except Exception as exc:
        print(f"speaker_worker_error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        time.sleep(0.05)
        return 3
    finally:
        speaker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
