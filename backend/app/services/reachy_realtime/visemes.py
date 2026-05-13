"""
Backend viseme surfacing for the mascot mouth.

Mirrors ``frontend/src/components/reachy/Mascot/visemes.ts`` so the on-screen
mascot can render mouth shapes derived from server-side TTS audio alignment
without re-implementing the table client-side.

The shapes are emitted on the realtime websocket as ``mascot.viseme`` events
in lockstep with the existing ``audio.delta`` PCM chunks, so the frontend can
choose to use them (more accurate) or fall back to its own text-walker
(works when the backend doesn't surface them, e.g. cloud realtime backends).
"""

from __future__ import annotations

from typing import Iterable, Iterator

VISEME_REST = "REST"

_VISEME_TABLE: dict[str, tuple[float, float]] = {
    "REST": (0.0, 0.30),
    "A":    (0.95, 0.60),
    "E":    (0.45, 1.00),
    "I":    (0.30, 0.85),
    "O":    (0.75, 0.20),
    "U":    (0.40, 0.05),
    "M":    (0.00, 0.40),
    "F":    (0.15, 0.55),
}


def viseme_for_char(ch: str) -> str:
    """Return a viseme id (REST/A/E/I/O/U/M/F) for a single character."""
    if not ch:
        return VISEME_REST
    c = ch.lower()
    if c in "a":
        return "A"
    if c in "eæɛ":
        return "E"
    if c in "iyɪ":
        return "I"
    if c in "o":
        return "O"
    # F / V close the lower lip on the teeth — must win over U / B mappings
    # for the letters 'v' and 'f' specifically.
    if c in "fv":
        return "F"
    if c in "uʊ":
        return "U"
    if c in "mbp":
        return "M"
    if c in "whˈ":
        return "O"
    if c in "rtl":
        return "I"
    if c in "sznchk":
        return "E"
    return VISEME_REST


def viseme_shape(viseme_id: str) -> tuple[float, float]:
    """Return ``(openness, width)`` for a viseme id. Falls back to REST."""
    return _VISEME_TABLE.get(viseme_id, _VISEME_TABLE[VISEME_REST])


def viseme_frames_for_speech(text: str, duration_seconds: float, frame_rate_hz: float = 20.0) -> Iterator[dict]:
    """Yield one viseme event dict per output PCM chunk.

    Walks the text linearly across the speech duration so each PCM chunk
    has a matching viseme. Each yielded dict has shape:

        {"viseme_id": "A", "openness": 0.95, "width": 0.6, "offset_ms": 50}

    The frontend uses ``offset_ms`` only for instrumentation; the events are
    delivered in order, in time with audio.delta.
    """
    if not text or duration_seconds <= 0:
        return
    frame_count = max(1, int(duration_seconds * frame_rate_hz))
    text_len = max(1, len(text))
    frame_ms = int(1000.0 / frame_rate_hz)
    for i in range(frame_count):
        idx = min(text_len - 1, int((i / frame_count) * text_len))
        ch = text[idx]
        vid = viseme_for_char(ch)
        op, wd = viseme_shape(vid)
        yield {
            "viseme_id": vid,
            "openness": op,
            "width": wd,
            "offset_ms": i * frame_ms,
            "char": ch,
        }


def collapse_consecutive(frames: Iterable[dict]) -> Iterator[dict]:
    """Drop consecutive frames with the same viseme_id to save bytes."""
    last: str | None = None
    for f in frames:
        vid = f.get("viseme_id")
        if vid == last:
            continue
        last = vid
        yield f
