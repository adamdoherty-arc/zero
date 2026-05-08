"""
Reachy memory blocks — Letta-style composable system-prompt segments.

Four named blocks compose into every system prompt sent to the LLM (classic
voice loop AND realtime bridge):

  persona        — active persona body + user-driven tweaks ("user prefers I
                   skip greetings"). User-editable; the model can append
                   tweaks via tool call but cannot rewrite freely.
  human          — durable facts about the user. Updated nightly by the
                   personality synthesis job; the model can extend it via the
                   ``update_memory_block`` tool when something important is
                   learned mid-turn.
  relationship   — recurring topics, inside shorthand, recent threads.
                   Built nightly from the last 7 days of turns.
  working_context — assembled per turn from CalendarService, presence, sight,
                   attention queue, and vault retrieval hits. NOT persisted.

The persona block has a hard size cap (PERSONA_MAX_CHARS); the other three
are capped to keep the system-prompt budget predictable. Edit history (last
30 edits per block) is retained so the user can revert.

Storage: ``workspace/reachy/memory_blocks.json``. Single file, atomic write.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import structlog

from app.services.reachy_personas import (
    CORE_IDENTITY,
    MOTION_TAG_INSTRUCTIONS,
    get_persona,
)

logger = structlog.get_logger()

BLOCKS_PATH = Path("workspace") / "reachy" / "memory_blocks.json"

PERSONA_MAX_CHARS = 4000
HUMAN_MAX_CHARS = 3000
RELATIONSHIP_MAX_CHARS = 2000
WORKING_CONTEXT_MAX_CHARS = 2000
EDIT_HISTORY_MAX = 30

VALID_LABELS = ("persona", "human", "relationship", "working_context")
USER_EDITABLE = ("persona", "human", "relationship")
MODEL_EDITABLE = ("human", "relationship")  # persona is read-only to the model


# Voice suffix lifted from the realtime-bridge constraint: same constraint
# both paths so personas behave identically classic vs realtime.
VOICE_SUFFIX = (
    "\n\nVoice turn: reply in 1-2 natural spoken sentences, under 25 words "
    "unless the user explicitly asks for more. No markdown, bullets, URLs, "
    "or emoji — your words are spoken aloud. Numbers and times in spoken "
    "form (\"three p.m.\", \"two emails\")."
)


@dataclass
class Edit:
    ts: float
    by: str  # "user" | "reachy" | "synthesis_job" | "migration"
    reason: str
    previous_value: str  # for revert
    new_value: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MemoryBlock:
    label: str
    value: str
    max_chars: int
    last_updated_by: str
    last_updated_at: float
    edit_history: list[Edit] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "value": self.value,
            "max_chars": self.max_chars,
            "last_updated_by": self.last_updated_by,
            "last_updated_at": self.last_updated_at,
            "edit_history": [e.to_dict() for e in self.edit_history],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryBlock":
        edits = [Edit(**e) for e in d.get("edit_history", [])]
        return cls(
            label=d["label"],
            value=d.get("value", ""),
            max_chars=d.get("max_chars", 1000),
            last_updated_by=d.get("last_updated_by", "system"),
            last_updated_at=d.get("last_updated_at", time.time()),
            edit_history=edits,
        )


_DEFAULT_BLOCKS = {
    "persona": MemoryBlock(
        label="persona",
        value="",  # filled at compose time from active persona's system_prompt
        max_chars=PERSONA_MAX_CHARS,
        last_updated_by="system",
        last_updated_at=time.time(),
    ),
    "human": MemoryBlock(
        label="human",
        value="",
        max_chars=HUMAN_MAX_CHARS,
        last_updated_by="system",
        last_updated_at=time.time(),
    ),
    "relationship": MemoryBlock(
        label="relationship",
        value="",
        max_chars=RELATIONSHIP_MAX_CHARS,
        last_updated_by="system",
        last_updated_at=time.time(),
    ),
}


class ReachyMemoryBlockStore:
    """Singleton store for the four memory blocks."""

    _instance: Optional["ReachyMemoryBlockStore"] = None

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._blocks: dict[str, MemoryBlock] = {
            label: MemoryBlock(
                label=label,
                value=blk.value,
                max_chars=blk.max_chars,
                last_updated_by=blk.last_updated_by,
                last_updated_at=blk.last_updated_at,
            )
            for label, blk in _DEFAULT_BLOCKS.items()
        }
        self._migration_done = False
        self._load()

    @classmethod
    def get_instance(cls) -> "ReachyMemoryBlockStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if not BLOCKS_PATH.exists():
                return
            raw = json.loads(BLOCKS_PATH.read_text(encoding="utf-8"))
            for label in ("persona", "human", "relationship"):
                d = (raw.get("blocks") or {}).get(label)
                if d:
                    self._blocks[label] = MemoryBlock.from_dict(d)
            self._migration_done = bool(raw.get("migration_done", False))
        except Exception as e:
            logger.warning("memory_blocks_load_failed", error=str(e))

    def _save_sync(self) -> None:
        try:
            BLOCKS_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "blocks": {label: b.to_dict() for label, b in self._blocks.items()},
                "migration_done": self._migration_done,
            }
            BLOCKS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("memory_blocks_save_failed", error=str(e))

    # ------------------------------------------------------------------
    # Public API — read
    # ------------------------------------------------------------------

    def get_block(self, label: str) -> Optional[MemoryBlock]:
        return self._blocks.get(label)

    def list_blocks(self) -> dict[str, MemoryBlock]:
        return dict(self._blocks)

    # ------------------------------------------------------------------
    # Public API — write
    # ------------------------------------------------------------------

    async def update_block(
        self,
        label: str,
        new_value: str,
        *,
        by: str,
        reason: str = "",
    ) -> MemoryBlock:
        if label not in VALID_LABELS or label == "working_context":
            raise ValueError(f"unknown or non-persistable block: {label}")
        if by == "reachy" and label not in MODEL_EDITABLE:
            raise PermissionError(
                f"the model cannot directly edit the {label!r} block"
            )

        async with self._lock:
            block = self._blocks[label]
            value = (new_value or "").strip()
            if len(value) > block.max_chars:
                value = value[: block.max_chars]
            edit = Edit(
                ts=time.time(),
                by=by,
                reason=reason or "(no reason given)",
                previous_value=block.value,
                new_value=value,
            )
            block.value = value
            block.last_updated_by = by
            block.last_updated_at = time.time()
            block.edit_history.append(edit)
            block.edit_history = block.edit_history[-EDIT_HISTORY_MAX:]
            self._save_sync()
            logger.info(
                "memory_block_updated",
                label=label,
                by=by,
                reason=reason[:80] if reason else "",
                chars=len(value),
            )
            return block

    async def append_to_block(
        self,
        label: str,
        addendum: str,
        *,
        by: str,
        reason: str = "",
    ) -> MemoryBlock:
        """Append a line to a block (the common case for the model's self-edit
        tool). Joined with ``\\n``; whole result is still capped."""
        if label not in VALID_LABELS or label == "working_context":
            raise ValueError(f"unknown or non-persistable block: {label}")
        block = self._blocks[label]
        existing = block.value.strip()
        new_line = (addendum or "").strip()
        if not new_line:
            return block
        merged = (existing + "\n" + new_line).strip() if existing else new_line
        return await self.update_block(label, merged, by=by, reason=reason)

    async def revert_block(self, label: str, edit_index: int) -> MemoryBlock:
        """Revert to ``previous_value`` of edit at ``edit_index`` (negative
        indexing supported, -1 = most recent edit)."""
        if label not in VALID_LABELS or label == "working_context":
            raise ValueError(f"unknown block: {label}")
        async with self._lock:
            block = self._blocks[label]
            if not block.edit_history:
                raise ValueError("no edits to revert")
            idx = edit_index
            if idx < 0:
                idx = len(block.edit_history) + idx
            if idx < 0 or idx >= len(block.edit_history):
                raise IndexError(f"edit index {edit_index} out of range")
            target = block.edit_history[idx]
            revert_edit = Edit(
                ts=time.time(),
                by="user",
                reason=f"revert to edit {idx} (was: {target.reason[:60]})",
                previous_value=block.value,
                new_value=target.previous_value,
            )
            block.value = target.previous_value
            block.last_updated_by = "user"
            block.last_updated_at = time.time()
            block.edit_history.append(revert_edit)
            block.edit_history = block.edit_history[-EDIT_HISTORY_MAX:]
            self._save_sync()
            return block

    # ------------------------------------------------------------------
    # First-run migration: pull existing user_memory.json _notes into the
    # human block as a one-shot. Cheap, no LLM — preserves what Reachy already
    # knows about the user without losing it on the schema change.
    # ------------------------------------------------------------------

    async def maybe_migrate_from_user_memory(self) -> None:
        if self._migration_done:
            return
        try:
            from app.services.reachy_user_memory_service import (
                get_reachy_user_memory_service,
            )
            mem = get_reachy_user_memory_service()
            notes = mem.list_notes()
        except Exception as e:
            logger.debug("memory_migration_skipped", error=str(e))
            return

        if not notes:
            self._migration_done = True
            self._save_sync()
            return

        # Group by category so the human block reads as a real profile, not
        # a flat dump.
        by_cat: dict[str, list[str]] = {}
        for n in notes:
            by_cat.setdefault(n.category, []).append(n.text)

        sections: list[str] = []
        order = ("preference", "fact", "topic", "correction")
        labels = {
            "preference": "Preferences",
            "fact": "Facts",
            "topic": "Recurring topics",
            "correction": "Corrections to remember",
        }
        for cat in order:
            items = by_cat.get(cat) or []
            if not items:
                continue
            sections.append(f"## {labels.get(cat, cat.capitalize())}")
            for item in items:
                sections.append(f"- {item}")
            sections.append("")

        body = "\n".join(sections).strip()
        if not body:
            self._migration_done = True
            self._save_sync()
            return

        await self.update_block(
            "human",
            body,
            by="migration",
            reason=f"migrated {len(notes)} notes from user_memory.json",
        )
        self._migration_done = True
        self._save_sync()
        logger.info("memory_blocks_migrated_from_user_memory", notes=len(notes))


# ----------------------------------------------------------------------
# Composer — single source of truth used by both voice paths.
# ----------------------------------------------------------------------


def compose_system_prompt(
    persona_id: str,
    *,
    working_context: str = "",
    include_voice_suffix: bool = True,
) -> str:
    """Compose the full system prompt sent to the LLM.

    Order:
        CORE_IDENTITY
        persona body (active persona's system_prompt + any user tweaks from
                      the persona block)
        human block       (durable facts)
        relationship block (shared shorthand)
        working_context  (per-turn calendar/sight/vault — caller-supplied)
        MOTION_TAG_INSTRUCTIONS
        VOICE_SUFFIX     (only when include_voice_suffix=True)

    ``working_context`` is the rendered "### CURRENT CONTEXT" block (already
    formatted) — voice loop builds it via ``reachy_context_service`` plus the
    Phase-3 vault retrieval lines. Pass empty string to skip.
    """
    store = ReachyMemoryBlockStore.get_instance()
    persona = get_persona(persona_id)
    parts: list[str] = [CORE_IDENTITY]

    # Persona body. Active persona's prompt + any user-tuning persisted in
    # the persona block.
    persona_body = persona.system_prompt if persona else ""
    persona_tweaks = (store.get_block("persona") or _DEFAULT_BLOCKS["persona"]).value
    if persona_body:
        parts.append(persona_body)
    if persona_tweaks:
        parts.append("### USER TUNING\n" + persona_tweaks)

    # Human block.
    human = (store.get_block("human") or _DEFAULT_BLOCKS["human"]).value
    if human:
        parts.append("### WHO YOU ARE TALKING TO\n" + human)

    # Relationship block.
    rel = (store.get_block("relationship") or _DEFAULT_BLOCKS["relationship"]).value
    if rel:
        parts.append("### YOUR HISTORY TOGETHER\n" + rel)

    # Working context (calendar, sight, vault chunks). Caller-formatted.
    wc = (working_context or "").strip()
    if wc:
        if not wc.startswith("###"):
            wc = "### CURRENT CONTEXT\n" + wc
        # Hard cap to keep prompt budget sane.
        if len(wc) > WORKING_CONTEXT_MAX_CHARS:
            wc = wc[:WORKING_CONTEXT_MAX_CHARS] + "\n…"
        parts.append(wc)

    parts.append(MOTION_TAG_INSTRUCTIONS.lstrip("\n"))
    if include_voice_suffix:
        parts.append(VOICE_SUFFIX.lstrip("\n"))

    return "\n\n".join(parts)


# ----------------------------------------------------------------------
# Module-level convenience wrappers
# ----------------------------------------------------------------------


def get_reachy_memory_blocks() -> ReachyMemoryBlockStore:
    return ReachyMemoryBlockStore.get_instance()


async def update_memory_block_tool(
    block: str,
    patch: str,
    reason: str,
    *,
    mode: str = "append",
) -> dict[str, Any]:
    """Tool entrypoint exposed to the model. Returns a small status dict.

    mode="append" (default) → ``append_to_block`` so the model only adds
                              facts, never rewrites history.
    mode="replace"           → ``update_block`` for the rare cases (e.g.
                              "the user changed their daughter's name") that
                              need a full rewrite.
    """
    store = get_reachy_memory_blocks()
    try:
        if mode == "replace":
            updated = await store.update_block(block, patch, by="reachy", reason=reason)
        else:
            updated = await store.append_to_block(block, patch, by="reachy", reason=reason)
        return {
            "ok": True,
            "block": block,
            "chars": len(updated.value),
            "max_chars": updated.max_chars,
        }
    except PermissionError as e:
        return {"ok": False, "error": str(e), "block": block}
    except Exception as e:
        logger.warning("update_memory_block_tool_failed", error=str(e), block=block)
        return {"ok": False, "error": str(e), "block": block}
