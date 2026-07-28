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
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import VaultChunkModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.infrastructure.ollama_client import get_llm_client

logger = structlog.get_logger(__name__)


_SKIP_DIR_PARTS = {".obsidian", ".git", ".trash", "90_Archive", "node_modules"}
_MAX_CHUNK_CHARS = 2000  # ~500 tokens with overlap
_OVERLAP_CHARS = 240

# IDX-7 (supervise 6a1563fd): a heading section whose body is a single
# boilerplate line was still chunked, embedded and indexed. Measured on the live
# index: 17,914 of 101,484 chunks (17.7%) were under 40 chars, and the top two
# were `**Status:** `success`` (10,391 copies) and `**Status:** `failure``
# (5,283) emitted by the auto-generated loop-run notes under
# `00_Meta/_agent/loops/`. Identical text embeds to an identical vector, so
# those two strings alone collapsed ~15% of the corpus onto TWO points in the
# embedding space — and because the dense side of `search()` has no similarity
# floor, they filled the nearest-neighbour list for almost any query (measured:
# 40/40 of the dense top-40 for both "GTD weekly review" and "ADA trading
# strategy"). Every one of the 12 most common sub-40-char chunks was
# content-free boilerplate (```bash, "- None", "_(no tasks yet)_", ...).
#
# The floor is measured on markdown-STRIPPED text so the decision is about
# retrievable signal rather than formatting: `**Status:** `success`` carries 14
# signal chars, while a genuinely short but meaningful line is judged on its
# real words. Tunable because the right cut depends on a vault's writing style.
_MIN_CHUNK_SIGNAL_CHARS = 20

# Markdown decoration that carries no retrieval signal on its own.
_MD_DECORATION_RE = re.compile(r"[*_`~#>\[\]()!|+-]|\s+")
# IDX-FM-NOEOL (supervise f8574c6d): the trailing `\n` after the closing `---`
# was mandatory, so a pure-frontmatter note whose bytes end at `---` (no body,
# no trailing newline) failed to match — its frontmatter (tags, partition
# override) was silently dropped and a path-derived partition used instead.
# Make the leading-newline + body group optional.
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n(.*))?$", re.DOTALL)


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


_VALID_PARTITIONS = frozenset({"reference", "projects", "journal", "inbox"})


def _resolve_partition(partition_override: object, rel: str) -> str:
    """Resolve the *retrieval* partition for a chunk.

    IDX-PARTITION (supervise 3c3ade8e): a note's frontmatter ``partition`` is the
    *privacy/domain* taxonomy (``personal | trading | zero-dev``, with ``work``
    hard-dropped per the vault constitution). ``vault_chunks.partition`` is the
    distinct *retrieval* taxonomy (``reference | projects | journal | inbox``)
    that ``vault_retrieval_service.search()`` filters on (and ``journal`` alone
    receives the time-decay boost). IDX-FM-NOEOL made the frontmatter override
    take effect, which then leaked the privacy taxonomy into the retrieval column
    (~83% of chunks were stored as ``personal``), so partition-filtered retrieval
    and the journal time-decay silently missed those notes. Only honour an
    override that is already a valid retrieval partition; otherwise derive it from
    the path.

    RET-01 (supervise zero 6a8c5562): this docstring used to claim the path
    fallback "enforces the constitution's ``work`` hard-drop". It does not, and
    the claim was load-bearing enough that the accompanying test was named
    ``test_work_override_is_hard_dropped_via_path_fallback`` while asserting the
    note is indexed as ``reference``. **Rejecting an override is not dropping a
    note.** A note whose frontmatter says ``partition: work`` still gets chunked,
    embedded, stored, and returned by search — it just lands in a path-derived
    bucket. The real drop is enforced by the caller (``_index_file``); this
    function only chooses a retrieval bucket for a note that IS being indexed.
    """
    if isinstance(partition_override, str) and partition_override in _VALID_PARTITIONS:
        return partition_override
    return _partition_for(Path(rel))


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
    """Split a note into (frontmatter dict, body).

    IDX-2 (supervise fc9c5829): _FRONTMATTER_RE anchors on a literal ``\\n`` after
    the opening ``---``, so a note saved with CRLF line endings ("---\\r\\n") never
    matched and this returned ``({}, full_text)``. 380 of 17,723 live vault notes
    were in that state, with two silent consequences: tags and the ``partition``
    override were dropped and the raw YAML block was indexed as body prose, and —
    more seriously — ``_index_file``'s ``work`` hard-drop reads ``fm["partition"]``,
    so a CRLF note tagged ``partition: work`` bypassed the constitution's drop
    entirely. Normalize line endings here, at the parser boundary, so every caller
    (and the body handed to the chunker) sees one form.
    """
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            fm = {}
        # group(2) is None when the note is frontmatter-only (no body) — coerce
        # to "" so callers always get a str (IDX-FM-NOEOL).
        return _json_safe(fm), (m.group(2) or "")
    except yaml.YAMLError:
        return {}, text


_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})")


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """Return [(heading_path, body), ...]. Heading path is '> '-joined h1/h2/....

    IDX-3 (supervise fc9c5829): this splitter had no fenced-code-block awareness,
    so any line inside a ``` block that began with 1-6 `#` and a space — a shell
    comment, a Python `# TODO`, markdown-inside-markdown — was treated as a real
    heading. It flushed the section mid-code-block, cutting one logical unit into
    several chunks and writing a bogus `heading_path` onto each. Live exposure at
    the time of the fix: 9,651 false headings across 1,954 of 17,723 vault notes
    (the plan/session archives are code-dense), corrupting both chunk boundaries
    and the heading metadata retrieval ranks on. Track fence state and skip
    heading detection inside fences.
    """
    sections: list[tuple[str, str]] = []
    cur_path: list[tuple[int, str]] = []
    buf: list[str] = []
    current_heading_path = ""
    in_fence = False

    def flush():
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            sections.append((current_heading_path, body))
        buf = []

    for line in text.splitlines():
        if _FENCE_RE.match(line):
            # Toggle on any fence marker. An unterminated fence keeps the rest of
            # the note fenced, which is the safe direction: it preserves the text
            # verbatim under the last real heading instead of inventing new ones.
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
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


def _signal_len(text: str) -> int:
    """Length of ``text`` once markdown decoration and whitespace are removed.

    IDX-7: used to decide whether a chunk carries enough retrievable signal to
    be worth embedding. ``**Status:** `success``` measures 14 here, not 21.
    """
    return len(_MD_DECORATION_RE.sub("", text))


def _is_indexable(content: str) -> bool:
    """IDX-7: reject chunks that are pure boilerplate/formatting."""
    return _signal_len(content) >= _MIN_CHUNK_SIGNAL_CHARS


def _chunk_section(heading_path: str, body: str) -> list[_Chunk]:
    """Token-cap chunks from a heading section. Small sections stay whole."""
    body = body.strip()
    if not body:
        return []
    if len(body) <= _MAX_CHUNK_CHARS:
        if not _is_indexable(body):
            return []
        return [_Chunk(idx=0, heading_path=heading_path, content=body, token_count=len(body) // 4)]
    chunks: list[_Chunk] = []
    start = 0
    idx = 0
    while start < len(body):
        end = min(start + _MAX_CHUNK_CHARS, len(body))
        slice_ = body[start:end]
        # try to break at a paragraph boundary
        if end < len(body):
            last_nl = slice_.rfind("\n\n")
            if last_nl > _MAX_CHUNK_CHARS // 2:
                end = start + last_nl
                slice_ = body[start:end]
        chunks.append(_Chunk(idx=idx, heading_path=heading_path, content=slice_.strip(), token_count=len(slice_) // 4))
        idx += 1
        if end >= len(body):
            break
        # Fix-118 (IDX-B): advance from the ACTUAL end (minus overlap), not a
        # fixed step from `start`. When `end` was pulled back to a paragraph
        # boundary (last_nl < _MAX_CHUNK_CHARS), the old `start += step`
        # (step=_MAX-_OVERLAP) jumped PAST the boundary, leaving the bytes
        # between the boundary and start+step in NO chunk — up to
        # (_MAX_CHUNK_CHARS - _OVERLAP_CHARS - last_nl) chars silently dropped
        # from the index for every large section. max(start+1, ...) guarantees
        # forward progress.
        start = max(start + 1, end - _OVERLAP_CHARS)
    # IDX-7: the tail slice of a long section can still be a boilerplate
    # fragment; re-index the survivors so `idx` stays gap-free.
    kept = [c for c in chunks if _is_indexable(c.content)]
    for new_idx, chunk in enumerate(kept):
        chunk.idx = new_idx
    return kept


def _iter_markdown(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.md"):
        if any(part in _SKIP_DIR_PARTS for part in p.relative_to(root).parts):
            continue
        yield p


class VaultIndexerService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._root = Path(self._settings.vault_path)
        # Fix-109: match the shared embedder's actual output dim
        # (settings.embedding_dimension, default 768) and the vault_chunks.embedding
        # Vector(768) column. Was hardcoded 1024 (Qwen3 full-dim), but the embedder
        # truncates to 768 and the column was migrated to Vector(768) — so the 1024
        # guard rejected EVERY 768-dim vector, storing NULL and silently degrading
        # dense retrieval to BM25-only (324/1267 chunks already NULL).
        self._embed_dim = self._settings.embedding_dimension
        # IDX-REINDEX-2: serialize reindex passes. The scheduler's
        # _run_vault_reindex_tick and a manual POST /reindex (or two manual
        # calls) otherwise run delete-then-insert per path concurrently, which
        # either UniqueViolation-aborts on ux_vault_chunks_path_idx or writes
        # duplicate chunk rows. Only one pass runs at a time.
        self._reindex_lock = asyncio.Lock()
        # IDX-4: rel_path -> file_hash for files that legitimately produce zero
        # chunks (empty body after frontmatter). These never persist a
        # VaultChunkModel row, so the row-derived unchanged-file skip can never
        # match them. Process-local by design: it is a work-avoidance cache, not
        # state — a restart just re-does one no-op pass per empty file.
        self._empty_hashes: dict[str, str] = {}

    def available(self) -> bool:
        return self._root.is_dir()

    async def _embed(self, text: str) -> Optional[list[float]]:
        """Embed via the shared LiteLLM embedder. Returns None on failure."""
        try:
            client = get_llm_client()
            vec = await client.embed(text, max_retries=1)
            if not vec:
                return None
            # Fix-96: mirror the query-side dim guard (vault_retrieval_service
            # _embed_query, Fix-93). Silently truncating/zero-padding to 1024
            # stored garbage vectors whenever the embedder's native dim != 1024,
            # while the query side already rejects the mismatch — an
            # index/retrieve asymmetry that left dense retrieval permanently
            # broken. Reject loudly and store NULL (BM25-only) instead, so both
            # sides stay consistent.
            if len(vec) != self._embed_dim:
                logger.warning(
                    "vault_embed_dim_mismatch",
                    got=len(vec),
                    expected=self._embed_dim,
                )
                return None
            return vec
        except Exception as e:  # noqa: BLE001
            logger.warning("vault_embed_failed", error=str(e))
            return None

    async def reindex(self, *, force: bool = False, max_files: int = 500) -> dict[str, Any]:
        """Serialized entrypoint (IDX-REINDEX-2): only one reindex pass runs at
        a time. A second concurrent call is skipped rather than queued so
        every-2-min ticks can't pile up behind a slow embed pass."""
        if self._reindex_lock.locked():
            logger.info("vault_reindex_already_running_skipped")
            return {"status": "skipped", "reason": "reindex_in_progress"}
        async with self._reindex_lock:
            return await self._reindex_impl(force=force, max_files=max_files)

    async def _reindex_impl(self, *, force: bool = False, max_files: int = 500) -> dict[str, Any]:
        """Scan vault, upsert changed files, drop orphaned chunks."""
        if not self.available():
            return {"status": "skipped", "reason": "vault_unavailable", "path": str(self._root)}

        scanned = 0
        files_changed = 0
        chunks_written = 0
        chunks_deleted = 0
        orphan_paths = 0  # IDX-6
        unreadable = 0  # IDX-5

        # Build a set of live paths for orphan detection.
        live_paths: set[str] = set()

        # Fix-118 (IDX-A): the cap must bound the EXPENSIVE re-embed work, NOT
        # the cheap directory walk. The old loop did `scanned += 1` for every
        # file it touched and broke at `scanned >= max_files`, so on a 14.8k-file
        # vault the every-2-min tick (max_files=200) re-walked the SAME first 200
        # paths (deterministic rglob order) forever — ~96% of the vault was NEVER
        # indexed and stayed BM25+dense blind. Now we walk the WHOLE tree every
        # tick (change-detection is cheap), prefetch existing (hash, has-null) in
        # ONE grouped query instead of two SELECTs per file, and cap only the
        # number of files actually re-embedded.
        existing: dict[str, tuple[str | None, bool]] = {}
        if not force:
            async with get_session() as session:
                rows = await session.execute(
                    select(
                        VaultChunkModel.path,
                        func.min(VaultChunkModel.content_hash),
                        func.bool_or(VaultChunkModel.embedding.is_(None)),
                    ).group_by(VaultChunkModel.path)
                )
                for path, chash, has_null in rows.all():
                    existing[path] = (chash, bool(has_null))

        reindexed = 0
        capped = False
        # IDX-ASYNC-WALK (supervise f8574c6d): _iter_markdown drives a synchronous
        # Path.rglob over the whole vault (~14.8k files); iterating it directly on
        # the event loop stalls concurrent coroutines (voice path, HTTP handlers,
        # scheduler) for the duration of the directory walk. Materialize the path
        # list off-thread so only the embedding awaits run on the loop.
        md_paths = await asyncio.to_thread(lambda: list(_iter_markdown(self._root)))
        for fp in md_paths:
            rel = fp.relative_to(self._root).as_posix()
            live_paths.add(rel)
            scanned += 1
            try:
                raw = fp.read_bytes()
            except Exception as e:  # noqa: BLE001
                # IDX-5 (supervise fc9c5829): this skip was completely silent —
                # an unreadable file (locked handle, un-hydrated cloud placeholder,
                # permission error) was indistinguishable from an unchanged one in
                # every log, counter, and API response, so a chronically failing
                # file could never be discovered. It is still retried next tick.
                unreadable += 1
                logger.warning("vault_index_unreadable", path=rel, error=str(e))
                continue
            file_hash = _sha256_bytes(raw)

            # IDX-4 (supervise fc9c5829): a note whose body is empty after
            # frontmatter (49 live vault notes — placeholder dailies, plan stubs)
            # produces zero chunks, so no VaultChunkModel row and therefore no
            # content_hash is ever persisted for it. The unchanged-file skip below
            # reads its hash from those rows, so it never matched: every such note
            # was re-read, re-parsed, and burned one of the max_files re-embed slots
            # on every 2-minute tick, forever, while doing no work. Remember the
            # hash of files that legitimately yield no chunks and skip them until
            # their bytes change.
            if not force and self._empty_hashes.get(rel) == file_hash:
                continue

            # Skip unchanged files unless forced. Fix-115: a file whose chunks
            # are still NULL-embedded (embedder was down on a prior tick) is
            # re-indexed so it self-heals once the embedder recovers — the
            # unchanged-file skip would otherwise strand it dense-blind forever.
            if not force:
                existing_hash, has_null_embedding = existing.get(rel, (None, False))
                hash_matches = bool(
                    existing_hash and existing_hash.startswith(file_hash[:16])
                )
                if hash_matches and not has_null_embedding:
                    continue

            # Throttle ONLY the costly embedding work. The walk above is
            # unbounded so the entire vault is covered for change-detection on
            # every tick; capping re-embeds spreads a large backlog (e.g. a
            # first full index) across consecutive ticks instead of starving the
            # tail of the tree.
            if reindexed >= max_files:
                capped = True
                break

            files_changed += 1
            written = await self._index_file(fp, rel, raw, file_hash)
            chunks_written += written
            if written:
                self._empty_hashes.pop(rel, None)
                reindexed += 1
            else:
                # IDX-4: no chunks were produced, so no embedding work was done —
                # this file must not consume a re-embed slot (that is what starved
                # genuinely-changed files at the tail of the cap). Record the hash
                # so subsequent ticks skip it outright until the bytes change.
                self._empty_hashes[rel] = file_hash

        # Orphan sweep: remove chunks whose source file no longer exists.
        # Only run when the scan was complete (the loop did NOT hit the cap) to
        # avoid deleting chunks for files past the cap that still exist on disk.
        # Keyed on the actual break, so a vault of exactly max_files still sweeps.
        if not capped:
            async with get_session() as session:
                result = await session.execute(select(VaultChunkModel.path).distinct())
                db_paths = {p for (p,) in result.all()}
                orphans = db_paths - live_paths
                if orphans:
                    result = await session.execute(
                        delete(VaultChunkModel).where(VaultChunkModel.path.in_(orphans))
                    )
                    await session.commit()
                    # IDX-6 (supervise fc9c5829): this reported `len(orphans)` —
                    # the number of orphaned PATHS — under the name chunks_deleted,
                    # in both the log line and the /api/vault/reindex response. A
                    # sweep of 50 deleted files averaging 3 chunks each reported 50
                    # instead of ~150, so the metric understated the blast radius of
                    # every orphan sweep. Use the real rowcount, as the sibling
                    # _delete_chunks_for_path already does.
                    chunks_deleted = int(getattr(result, "rowcount", 0) or 0)
                    orphan_paths = len(orphans)
        else:
            logger.warning(
                "orphan_sweep_skipped_reembed_capped",
                scanned=scanned,
                reindexed=reindexed,
                max_files=max_files,
            )

        logger.info(
            "vault_reindex",
            scanned=scanned,
            files_changed=files_changed,
            chunks_written=chunks_written,
            chunks_deleted=chunks_deleted,
            orphan_paths=orphan_paths,
            unreadable=unreadable,
            empty_body_cached=len(self._empty_hashes),
        )
        return {
            "status": "ok",
            "scanned": scanned,
            "files_changed": files_changed,
            "chunks_written": chunks_written,
            "chunks_deleted": chunks_deleted,
            "orphan_paths": orphan_paths,
            "unreadable": unreadable,
        }

    async def _delete_chunks_for_path(self, rel: str) -> int:
        """Purge every chunk previously indexed for one vault path.

        RET-01: used by the `work` hard-drop so a note that was indexed before
        it was (re)tagged `work` does not linger in the searchable corpus.
        """
        async with get_session() as session:
            result = await session.execute(
                delete(VaultChunkModel).where(VaultChunkModel.path == rel)
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0) or 0)

    async def _index_file(self, fp: Path, rel: str, raw: bytes, file_hash: str) -> int:
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return 0
        # IDX-NUL (supervise ee392aa1): a corrupt vault file (e.g. a half-written
        # health-watchdog daily journal padded with 0x00) decodes NUL bytes into
        # text. PostgreSQL text columns cannot hold 0x00, so a single such file
        # raised DataError on the batch INSERT and aborted the ENTIRE reindex tick
        # every 2 min (silent — the scheduler wrapper caught+logged it and still
        # recorded job status=completed). Strip NUL at the decode boundary so one
        # bad file degrades to its readable text instead of breaking all indexing.
        if "\x00" in text:
            logger.warning("vault_index_nul_stripped", path=rel, nul_count=text.count("\x00"))
            text = text.replace("\x00", "")
        # IDX-2: CRLF normalization lives in _parse_frontmatter (parser boundary),
        # so `body` below is already newline-normalized for the chunker.
        fm, body = _parse_frontmatter(text)
        tags = []
        raw_tags = (fm or {}).get("tags")
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags if t]
        elif isinstance(raw_tags, str):
            tags = [raw_tags]

        # RET-01 (supervise zero 6a8c5562): the constitution's `work` hard-drop
        # had no implementation anywhere. _resolve_partition() rejects `work` as
        # a retrieval-partition OVERRIDE, and its docstring plus a test name both
        # described that as the drop — but rejecting an override only picks a
        # different bucket; the note was still chunked, embedded, stored, and
        # returned by search, frontmatter and all. Live exposure was zero when
        # this was found (0 notes and 0 chunks carrying `work`), because the
        # scope rule keeps Eightfold material in a separate vault — which is
        # exactly why it went unnoticed. This is the belt to that braces: a
        # `work` note that ever lands here is skipped, and any chunks a previous
        # pass already wrote for it are purged.
        _fm_partition = str((fm or {}).get("partition") or "").strip().lower()
        if _fm_partition == "work" or "work" in {t.strip().lower() for t in tags}:
            logger.warning("vault_index_work_partition_dropped", path=rel)
            await self._delete_chunks_for_path(rel)
            return 0

        partition = _resolve_partition((fm or {}).get("partition"), rel)

        # IDX-STAT-BLOCK (supervise 3c3ade8e): fp.stat() is a synchronous syscall
        # run up to max_files times per reindex tick inside this async method;
        # like the _iter_markdown walk (IDX-ASYNC-WALK) it must not block the loop
        # — push it off-thread so only the embedding awaits run on the event loop.
        mtime_ts = await asyncio.to_thread(lambda: fp.stat().st_mtime)
        mtime = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)

        # Split + chunk
        sections = _split_by_headings(body)
        all_chunks: list[_Chunk] = []
        global_idx = 0
        for heading_path, section_body in sections:
            for ch in _chunk_section(heading_path, section_body):
                ch.idx = global_idx
                all_chunks.append(ch)
                global_idx += 1
        if not all_chunks and body.strip() and _is_indexable(body):
            # file with no headings; treat as one chunk (IDX-7: unless the whole
            # file is boilerplate — this fallback previously re-admitted exactly
            # the stub content `_chunk_section` had just rejected).
            all_chunks = [_Chunk(idx=0, heading_path="", content=body.strip(), token_count=len(body) // 4)]

        # Fix-109: embed ALL chunks first (no session held across the embedder
        # await — see 60-database.md), then write delete+insert in ONE transaction
        # so a file is either fully reindexed or left untouched. The old per-chunk
        # commit left a half-indexed file on a mid-loop process death, and the
        # reindex-skip (any chunk row's hash) then treated it as complete forever.
        rows: list[VaultChunkModel] = []
        for chunk in all_chunks:
            embedding = await self._embed(chunk.content)
            chunk_hash = _sha256_bytes(chunk.content.encode("utf-8"))
            # content_hash per chunk stores file_hash[:16] + chunk_hash[:16] so
            # reindex-skip in reindex() can check any chunk row for the file hash.
            content_hash = file_hash[:16] + chunk_hash[:16]
            rows.append(VaultChunkModel(
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
            ))

        async with get_session() as session:
            await session.execute(delete(VaultChunkModel).where(VaultChunkModel.path == rel))
            session.add_all(rows)
            await session.commit()
        return len(rows)


_singleton: Optional[VaultIndexerService] = None


def get_vault_indexer() -> VaultIndexerService:
    global _singleton
    if _singleton is None:
        _singleton = VaultIndexerService()
    return _singleton
