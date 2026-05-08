"""
Reachy memory router — read + edit Letta-style memory blocks, list edit
history, browse personality-history snapshots from the vault.

All endpoints are auth-gated. The frontend Memory page (Phase 5) consumes
these to render the user's editing surface.

  GET    /api/reachy/memory/blocks                  list all blocks
  GET    /api/reachy/memory/blocks/{label}          read one block + history
  PUT    /api/reachy/memory/blocks/{label}          replace block (user)
  POST   /api/reachy/memory/blocks/{label}/append   append to block (user)
  POST   /api/reachy/memory/blocks/{label}/revert   revert to a prior edit
  GET    /api/reachy/memory/history                 list snapshot files
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.infrastructure.config import get_settings
from app.services.reachy_memory_blocks import (
    USER_EDITABLE,
    VALID_LABELS,
    get_reachy_memory_blocks,
)

logger = structlog.get_logger()

router = APIRouter()


# ---------------------------------------------------------------- schemas


class BlockUpdate(BaseModel):
    value: str = Field(..., description="New full text of the block.")
    reason: str = Field("", description="Optional note about why this changed.")


class BlockAppend(BaseModel):
    addendum: str = Field(..., description="Line / paragraph to append.")
    reason: str = Field("", description="Optional note about why this was added.")


class BlockRevert(BaseModel):
    edit_index: int = Field(
        -1,
        description=(
            "Edit-history index. Negative is supported (-1 = most recent "
            "edit, -2 = prior, …)."
        ),
    )


# ---------------------------------------------------------------- helpers


def _block_to_dict(block, *, include_history: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "label": block.label,
        "value": block.value,
        "max_chars": block.max_chars,
        "chars": len(block.value),
        "last_updated_by": block.last_updated_by,
        "last_updated_at": block.last_updated_at,
        "user_editable": block.label in USER_EDITABLE,
    }
    if include_history:
        out["edit_history"] = [
            {
                "ts": e.ts,
                "by": e.by,
                "reason": e.reason,
                "previous_value": e.previous_value,
                "new_value": e.new_value,
            }
            for e in block.edit_history
        ]
    return out


def _validate_persistable_label(label: str) -> None:
    if label not in VALID_LABELS:
        raise HTTPException(404, f"unknown block: {label}")
    if label == "working_context":
        raise HTTPException(
            400,
            "working_context is built per-turn and not directly persistable",
        )


# ---------------------------------------------------------------- endpoints


@router.get("/blocks")
async def list_blocks(_user: str = Depends(require_auth)) -> dict[str, Any]:
    store = get_reachy_memory_blocks()
    blocks = store.list_blocks()
    return {
        "blocks": [
            _block_to_dict(b, include_history=False) for b in blocks.values()
        ]
    }


@router.get("/blocks/{label}")
async def get_block(label: str, _user: str = Depends(require_auth)) -> dict[str, Any]:
    _validate_persistable_label(label)
    store = get_reachy_memory_blocks()
    block = store.get_block(label)
    if not block:
        raise HTTPException(404, f"block not found: {label}")
    return _block_to_dict(block, include_history=True)


@router.put("/blocks/{label}")
async def update_block(
    label: str,
    payload: BlockUpdate,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    _validate_persistable_label(label)
    if label not in USER_EDITABLE:
        raise HTTPException(403, f"block {label} is not user-editable")
    store = get_reachy_memory_blocks()
    block = await store.update_block(
        label, payload.value, by="user", reason=payload.reason or ""
    )
    return _block_to_dict(block, include_history=True)


@router.post("/blocks/{label}/append")
async def append_block(
    label: str,
    payload: BlockAppend,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    _validate_persistable_label(label)
    if label not in USER_EDITABLE:
        raise HTTPException(403, f"block {label} is not user-editable")
    store = get_reachy_memory_blocks()
    block = await store.append_to_block(
        label, payload.addendum, by="user", reason=payload.reason or ""
    )
    return _block_to_dict(block, include_history=True)


@router.post("/blocks/{label}/revert")
async def revert_block(
    label: str,
    payload: BlockRevert,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    _validate_persistable_label(label)
    store = get_reachy_memory_blocks()
    try:
        block = await store.revert_block(label, payload.edit_index)
    except (ValueError, IndexError) as e:
        raise HTTPException(400, str(e))
    return _block_to_dict(block, include_history=True)


@router.get("/history")
async def list_history(_user: str = Depends(require_auth)) -> dict[str, Any]:
    """List personality-history snapshots written by the nightly synthesis
    job under ``00_Meta/_agent/reachy/personality-history/``. Returns newest
    first.
    """
    settings = get_settings()
    base = Path(settings.vault_path) / "00_Meta" / "_agent" / "reachy" / "personality-history"
    if not base.is_dir():
        return {"snapshots": [], "vault_path": str(base)}
    items = []
    for f in sorted(base.glob("*.md"), reverse=True):
        try:
            stat = f.stat()
        except OSError:
            continue
        items.append(
            {
                "filename": f.name,
                "date": f.stem,
                "bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return {"snapshots": items, "vault_path": str(base)}


@router.get("/history/{filename}")
async def get_history_snapshot(
    filename: str,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    """Read one snapshot file. Filename is the stem-with-extension as listed."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    settings = get_settings()
    target = (
        Path(settings.vault_path)
        / "00_Meta"
        / "_agent"
        / "reachy"
        / "personality-history"
        / filename
    )
    if not target.is_file():
        raise HTTPException(404, "snapshot not found")
    try:
        body = target.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"read failed: {e}")
    return {"filename": filename, "content": body, "bytes": len(body)}
