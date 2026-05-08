"""Vault Indexer — incremental markdown -> pgvector + tsvector pipeline.

Every tick:
  1. Walk the vault (skip .obsidian, .git, .trash, 90_Archive).
  2. Hash each .md file. Skip unchanged. Track deleted files (orphan sweep).
  3. For changed files: parse frontmatter, split by heading hierarchy into
     ~512-token chunks preserving `[[wikilinks]]`, upsert into vault_chunks.
  4. Embed each new chunk via the shared LiteLLM embedder (qwen3-embed).

Partition rules (drive retrieval weighting):
    10_Atlas/**, 40_Resources/**  -> reference
    30_Efforts/**                 -> projects
    20_Calendar/Daily|Weekly/**   -> journal      (time-decay applied here only)
    _Inbox/**                     -> inbox
    00_Meta/_agent/**             -> inbox (ephemeral agent output)

This is Phase 2 of the SecondBrain plan. It writes to vault_chunks; retrieval
lives in vault_retrieval_service. No Obsidian Local REST API involvement — the
indexer reads straight from the filesystem so it keeps working when Obsidian
is closed.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog
import yaml
from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import VaultChunkModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.infrastructure.ollama_client import get_llm_client

logger = structlog.get_logger(__name__)


_SKIP_DIR_PARTS = {".obsidian", ".git", ".trash", "90_Archive", "node_modules"}
_MAX_CHUNK_CHARS = 2000  # ~500 tokens with overlap
_OVERLAP_CHARS = 240
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _partition_for(rel_path: Path) -> str:
    parts = rel_path.parts
    if not parts:
        return "inbox"
    head = parts[0]
    if head in ("10_Atlas", "40_Resources"):
        return "reference"
    if head == "30_Efforts":
        return "projects"
    if head == "20_Calendar":
        return "journal"
    if head == "_Inbox":
        return "inbox"
    if head == "00_Meta" and len(parts) >= 2 and parts[1] == "_agent":
        return "inbox"
    return "reference"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass
class _Chunk:
    idx: int
    heading_path: str
    content: str
    token_count: int


def _json_safe(obj: Any) -> Any:
    """Coerce YAML-parsed values (dates, datetimes, sets) to JSON-serializable types."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):  # date / datetime / time
        return obj.isoformat()
    return obj


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            fm = {}
        return _json_safe(fm), m.group(2)
    except yaml.YAMLError:
        return {}, text


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """Return [(heading_path, body), ...]. Heading path is '> '-joined h1/h2/...."""
    sections: list[tuple[str, str]] = []
    cur_path: list[tuple[int, str]] = []
    buf: list[str] = []
    current_heading_path = ""

    def flush():
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            sections.append((current_heading_path, body))
        buf = []

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2)
            cur_path = [(lvl, t) for lvl, t in cur_path if lvl < level]
            cur_path.append((level, title))
            current_heading_path = " > ".join(t for _, t in cur_path)
            continue
        buf.append(line)
    flush()
    return sections


def _chunk_section(heading_path: str, body: str) -> list[_Chunk]:
    """Token-cap chunks from a heading section. Small sections stay whole."""
    body = body.strip()
    if not body:
        return []
    if len(body) <= _MAX_CHUNK_CHARS:
        return [_Chunk(idx=0, heading_path=heading_path, content=body, token_count=len(body) // 4)]
    chunks: list[_Chunk] = []
    start = 0
    idx = 0
    step = _MAX_CHUNK_CHARS - _OVERLAP_CHARS
    while start < len(body):
        end = min(start + _MAX_CHUNK_CHARS, len(body))
        slice_ = body[start:end]
        # try to break at sentence boundary
        if end < len(body):
            last_nl = slice_.rfind("\n\n")
            if last_nl > _MAX_CHUNK_CHARS // 2:
                end = start + last_nl
                slice_ = body[start:end]
        chunks.append(_Chunk(idx=idx, heading_path=heading_path, content=slice_.strip(), token_count=len(slice_) // 4))
        idx += 1
        if end >= len(body):
            break
        start += step
    return chunks


def _iter_markdown(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.md"):
        if any(part in _SKIP_DIR_PARTS for part in p.relative_to(root).parts):
            continue
        yield p


class VaultIndexerService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._root = Path(self._settings.vault_path)
        self._embed_dim = 1024  # pgvector column dim; Matryoshka-truncate to 512 for journal below

    def available(self) -> bool:
        return self._root.is_dir()

    async def _embed(self, text: str) -> Optional[list[float]]:
        """Embed via the shared LiteLLM embedder. Returns None on failure."""
        try:
            client = get_llm_client()
            vec = await client.embed(text, max_retries=1)
            if not vec:
                return None
            # Ensure we fit the vector(1024) column. vLLM returns 1024; Matryoshka-truncate
            # anything longer and pad shorter (shouldn't happen with Qwen3-Embedding).
            if len(vec) > self._embed_dim:
                vec = vec[: self._embed_dim]
            elif len(vec) < self._embed_dim:
                vec = vec + [0.0] * (self._embed_dim - len(vec))
            return vec
        except Exception as e:  # noqa: BLE001
            logger.warning("vault_embed_failed", error=str(e))
            return None

    async def reindex(self, *, force: bool = False, max_files: int = 500) -> dict[str, Any]:
        """Scan vault, upsert changed files, drop orphaned chunks."""
        if not self.available():
            return {"status": "skipped", "reason": "vault_unavailable", "path": str(self._root)}

        scanned = 0
        files_changed = 0
        chunks_written = 0
        chunks_deleted = 0

        # Build a set of live paths for orphan detection.
        live_paths: set[str] = set()

        for fp in _iter_markdown(self._root):
            if scanned >= max_files:
                break
            scanned += 1
            rel = fp.relative_to(self._root).as_posix()
            live_paths.add(rel)
            try:
                raw = fp.read_bytes()
            except Exception:  # noqa: BLE001
                continue
            file_hash = _sha256_bytes(raw)

            # Skip unchanged files unless forced
            if not force:
                async with get_session() as session:
                    result = await session.execute(
                        select(VaultChunkModel.content_hash)
                        .where(VaultChunkModel.path == rel)
                        .limit(1)
                    )
                    existing_hash = result.scalar_one_or_none()
                if existing_hash and existing_hash.startswith(file_hash[:16]):
                    continue

            files_changed += 1
            written = await self._index_file(fp, rel, raw, file_hash)
            chunks_written += written

        # Orphan sweep: remove chunks whose source file no longer exists.
        async with get_session() as session:
            result = await session.execute(select(VaultChunkModel.path).distinct())
            db_paths = {p for (p,) in result.all()}
            orphans = db_paths - live_paths
            if orphans:
                await session.execute(
                    delete(VaultChunkModel).where(VaultChunkModel.path.in_(orphans))
                )
                await session.commit()
                chunks_deleted = len(orphans)

        logger.info(
            "vault_reindex",
            scanned=scanned,
            files_changed=files_changed,
            chunks_written=chunks_written,
            chunks_deleted=chunks_deleted,
        )
        return {
            "status": "ok",
            "scanned": scanned,
            "files_changed": files_changed,
            "chunks_written": chunks_written,
            "chunks_deleted": chunks_deleted,
        }

    async def _index_file(self, fp: Path, rel: str, raw: bytes, file_hash: str) -> int:
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return 0
        fm, body = _parse_frontmatter(text)
        partition_override = (fm or {}).get("partition")
        partition = partition_override if isinstance(partition_override, str) else _partition_for(Path(rel))
        tags = []
        raw_tags = (fm or {}).get("tags")
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags if t]
        elif isinstance(raw_tags, str):
            tags = [raw_tags]

        mtime = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)

        # Split + chunk
        sections = _split_by_headings(body)
        all_chunks: list[_Chunk] = []
        global_idx = 0
        for heading_path, section_body in sections:
            for ch in _chunk_section(heading_path, section_body):
                ch.idx = global_idx
                all_chunks.append(ch)
                global_idx += 1
        if not all_chunks and body.strip():
            # file with no headings; treat as one chunk
            all_chunks = [_Chunk(idx=0, heading_path="", content=body.strip(), token_count=len(body) // 4)]

        # Wipe prior chunks for this path (simpler + correct vs per-chunk upsert).
        async with get_session() as session:
            await session.execute(delete(VaultChunkModel).where(VaultChunkModel.path == rel))
            await session.commit()

        written = 0
        for chunk in all_chunks:
            embedding = await self._embed(chunk.content)
            chunk_hash = _sha256_bytes(chunk.content.encode("utf-8"))
            # content_hash per chunk stores file_hash[:16] + chunk_hash[:16] so
            # reindex-skip in reindex() can check any chunk row for the file hash.
            content_hash = file_hash[:16] + chunk_hash[:16]
            row = VaultChunkModel(
                id=uuid.uuid4().hex[:16] + str(chunk.idx).zfill(4),
                path=rel,
                partition=partition,
                chunk_idx=chunk.idx,
                heading_path=chunk.heading_path or None,
                content=chunk.content,
                content_hash=content_hash,
                token_count=chunk.token_count,
                tags=tags,
                frontmatter=fm if fm else None,
                embedding=embedding,
                file_mtime=mtime,
            )
            async with get_session() as session:
                session.add(row)
                await session.commit()
            written += 1
        return written


_singleton: Optional[VaultIndexerService] = None


def get_vault_indexer() -> VaultIndexerService:
    global _singleton
    if _singleton is None:
        _singleton = VaultIndexerService()
    return _singleton
