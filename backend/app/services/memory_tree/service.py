"""
Memory Vault service â€” public surface for callers.

Three operations:

    write_chunk(source, body, level=0, title=...)  â†’ append to L0
    summarize_source(source)  â†’ roll L0 chunks into an L1 summary
    write_global_digest(...)  â†’ store the daily global digest

    search(query, scope="source|topic|global", source=..., limit=10)

Search uses a lightweight in-process BM25-ish keyword scorer over chunk
bodies. It deliberately does not require pgvector because the vault is
designed to be inspectable on disk regardless of whether the DB is up. A
heavier semantic layer can be added later by indexing each .md file into
``EpisodicMemoryService`` (which already uses pgvector).
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog

from app.infrastructure.config import get_settings
from app.services.memory_tree.chunker import chunk_text
from app.services.memory_tree.vault import (
    VaultEntry,
    list_entries,
    read_entry,
    slugify,
    vault_root,
    write_chunk as _write_chunk,
    write_global_digest as _write_global_digest,
    write_topic as _write_topic,
)

logger = structlog.get_logger(__name__)


_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DATA_DIR = _DEFAULT_DATA_DIR
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SearchHit:
    path: Path
    score: float
    title: str
    source: str
    level: Optional[int]
    snippet: str


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _score_entry(entry: VaultEntry, query_tokens: list[str]) -> float:
    """Crude BM25-ish: sum of (1 + log(tf)) for each query token in body.

    Title matches are weighted x3. Heavier scoring belongs in pgvector; this
    keeps the vault self-contained for demos and offline reads.
    """
    body_tokens = _tokens(entry.body)
    title_tokens = _tokens(entry.frontmatter.get("title", ""))
    body_counts: dict[str, int] = {}
    for tok in body_tokens:
        body_counts[tok] = body_counts.get(tok, 0) + 1
    title_counts: dict[str, int] = {}
    for tok in title_tokens:
        title_counts[tok] = title_counts.get(tok, 0) + 1

    score = 0.0
    for qt in query_tokens:
        bc = body_counts.get(qt, 0)
        tc = title_counts.get(qt, 0)
        if bc:
            score += 1.0 + math.log(bc)
        if tc:
            score += 3.0 * (1.0 + math.log(tc))
    return score


def _snippet(body: str, query_tokens: list[str], window: int = 160) -> str:
    if not body:
        return ""
    lower = body.lower()
    best = 0
    for qt in query_tokens:
        idx = lower.find(qt)
        if idx >= 0:
            best = idx
            break
    start = max(0, best - window // 2)
    end = min(len(body), start + window)
    out = body[start:end].strip().replace("\n", " ")
    return ("..." if start > 0 else "") + out + ("..." if end < len(body) else "")


class MemoryTreeService:
    """Thin wrapper coordinating chunker + Memory Vault writers + searcher."""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            import app.services.memory_tree.service as _self_mod

            patched_data_dir = Path(_self_mod._DATA_DIR)
            if patched_data_dir != _DEFAULT_DATA_DIR:
                self._root = vault_root(patched_data_dir)
            else:
                settings = get_settings()
                self._root = (
                    Path(settings.vault_path) / "00_Meta" / "_agent" / "memory_vault"
                )
        else:
            # Tests pass a temporary base directory and retain the historical
            # <tmp>/vault layout for isolation.
            self._root = vault_root(data_dir)

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    async def write_chunk(
        self,
        source: str,
        body: str,
        *,
        level: int = 0,
        title: Optional[str] = None,
        tags: Optional[list[str]] = None,
        parent: Optional[str] = None,
    ) -> list[Path]:
        """Chunk and write a body to ``sources/{source}/L{level}/``.

        Returns the paths written (one per chunk).
        """
        if not body or not body.strip():
            return []
        chunks = chunk_text(body)
        if not chunks:
            return []
        return await asyncio.get_event_loop().run_in_executor(
            None,
            self._write_chunks_sync,
            source,
            level,
            title,
            chunks,
            tags,
            parent,
        )

    def _write_chunks_sync(
        self,
        source: str,
        level: int,
        title: Optional[str],
        chunks,
        tags,
        parent,
    ) -> list[Path]:
        paths: list[Path] = []
        for i, ch in enumerate(chunks):
            chunk_title = title or f"{source} L{level} part {i+1}"
            p = _write_chunk(
                self._root,
                source=source,
                level=level,
                title=chunk_title,
                body=ch.text,
                tags=tags,
                parent=parent,
                extra_meta={"part": i + 1, "of": len(chunks)},
            )
            paths.append(p)
        logger.info(
            "memory_vault_wrote_chunks",
            source=source,
            level=level,
            chunks=len(chunks),
        )
        return paths

    async def write_topic(
        self,
        entity: str,
        body: str,
        *,
        title: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> Path:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: _write_topic(
                self._root,
                entity=entity,
                title=title or entity,
                body=body,
                tags=tags,
            ),
        )

    async def write_global_digest(
        self,
        body: str,
        *,
        title: str = "Daily digest",
        sources: Optional[list[str]] = None,
    ) -> Path:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: _write_global_digest(
                self._root,
                title=title,
                body=body,
                sources=sources,
            ),
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        scope: Optional[str] = None,
        source: Optional[str] = None,
        entity: Optional[str] = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Keyword search across the vault. ``scope`` âˆˆ {None, source, topic, global}."""
        if not query.strip():
            return []
        return await asyncio.get_event_loop().run_in_executor(
            None,
            self._search_sync,
            query,
            scope,
            source,
            entity,
            limit,
        )

    def _search_sync(
        self,
        query: str,
        scope: Optional[str],
        source: Optional[str],
        entity: Optional[str],
        limit: int,
    ) -> list[SearchHit]:
        tokens = _tokens(query)
        if not tokens:
            return []
        entries = list_entries(
            self._root,
            source=source,
            entity=entity,
            scope=scope,
        )
        hits: list[SearchHit] = []
        for entry in entries:
            score = _score_entry(entry, tokens)
            if score <= 0:
                continue
            level_raw = entry.frontmatter.get("level")
            try:
                level = int(level_raw) if level_raw is not None else None
            except (TypeError, ValueError):
                level = None
            hits.append(
                SearchHit(
                    path=entry.path,
                    score=score,
                    title=entry.frontmatter.get("title", entry.path.stem),
                    source=entry.frontmatter.get("source", entry.frontmatter.get("entity", "global")),
                    level=level,
                    snippet=_snippet(entry.body, tokens),
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    # ------------------------------------------------------------------
    # Stats / listing (for the UI page)
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Counts per scope/source for the MemoryVault UI."""
        sources: dict[str, dict[str, int]] = {}
        src_root = self._root / "sources"
        if src_root.exists():
            for src_dir in src_root.iterdir():
                if not src_dir.is_dir():
                    continue
                buckets: dict[str, int] = {}
                for lvl_dir in src_dir.iterdir():
                    if not lvl_dir.is_dir():
                        continue
                    buckets[lvl_dir.name] = sum(1 for _ in lvl_dir.glob("*.md"))
                sources[src_dir.name] = buckets

        topics: dict[str, int] = {}
        topic_root = self._root / "topics"
        if topic_root.exists():
            for ent_dir in topic_root.iterdir():
                if not ent_dir.is_dir():
                    continue
                topics[ent_dir.name] = sum(1 for _ in ent_dir.glob("*.md"))

        global_count = 0
        global_root = self._root / "global"
        if global_root.exists():
            global_count = sum(1 for _ in global_root.glob("*.md"))

        return {
            "sources": sources,
            "topics": topics,
            "global_count": global_count,
            "root": str(self._root),
        }

    @property
    def root(self) -> Path:
        return self._root


@lru_cache(maxsize=1)
def get_memory_tree() -> MemoryTreeService:
    return MemoryTreeService()
