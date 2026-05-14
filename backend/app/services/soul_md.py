"""
SOUL.md — canonical persona definition file.

Format borrowed from the SOUL.md convention used by Claude Code, OpenClaw,
openhuman, and similar agent frameworks. A SOUL.md file lives next to
``tools.txt``/``voice.txt`` in ``backend/app/data/reachy_profiles/{id}/`` and
defines the persona's identity, voice, behaviors, safety rules, memory hints,
and emergency responses.

This module loads SOUL.md, parses well-known H2 sections, and renders a flat
system-prompt string compatible with the rest of Zero. The loader is
deliberately lenient — unrecognized sections are passed through verbatim, and
a SOUL.md without any structured headings is treated as a plain instructions
file (so it's a strict superset of the legacy ``instructions.txt`` format).

Section order in the rendered prompt (any of these may be absent):

    <preamble>              ← text before the first H2

    ## Personality          → kept verbatim
    ## Voice & Tone         → kept verbatim
    ## Behaviors            → kept verbatim, may contain H3 sub-sections
    ## Safety Rules         → kept verbatim (these are the "NEVER BREAK THESE")
    ## Memory               → kept verbatim (hints for the memory layer)
    ## Emergency Responses  → kept verbatim
    ## Games                → optional, persona-specific

Other H2 sections (e.g. ``## Hobbies``, ``## Tools``) flow through after the
known ones in the order they appear in the file.

The result is then run through the same realtime / motion-tag suffixes the
classic ``instructions.txt`` path uses, so SOUL.md is a drop-in replacement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


_H2_RE = re.compile(r"^##\s+(.+?)\s*$", flags=re.MULTILINE)


# Section names we recognise as canonical (case-insensitive). Order here is
# the order they will be re-emitted in. Anything else flows after, untouched.
_CANONICAL_ORDER = [
    "personality",
    "voice & tone",
    "voice and tone",
    "behaviors",
    "behaviour",
    "behaviours",
    "safety rules",
    "safety",
    "memory",
    "emergency responses",
    "emergency",
    "games you know",
    "games",
]


@dataclass
class SoulDoc:
    """Parsed SOUL.md document."""

    title: Optional[str] = None  # The first H1 if present
    preamble: str = ""  # Text before the first H2
    sections: list[tuple[str, str]] = field(default_factory=list)
    raw: str = ""

    def to_prompt(self) -> str:
        """Render the parsed SOUL.md back to a flat system-prompt string,
        in canonical order with unknown sections trailing."""
        parts: list[str] = []
        if self.preamble.strip():
            parts.append(self.preamble.strip())

        # Bucket sections by canonical name (lowercase).
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for canonical in _CANONICAL_ORDER:
            for name, body in self.sections:
                key = name.lower().strip()
                if key == canonical and key not in seen:
                    ordered.append((name, body))
                    seen.add(key)
                    break
        # Append everything else in original order.
        for name, body in self.sections:
            key = name.lower().strip()
            if key not in seen:
                ordered.append((name, body))
                seen.add(key)

        for name, body in ordered:
            body_clean = body.strip()
            if not body_clean:
                continue
            parts.append(f"## {name}\n{body_clean}")

        return "\n\n".join(parts).strip()


def parse_soul_md(text: str) -> SoulDoc:
    """Parse a SOUL.md document into title + preamble + ordered sections."""
    if not text:
        return SoulDoc()

    doc = SoulDoc(raw=text)

    # First H1, if any.
    h1_match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    if h1_match:
        doc.title = h1_match.group(1).strip()

    # Find every H2 boundary.
    matches = list(_H2_RE.finditer(text))
    if not matches:
        # No structured sections — treat the whole file as preamble.
        if h1_match:
            doc.preamble = text[h1_match.end():].strip()
        else:
            doc.preamble = text.strip()
        return doc

    # Preamble = text from end-of-H1 (or start of file) to first H2.
    preamble_start = h1_match.end() if h1_match and h1_match.start() < matches[0].start() else 0
    doc.preamble = text[preamble_start: matches[0].start()].strip()

    # Each section: from H2 to the next H2 (or EOF).
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        doc.sections.append((name, body))

    return doc


def load_soul_md(profile_dir: Path) -> Optional[str]:
    """Load and render the SOUL.md prompt for a profile directory.

    Returns the flat rendered system-prompt text, or None if no SOUL.md is
    present. Callers should fall back to ``instructions.txt`` in that case.
    """
    soul_file = profile_dir / "SOUL.md"
    if not soul_file.exists():
        return None
    try:
        raw = soul_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("soul_md_read_failed", profile=profile_dir.name, error=str(e))
        return None
    doc = parse_soul_md(raw)
    return doc.to_prompt() or None


def safety_rules_from_soul(doc: SoulDoc) -> list[str]:
    """Extract NEVER-BREAK safety rules as a list of strings.

    Used by Reachy's motion / consent layer to short-circuit dangerous moves
    when a profile declares hard physical constraints.
    """
    rules: list[str] = []
    for name, body in doc.sections:
        key = name.lower().strip()
        if "safety" not in key:
            continue
        for raw in body.splitlines():
            line = raw.strip().lstrip("-*0123456789.) ")
            if line:
                rules.append(line)
    return rules
