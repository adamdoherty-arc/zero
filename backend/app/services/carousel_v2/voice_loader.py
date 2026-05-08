"""Voice file loader — per-property tone/lexicon/forbidden phrases injected
into the Designer's system prompt.

Voice files live at ``backend/voices/{property}.yml`` and are tracked in git so
A/B tests against voice changes are reviewable. The loader caches parsed YAML
and exposes a ``compose_system_prompt`` helper that produces a stable string
for prompt-version registry diffing.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


VOICES_DIR = Path(__file__).resolve().parents[3] / "voices"


def _voices_dir() -> Path:
    # Allow override in tests / non-standard layouts.
    import os
    override = os.getenv("ZERO_VOICES_DIR")
    return Path(override) if override else VOICES_DIR


@lru_cache(maxsize=32)
def load_voice(property_key: str) -> dict[str, Any]:
    """Return the voice file as a dict, or an empty profile if missing."""
    path = _voices_dir() / f"{property_key}.yml"
    if not path.is_file():
        logger.warning("voice_file_missing", property=property_key, path=str(path))
        return {"property": property_key, "tone": "neutral", "lexicon": [], "forbidden_phrases": []}
    try:
        import yaml  # PyYAML — already a dep via APScheduler / discord
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice_file_parse_failed", property=property_key, error=str(exc))
        return {"property": property_key, "tone": "neutral", "lexicon": [], "forbidden_phrases": []}


def list_voices() -> list[str]:
    return sorted(p.stem for p in _voices_dir().glob("*.yml"))


def compose_system_prompt(property_key: str) -> str:
    """Render a deterministic system-prompt fragment from the voice file.

    Stable ordering matters — the prompt registry hashes this string when
    deciding whether a Designer prompt has changed.
    """
    voice = load_voice(property_key)
    tone = voice.get("tone", "neutral")
    register = voice.get("register", "")
    lex = ", ".join(voice.get("lexicon") or [])
    forbid = "; ".join(voice.get("forbidden_phrases") or [])
    s1 = voice.get("slide1_constraints") or {}

    parts = [
        f"PROPERTY: {voice.get('display_name', property_key)}",
        f"TONE: {tone}" + (f" ({register})" if register else ""),
    ]
    if lex:
        parts.append(f"LEXICON (use naturally, do not stuff): {lex}")
    if forbid:
        parts.append(f"FORBIDDEN PHRASES: {forbid}")
    if s1:
        parts.append(
            "SLIDE 1: ≤"
            + str(s1.get("max_words", 12))
            + " words. " + ", ".join(s1.get("encourage") or [])
            + (". forbid: " + ", ".join(s1.get("forbid") or []) if s1.get("forbid") else "")
        )
    return "\n".join(parts)
