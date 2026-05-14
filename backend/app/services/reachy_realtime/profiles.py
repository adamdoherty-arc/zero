"""
Unified profile catalog for the Reachy realtime bridge.

Two sources, one surface:

1. **Upstream profiles** vendored under ``backend/app/data/reachy_profiles/``.
   Each directory has the upstream layout: ``instructions.txt`` (with optional
   ``[include_name]`` placeholders expanded from
   ``backend/app/data/reachy_prompts_library/``), ``tools.txt``, optional
   ``voice.txt``.

2. **Zero personas** defined in ``app.services.reachy_personas``. These are
   Python data objects that predate the realtime port — the existing voice
   loop still reads them — so we keep them the source of truth for the 12
   Zero-native personas and surface them through this catalog with an
   ``origin: "zero"`` tag so the UI can group them.

Name collisions are resolved in favour of upstream (the persona catalog
keeps both representations in sync). Other Zero personas are additive.

Upstream reference:
https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/main/src/reachy_mini_conversation_app/prompts.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog

from app.services.reachy_personas import (
    MOTION_TAG_INSTRUCTIONS,
    PERSONAS as ZERO_PERSONAS,
)
from app.services.reachy_realtime.common import (
    BACKEND_OPENAI,
    DEFAULT_VOICE_BY_BACKEND,
    normalize_backend,
)
from app.services.reachy_realtime.tools import ALL_TOOL_NAMES

logger = structlog.get_logger()

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_PROFILES_DIR = _DATA_DIR / "reachy_profiles"
_PROMPTS_DIR = _DATA_DIR / "reachy_prompts_library"

_INCLUDE_PATTERN = re.compile(r"^\[([A-Za-z0-9/_-]+)\]$")


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    tagline: str
    instructions: str
    tools: tuple[str, ...]
    voice: Optional[str]
    origin: str  # "upstream" | "zero"
    model: Optional[str] = None  # persona-bound LLM (local backend only)
    character_card: Optional[dict] = None  # SillyTavern V2 schema, raw


def _expand_includes(content: str) -> str:
    """Resolve ``[fragment]`` lines against ``reachy_prompts_library``."""
    out: list[str] = []
    for line in content.splitlines():
        m = _INCLUDE_PATTERN.match(line.strip())
        if not m:
            out.append(line)
            continue
        frag_path = _PROMPTS_DIR / f"{m.group(1)}.txt"
        if frag_path.exists():
            out.append(frag_path.read_text(encoding="utf-8").rstrip())
        else:
            logger.warning("prompt_fragment_missing", fragment=m.group(1))
            out.append(line)
    return "\n".join(out)


def _load_upstream_profile(dir_path: Path) -> Optional[Profile]:
    # SillyTavern V2 character card takes precedence if present — its
    # ``system_prompt`` (or ``description`` + ``personality``) becomes the
    # instructions, and ``extensions`` can override voice/model/tools.
    card_file = dir_path / "character.json"
    card: Optional[dict] = None
    instructions: Optional[str] = None
    if card_file.exists():
        try:
            import json as _json
            card = _json.loads(card_file.read_text(encoding="utf-8"))
            instructions = _instructions_from_card(card)
        except Exception as e:
            logger.warning("character_card_read_failed", profile=dir_path.name, error=str(e))
            card = None

    if instructions is None:
        # SOUL.md takes precedence over instructions.txt — it's the canonical
        # persona format from the openhuman / OpenClaw / Claude Code convention.
        # Falls back to instructions.txt for legacy profiles that haven't
        # migrated yet.
        try:
            from app.services.soul_md import load_soul_md
            soul = load_soul_md(dir_path)
            if soul:
                instructions = _expand_includes(soul)
        except Exception as e:
            logger.warning("soul_md_load_failed", profile=dir_path.name, error=str(e))

        if instructions is None:
            instr_file = dir_path / "instructions.txt"
            if not instr_file.exists():
                return None
            try:
                instructions = _expand_includes(instr_file.read_text(encoding="utf-8").strip())
            except Exception as e:
                logger.warning("upstream_profile_read_failed", profile=dir_path.name, error=str(e))
                return None

    tools = _parse_tools_txt(dir_path / "tools.txt")
    # Card extensions provide DEFAULTS; voice.txt / model.txt / tools.txt
    # files are user-editable and win when present (they're what the Voice
    # Settings UI writes to via PUT /profiles/{id}/voice|model). Without
    # this priority order, edits made via the UI silently lose to whatever
    # ``extensions.voice`` was baked into character.json at seed time.
    card_voice: Optional[str] = None
    card_model: Optional[str] = None
    if card is not None:
        ext = (card.get("extensions") or {}) if isinstance(card, dict) else {}
        if isinstance(ext, dict):
            card_voice = ext.get("voice") or None
            card_model = ext.get("model") or None
            ext_tools = ext.get("tools")
            if isinstance(ext_tools, (list, tuple)) and ext_tools:
                tools = tuple(str(t) for t in ext_tools)
    voice_file = dir_path / "voice.txt"
    voice = (
        (voice_file.read_text(encoding="utf-8").strip() if voice_file.exists() else None)
        or card_voice
    )
    model_file = dir_path / "model.txt"
    model = (
        (model_file.read_text(encoding="utf-8").strip() if model_file.exists() else None)
        or card_model
    )
    name = (
        (card.get("name") if isinstance(card, dict) else None)
        or _humanize(dir_path.name)
    )
    # First non-empty line (minus markdown) makes a decent tagline.
    tagline = _first_tagline(instructions)
    return Profile(
        id=dir_path.name,
        name=name,
        tagline=tagline,
        instructions=instructions,
        tools=tools,
        voice=voice,
        origin="upstream",
        model=model,
        character_card=card,
    )


def _instructions_from_card(card: dict) -> str:
    """Compose a flat instructions string from a V2 character card.

    Order: system_prompt → description → personality → scenario →
    mes_example. Empty fields are skipped. We don't enforce schema strictness
    — community cards are inconsistent.
    """
    parts: list[str] = []
    sysp = (card.get("system_prompt") or "").strip()
    if sysp:
        parts.append(sysp)
    desc = (card.get("description") or "").strip()
    if desc:
        parts.append(desc)
    pers = (card.get("personality") or "").strip()
    if pers:
        parts.append(f"## Personality\n{pers}")
    scen = (card.get("scenario") or "").strip()
    if scen:
        parts.append(f"## Scenario\n{scen}")
    mes = (card.get("mes_example") or "").strip()
    if mes:
        parts.append(f"## Speaking style\n{mes}")
    post = (card.get("post_history_instructions") or "").strip()
    if post:
        parts.append(post)
    return _expand_includes("\n\n".join(parts).strip())


def _parse_tools_txt(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ALL_TOOL_NAMES
    tools: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tools.append(line)
    return tuple(tools) if tools else ALL_TOOL_NAMES


def _humanize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("-", "_").split("_"))


def _first_tagline(text: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if not s or s.startswith("##") or s.lower().startswith("you are"):
            continue
        return s[:120]
    return ""


def _zero_persona_to_profile(p) -> Profile:
    return Profile(
        id=p.id,
        name=p.name,
        tagline=p.tagline,
        # Append Zero's gesture-marker tail so the realtime path still honours
        # any inline [emotion:..] / [dance:..] tokens the model might emit in
        # text channels (tools remain the primary motion surface).
        instructions=p.system_prompt + MOTION_TAG_INSTRUCTIONS,
        tools=tuple(p.tools) if p.tools else ALL_TOOL_NAMES,
        voice=None,
        origin="zero",
    )


@lru_cache(maxsize=1)
def _all_profiles() -> dict[str, Profile]:
    """Load once, cache forever. Upstream wins on id collisions."""
    out: dict[str, Profile] = {}
    # Upstream first so it takes precedence.
    if _PROFILES_DIR.exists():
        for d in sorted(p for p in _PROFILES_DIR.iterdir() if p.is_dir()):
            prof = _load_upstream_profile(d)
            if prof is not None:
                out[prof.id] = prof
    for zp in ZERO_PERSONAS:
        if zp.id not in out:
            out[zp.id] = _zero_persona_to_profile(zp)
    return out


def list_profiles() -> list[Profile]:
    return list(_all_profiles().values())


def get_profile(profile_id: Optional[str]) -> Profile:
    """Resolve a profile id. Empty / unknown falls back to ``default`` or the
    first available profile."""
    all_ = _all_profiles()
    if profile_id and profile_id in all_:
        return all_[profile_id]
    if "companion" in all_:
        return all_["companion"]
    # Fallback: first by id, or a minimal built-in if nothing loaded.
    if all_:
        return next(iter(all_.values()))
    return Profile(
        id="default",
        name="Default",
        tagline="",
        instructions="You are Reachy Mini, a friendly conversational robot.",
        tools=ALL_TOOL_NAMES,
        voice=None,
        origin="upstream",
    )


# Latency-oriented suffix appended to every realtime-session system prompt.
# Short replies = short TTS playback = apparent responsiveness. Each profile
# already has its own flavor; this only constrains length + voice-friendliness.
_REALTIME_SHORT_REPLY_SUFFIX = (
    "\n\nResponse guidance: Reply in 1–2 natural spoken sentences, under 25 "
    "words, unless the user explicitly asks for detail. No markdown, bullets, "
    "URLs, or emoji — your words are spoken aloud. Numbers and times in spoken "
    "form (\"three p.m.\", \"two emails\"). You can interrupt yourself if the "
    "user speaks — it's natural."
)


_GESTURE_MARKER_SECTION_RE = re.compile(
    r"\n+#{2,6}\s*GESTURE MARKERS\b.*?(?=\n+#{1,6}\s|\Z)",
    flags=re.IGNORECASE | re.DOTALL,
)
_INLINE_MOTION_MARKER_RE = re.compile(r"\[(?:emotion|dance):[^\]]+\]\s*", flags=re.IGNORECASE)

_REALTIME_SPOKEN_SAFETY_SUFFIX = (
    "\n\nHard realtime audio rules: Speak only in English unless the user "
    "explicitly asks for another language. Never output or pronounce bracketed "
    "stage directions, emotion tags, dance tags, SSML, JSON, markdown, or "
    "language labels. If motion would help, use an available tool instead of "
    "putting tags in spoken words."
    "\n\nRobot motion rules: The UI state 'Body still' or 'Auto motion off' "
    "only pauses autonomous idle wobble and expressive motion during speech. "
    "It does not block explicit user-commanded robot actions. When the user "
    "asks you to move, nod, look, wake, gesture, or play an emotion/dance, use "
    "the movement tools directly unless system status says the robot body is "
    "unavailable or a hardware fault is active. Do not ask to enable body "
    "motion for a direct movement command; only change automatic body motion "
    "when the user asks for ongoing idle/live body motion."
)


def _make_realtime_spoken_prompt(text: str) -> str:
    """Make profile instructions safe for providers that synthesize speech."""
    cleaned = _GESTURE_MARKER_SECTION_RE.sub("", text or "")
    cleaned = _INLINE_MOTION_MARKER_RE.sub("", cleaned)
    return cleaned.strip() + _REALTIME_SHORT_REPLY_SUFFIX + _REALTIME_SPOKEN_SAFETY_SUFFIX


def resolve_instructions(
    profile_id: Optional[str],
    *,
    seed_text: Optional[str] = None,
) -> str:
    """Resolve the full system prompt for a realtime session.

    For Zero personas (companion, assistant, deep_work, …) the prompt is
    composed via ``reachy_memory_blocks.compose_system_prompt`` so realtime
    shares the same identity / human / relationship blocks as the classic
    voice loop. For any non-Zero upstream profile we fall back to the raw
    instructions text so external HF Spaces apps still work.

    When ``seed_text`` is provided (e.g. the user's opening utterance, a
    persona-bound seed phrase, or a known topic), microagents whose
    triggers match are injected as additional context. This is the
    openhuman/OpenHands microagent pattern: triggered knowledge bundles
    that load only when relevant, keeping the default prompt slim.
    """
    prof = get_profile(profile_id)

    base: str
    try:
        from app.services.reachy_personas import get_persona
        if get_persona(prof.id) is not None:
            from app.services.reachy_memory_blocks import compose_system_prompt
            base = _make_realtime_spoken_prompt(compose_system_prompt(
                prof.id,
                working_context="",
                include_voice_suffix=False,
            ))
        else:
            base = _make_realtime_spoken_prompt(prof.instructions or "")
    except Exception as e:  # noqa: BLE001
        logger.debug("realtime_compose_fallback", error=str(e))
        base = _make_realtime_spoken_prompt(prof.instructions or "")

    if seed_text:
        try:
            from app.services.microagents_service import get_microagents_service
            microagents = get_microagents_service()
            context = microagents.compose_context_for(
                seed_text, agent_persona=prof.id, max_chars=2000
            )
            if context:
                base = f"{base}\n\n{context}"
                logger.info(
                    "microagent_context_injected",
                    profile=prof.id,
                    chars=len(context),
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("microagent_inject_failed", error=str(e))

    return base


def compose_turn_context(text: str, *, profile_id: Optional[str] = None) -> str:
    """Per-turn microagent context for chat / classic-voice paths.

    Realtime LLM sessions lock the system prompt at start, so they use
    ``resolve_instructions(seed_text=...)`` once. Non-realtime callers
    (chat router, classic STT→Intent→LLM) can call this each turn and
    inject the returned string just before the user message.
    """
    if not text:
        return ""
    persona = profile_id or "any"
    try:
        from app.services.microagents_service import get_microagents_service
        return get_microagents_service().compose_context_for(
            text, agent_persona=persona, max_chars=2000
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("compose_turn_context_failed", error=str(e))
        return ""


def resolve_tools(profile_id: Optional[str]) -> tuple[str, ...]:
    return get_profile(profile_id).tools


def resolve_voice(profile_id: Optional[str], backend: Optional[str]) -> str:
    backend = normalize_backend(backend)
    prof = get_profile(profile_id)
    if prof.voice:
        return prof.voice
    return DEFAULT_VOICE_BY_BACKEND.get(backend, DEFAULT_VOICE_BY_BACKEND[BACKEND_OPENAI])


def profile_to_dict(p: Profile, include_instructions: bool = False) -> dict:
    d = {
        "id": p.id,
        "name": p.name,
        "tagline": p.tagline,
        "tools": list(p.tools),
        "voice": p.voice,
        "origin": p.origin,
        "model": p.model,
    }
    if include_instructions:
        d["instructions"] = p.instructions
    return d
