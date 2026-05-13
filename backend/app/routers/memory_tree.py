"""
Memory Tree API.

Surfaces the Obsidian-compatible vault to the MemoryVault UI page and to the
agent (so it can search its own memory).

  GET  /api/memory-tree/stats              → counts per source / topic / global
  GET  /api/memory-tree/search?q=...       → keyword search across the vault
  GET  /api/memory-tree/entry?path=...     → fetch a single chunk by path
  POST /api/memory-tree/chunks             → write a chunk (caller-side automation)
  POST /api/memory-tree/global-digest      → write today's global digest
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.memory_tree import get_memory_tree

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
    """Keyword search. ``scope`` ∈ {source, topic, global, ''}."""
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
    abs_path = (tree.root / path).resolve()
    # Don't let callers escape the vault root.
    try:
        abs_path.relative_to(tree.root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path outside vault") from e
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="entry not found")
    item = read_entry(abs_path)
    if item is None:
        raise HTTPException(status_code=500, detail="failed to read entry")
    return {
        "path": str(abs_path.relative_to(tree.root)),
        "frontmatter": item.frontmatter,
        "body": item.body,
    }


@router.post("/chunks")
async def write_chunk(req: ChunkWriteRequest):
    tree = get_memory_tree()
    paths = await tree.write_chunk(
        req.source,
        req.body,
        level=req.level,
        title=req.title,
        tags=req.tags,
        parent=req.parent,
    )
    root = tree.root
    return {
        "count": len(paths),
        "paths": [str(Path(p).relative_to(root)) for p in paths],
    }


@router.post("/global-digest")
async def write_global_digest(req: GlobalDigestRequest):
    tree = get_memory_tree()
    path = await tree.write_global_digest(
        req.body, title=req.title, sources=req.sources
    )
    return {"path": str(path.relative_to(tree.root))}
