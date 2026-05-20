"""Detect what KIND of meeting a calendar event is from its description.

Cheap regex match against well-known meeting URLs. Used by the scheduler
to decide whether to (a) capture system audio via loopback (in-person /
local), (b) send Zero as virtual attendee (Zoom / Meet / Teams when opted
in), or (c) skip capture entirely (calls on the user's phone).
"""

from __future__ import annotations

import re
from typing import Literal

MeetingKind = Literal["zoom", "meet", "teams", "webex", "in_person", "phone", "unknown"]


_URL_PATTERNS: tuple[tuple[MeetingKind, re.Pattern[str]], ...] = (
    ("zoom", re.compile(r"https?://[^\s)>\"']*zoom\.us/[^\s)>\"']*", re.IGNORECASE)),
    ("meet", re.compile(r"https?://meet\.google\.com/[^\s)>\"']*", re.IGNORECASE)),
    ("teams", re.compile(r"https?://teams\.microsoft\.com/[^\s)>\"']*", re.IGNORECASE)),
    ("webex", re.compile(r"https?://[^\s)>\"']*webex\.com/[^\s)>\"']*", re.IGNORECASE)),
)

_PHONE_HINTS = re.compile(r"\b(phone|call|dial-?in|conference)\b", re.IGNORECASE)
_LOCATION_IN_PERSON_HINTS = re.compile(
    r"\b(office|conference room|in.?person|building|room|hq|on-?site)\b",
    re.IGNORECASE,
)


def detect_kind(*, description: str | None, location: str | None) -> tuple[MeetingKind, str | None]:
    """Return (kind, join_url-or-None).

    Priority: explicit Zoom/Meet/Teams/Webex URL wins. Otherwise fall
    back to location hints. "Unknown" if nothing matches.
    """
    blob = " ".join(filter(None, (description or "", location or "")))
    for kind, pat in _URL_PATTERNS:
        m = pat.search(blob)
        if m:
            return kind, m.group(0).rstrip(".,)>\"'<")
    if location and _LOCATION_IN_PERSON_HINTS.search(location):
        return "in_person", None
    if blob and _PHONE_HINTS.search(blob):
        return "phone", None
    return "unknown", None
