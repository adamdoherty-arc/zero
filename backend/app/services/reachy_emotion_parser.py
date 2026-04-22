"""
Parse inline gesture markers emitted by the LLM, strip them from the spoken
text, and return a list of actions the voice loop should dispatch to the
Reachy daemon.

Marker grammar (case insensitive, whitespace tolerant):

    [emotion:<name>]   — resolves via reachy_motion_library (alias or canonical)
    [dance:<name>]     — same, constrained to the dance library
    [motion:<name>]    — either library, name-resolved
    [look:x,y,z]       — point the head at a 3D target (meters)

Anything else inside brackets is left alone (so the LLM's citation-style "[1]"
survives). Actions are returned in order so the caller can interleave them
with TTS for rough lip-sync / beat timing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

GestureKind = Literal["emotion", "dance", "motion", "look"]


@dataclass(frozen=True)
class GestureAction:
    kind: GestureKind
    payload: str
    # Character offset in the cleaned text where this gesture should fire.
    # Downstream consumers can use this to align gestures with TTS chunks.
    offset: int


_PATTERN = re.compile(
    r"\[\s*(emotion|dance|motion|look)\s*:\s*([^\]]+?)\s*\]",
    re.IGNORECASE,
)


def parse_and_strip(text: str) -> tuple[str, list[GestureAction]]:
    """
    Strip gesture markers from `text` and return (clean_text, actions).
    `offset` on each action points into `clean_text`.
    """
    if not text:
        return text, []

    actions: list[GestureAction] = []
    out: list[str] = []
    cursor = 0
    for match in _PATTERN.finditer(text):
        out.append(text[cursor:match.start()])
        cleaned_so_far = sum(len(piece) for piece in out)
        kind = match.group(1).lower()
        payload = match.group(2).strip()
        actions.append(GestureAction(kind=kind, payload=payload, offset=cleaned_so_far))
        cursor = match.end()
    out.append(text[cursor:])

    clean = "".join(out)
    # Collapse double spaces and kill the " !" / " ." / " ," artefacts left when
    # a marker sat between a word and its punctuation.
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r"\s+([.,!?;:])", r"\1", clean).strip()
    return clean, actions


def action_to_motion_request(action: GestureAction) -> Optional[dict]:
    """
    Translate an action into the payload for reachy_service.play_motion or
    look_at. Returns None if the marker was malformed.
    """
    if action.kind == "look":
        parts = [p.strip() for p in action.payload.split(",")]
        if len(parts) != 3:
            return None
        try:
            x, y, z = (float(p) for p in parts)
        except ValueError:
            return None
        return {"kind": "look", "x": x, "y": y, "z": z}
    if action.kind == "dance":
        return {"kind": "dance", "name": action.payload}
    if action.kind == "emotion":
        return {"kind": "emotion", "name": action.payload}
    if action.kind == "motion":
        return {"kind": "motion", "name": action.payload}
    return None
