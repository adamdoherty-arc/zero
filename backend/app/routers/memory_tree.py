"""
Memory Vault API.

Surfaces the Obsidian-compatible vault to the Memory Vault UI page and to the
agent so it can search its own memory. Direct HTTP writes are side-effect
surfaces, so they create approval requests instead of writing immediately.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.memory_tree import get_memory_tree
from app.services.side_effect_gate import queue_side_effect_approval

router = APIRouter()


class ChunkWriteRequest(BaseModel):
    source: str
    body: str
    level: int = Field(0, ge=0, le=3)
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    parent: Optional[str] = None


class GlobalDigestRequest(BaseModel):
    body: str
    title: str = "Daily digest"
    sources: Optional[list[str]] = None


@router.get("/stats")
async def stats():
    return get_memory_tree().stats()


@router.get("/search")
async def search(
    q: str,
    scope: Optional[str] = None,
    source: Optional[str] = None,
    entity: Optional[str] = None,
    limit: int = 10,
):
    """Keyword search. ``scope`` is one of source, topic, global, or empty."""
    tree = get_memory_tree()
    hits = await tree.search(
        q,
        scope=scope if scope in {"source", "topic", "global"} else None,
        source=source,
        entity=entity,
        limit=limit,
    )
    return {
        "query": q,
        "hits": [
            {
                "path": str(h.path.relative_to(tree.root)),
                "title": h.title,
                "source": h.source,
                "level": h.level,
                "score": round(h.score, 3),
                "snippet": h.snippet,
            }
            for h in hits
        ],
    }


@router.get("/entry")
async def entry(path: str):
    """Read a single vault entry by relative path."""
    from app.services.memory_tree.vault import read_entry

    tree = get_memory_tree()
    root = tree.root.resolve()
    abs_path = (root / path).resolve()
    try:
        abs_path.relative_to(root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path outside vault") from e
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="entry not found")
    item = read_entry(abs_path)
    if item is None:
        raise HTTPException(status_code=500, detail="failed to read entry")
    return {
        "path": str(abs_path.relative_to(root)),
        "frontmatter": item.frontmatter,
        "body": item.body,
    }


@router.post("/chunks")
async def write_chunk(req: ChunkWriteRequest):
    return await queue_side_effect_approval(
        tool_name="memory_vault.write_chunk",
        tier="write_local",
        summary=f"Write Memory Vault chunk from {req.source}",
        arguments=req.model_dump(),
    )


@router.post("/global-digest")
async def write_global_digest(req: GlobalDigestRequest):
    return await queue_side_effect_approval(
        tool_name="memory_vault.write_global_digest",
        tier="write_local",
        summary=f"Write Memory Vault global digest: {req.title}",
        arguments=req.model_dump(),
    )
