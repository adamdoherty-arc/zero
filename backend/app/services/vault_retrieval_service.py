"""Vault Retrieval — hybrid BM25 + dense + RRF fusion with partition routing.

Each query:
  1. Embed the query via the shared LiteLLM embedder.
  2. BM25 over the tsvector column (Postgres `plainto_tsquery + ts_rank_cd`).
  3. Dense cosine over the HNSW-indexed `embedding vector(768)` column.
  4. Reciprocal Rank Fusion: combine both rankings (k=60). Journal partition gets
     an additional time-decay multiplier (0.5 ** (age_days / 30)) per SecondBrain §4.
  5. Optional partition filter so 'what did I do Monday' queries don't retrieve
     reference docs.

Returns the top-N chunks plus distinct file paths for follow-up reads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.infrastructure.ollama_client import get_llm_client

logger = structlog.get_logger(__name__)


_RRF_K = 60  # standard RRF constant


async def _embed_query(text_: str) -> Optional[list[float]]:
    try:
        client = get_llm_client()
        vec = await client.embed(text_, max_retries=1)
        if not vec:
            return None
        # Fix-93/Fix-109: reject dimension mismatches loudly. The guard dim MUST
        # track settings.embedding_dimension (the shared embedder truncates to it,
        # default 768) — a hardcoded 1024 rejected every 768-dim query vector and
        # killed dense search entirely (BM25-only). Returning None on a real
        # mismatch still degrades gracefully with a visible warning.
        expected = get_settings().embedding_dimension
        if len(vec) != expected:
            logger.warning(
                "vault_query_embed_dim_mismatch", got=len(vec), expected=expected
            )
            return None
        return vec
    except Exception as e:  # noqa: BLE001
        logger.warning("vault_query_embed_failed", error=str(e))
        return None


# --- Search-infra invariant (Fix-110) --------------------------------------
#
# Migration 056 added the BM25 ``content_tsv`` generated column + GIN index and
# the HNSW embedding index to ``vault_chunks``. But SQLAlchemy ``create_all``
# (dev bring-ups, fresh envs, some tests) recreates the table from the ORM
# model — which has NONE of these add-ons — while ``alembic_version`` stays at
# 056 so the migration never re-runs. Result (the Fix-109 outage): ``content_tsv``
# silently vanishes and EVERY vault search 500s on ``UndefinedColumn`` (the BM25
# side runs first), undetected until a query fails at runtime.
#
# ``ensure_vault_search_infra()`` re-asserts the same idempotent DDL on EVERY
# startup, healing the drift regardless of alembic state, and reports whether a
# repair was actually needed so real drift is logged LOUDLY (not silently
# fixed). Scope is the actively-queried vector-search tables. Dormant
# migration-only objects on paths no live query touches stay excluded
# (atomic_facts.content_tsv on the deprecated carousel_v2 path; the still-empty
# voiceprints/faceprints HNSW indexes — 0 rows as of 2026-06-23, KNN there is a
# no-op).
#
# IDX-EPISODIC-HNSW (fdbed9cf): episodic_memories IS now included. It crossed
# 0 -> ~1500 live rows and ``episodic_memory_service.search()`` runs an
# ``ORDER BY embedding <=> q LIMIT k`` cosine KNN on every recall (brain,
# reflection, memory_facade fan-in). No ANN index was EVER defined for it
# (migration 018 only added a btree on ``importance``; 055 only touched
# vault_chunks), so recall full-scanned + top-N-sorted all rows (verified:
# Seq Scan on 1496 rows -> Index Scan using hnsw after the fix). The repair
# below adds the missing ``ix_episodic_memories_embedding_hnsw`` so a create_all
# fresh-env keeps fast recall too.

_SEARCH_INFRA_REPAIR_SQL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    # content_tsv: GENERATED ALWAYS … STORED auto-backfills from `content`.
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'vault_chunks' AND column_name = 'content_tsv'
        ) THEN
            ALTER TABLE vault_chunks
            ADD COLUMN content_tsv tsvector
            GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED;
        END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS ix_vault_chunks_content_tsv "
    "ON vault_chunks USING gin (content_tsv)",
    "CREATE INDEX IF NOT EXISTS ix_vault_chunks_embedding_hnsw "
    "ON vault_chunks USING hnsw (embedding vector_cosine_ops) "
    "WITH (m = 16, ef_construction = 128)",
    # RET-02: de-duplicate BEFORE the unique index, or the index build fails on
    # the very drift it is meant to re-establish. Keeps the newest row per
    # (path, chunk_idx); the indexer rewrites content on the next pass anyway.
    "DELETE FROM vault_chunks a USING vault_chunks b "
    "WHERE a.ctid < b.ctid AND a.path = b.path AND a.chunk_idx = b.chunk_idx",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_vault_chunks_path_idx "
    "ON vault_chunks (path, chunk_idx)",
)

# IDX-EPISODIC-HNSW (fdbed9cf): the missing ANN index on the live episodic store.
# Gated by a detect so the build (and its log line) only fires on real drift.
_EPISODIC_HNSW_DETECT_SQL = text(
    "SELECT count(*) FROM pg_indexes WHERE tablename='episodic_memories' "
    "AND indexname='ix_episodic_memories_embedding_hnsw'"
)
_EPISODIC_HNSW_REPAIR_SQL = text(
    "CREATE INDEX IF NOT EXISTS ix_episodic_memories_embedding_hnsw "
    "ON episodic_memories USING hnsw (embedding vector_cosine_ops) "
    "WITH (m = 16, ef_construction = 128)"
)

_SEARCH_INFRA_DETECT_SQL = text(
    """
    SELECT
      (SELECT count(*) FROM information_schema.columns
         WHERE table_name='vault_chunks' AND column_name='content_tsv') AS has_tsv,
      (SELECT count(*) FROM pg_indexes
         WHERE tablename='vault_chunks' AND indexname='ix_vault_chunks_content_tsv') AS has_gin,
      (SELECT count(*) FROM pg_indexes
         WHERE tablename='vault_chunks' AND indexname='ix_vault_chunks_embedding_hnsw') AS has_hnsw
    """
)


async def search_infra_status() -> dict[str, Any]:
    """Detect-only check of the actively-queried vault search objects.

    Cheap (information_schema / pg_indexes lookups, no mutation). Used by
    /health/ready to surface create_all drift WITHOUT requiring a restart.
    ``status`` is ``critical`` when content_tsv is absent (BM25 hard-500s),
    ``degraded`` when only an index is missing (perf), else ``ok``.
    """
    async with get_session() as session:
        row = (await session.execute(_SEARCH_INFRA_DETECT_SQL)).mappings().first()
    has_tsv = bool(row and row["has_tsv"])
    missing: list[str] = []
    if not has_tsv:
        missing.append("vault_chunks.content_tsv")
    if not (row and row["has_gin"]):
        missing.append("ix_vault_chunks_content_tsv")
    if not (row and row["has_hnsw"]):
        missing.append("ix_vault_chunks_embedding_hnsw")
    status = "ok" if not missing else ("critical" if not has_tsv else "degraded")
    return {"status": status, "missing": missing, "content_tsv": has_tsv}


async def ensure_vault_search_infra() -> dict[str, Any]:
    """Idempotently (re-)assert vault_chunks BM25/HNSW search objects at startup.

    Heals the Fix-109 silent-500 class regardless of ``alembic_version``. Logs
    LOUDLY when a repair was actually needed (real drift), quietly otherwise.
    Returns ``{"healed": bool, "missing_before": [...]}``.
    """
    before = await search_infra_status()
    episodic_hnsw_created = False

    # RET-02 (supervise zero 6a8c5562): every repair statement used to share ONE
    # transaction. Postgres DDL is transactional, so a failure on the LAST
    # statement rolled back the earlier ones — including the ADD COLUMN
    # content_tsv this function exists to restore. And the last statement is
    # `CREATE UNIQUE INDEX ux_vault_chunks_path_idx`, which fails on exactly the
    # drift being healed: VaultChunkModel declares no unique constraint on
    # (path, chunk_idx), so when create_all rebuilds the table the index is gone
    # and duplicate chunk rows accumulate (the indexer documents this). With
    # duplicates present the CREATE UNIQUE INDEX raises, the whole transaction
    # rolls back, content_tsv is never created, and EVERY vault search 500s on
    # UndefinedColumn. main.py swallows the failure as a warning, so the app
    # boots with BM25 permanently dead — precisely the silent-500 class this
    # function was written to eliminate.
    #
    # Each statement now commits independently and a failure is logged and
    # stepped over, so one broken repair can no longer take the others down.
    for stmt in _SEARCH_INFRA_REPAIR_SQL:
        try:
            async with get_session() as session:
                await session.execute(text(stmt))
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "vault_search_infra.repair_stmt_failed",
                statement=stmt.split("\n")[0][:120],
                error=str(e),
                impact="this repair was skipped; the others still applied",
            )

    async with get_session() as session:
        # IDX-EPISODIC-HNSW: detect-then-create so the (potentially slow) HNSW
        # build only runs on real drift, and the log distinguishes healed vs
        # verified. On a fresh/empty env the table has 0 rows -> instant build.
        epi_has = (await session.execute(_EPISODIC_HNSW_DETECT_SQL)).scalar()
        if not epi_has:
            await session.execute(_EPISODIC_HNSW_REPAIR_SQL)
            episodic_hnsw_created = True
        await session.commit()
    if episodic_hnsw_created:
        logger.warning(
            "episodic_search_infra.hnsw_created",
            impact="episodic_memories KNN recall was full-scanning embedding; "
                   "ix_episodic_memories_embedding_hnsw added (never migration-defined)",
        )
    missing_before = before["missing"]
    if "vault_chunks.content_tsv" in missing_before:
        logger.error(
            "vault_search_infra.CRITICAL_drift_healed",
            missing=missing_before,
            impact="content_tsv was absent -> BM25 vault search would 500 on UndefinedColumn",
            root_cause="ORM create_all recreated vault_chunks without migration-only objects (alembic stayed at 056)",
        )
    elif missing_before:
        logger.warning("vault_search_infra.drift_healed", missing=missing_before)
    else:
        logger.info("vault_search_infra.verified")
    return {
        "healed": bool(missing_before) or episodic_hnsw_created,
        "missing_before": missing_before,
        "episodic_hnsw_created": episodic_hnsw_created,
    }


class VaultRetrievalService:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def search(
        self,
        query: str,
        *,
        partitions: Optional[list[str]] = None,
        top_k: int = 10,
        per_side_k: int = 40,
    ) -> dict[str, Any]:
        """Hybrid BM25 + dense search with RRF fusion.

        partitions: optional list in {reference, projects, journal, inbox}. Empty = all.
        """
        embedding = await _embed_query(query)

        part_filter_sql = ""
        params: dict[str, Any] = {"q": query, "k": per_side_k}
        if partitions:
            params["partitions"] = list(partitions)
            part_filter_sql = "AND partition = ANY(:partitions)"

        # BM25 side
        bm25_sql = text(
            f"""
            SELECT id, path, partition, heading_path, chunk_idx, content, file_mtime,
                   ts_rank_cd(content_tsv, plainto_tsquery('english', :q)) AS rank
              FROM vault_chunks
             WHERE content_tsv @@ plainto_tsquery('english', :q)
               {part_filter_sql}
             ORDER BY rank DESC
             LIMIT :k
            """
        )

        # Dense side (only if we got an embedding)
        dense_rows: list[dict[str, Any]] = []
        async with get_session() as session:
            bm25_rows = (await session.execute(bm25_sql, params)).mappings().all()
            bm25_rows = [dict(r) for r in bm25_rows]

            if embedding is not None:
                dense_sql = text(
                    f"""
                    SELECT id, path, partition, heading_path, chunk_idx, content, file_mtime,
                           1 - (embedding <=> (:emb)::vector) AS cosine_sim
                      FROM vault_chunks
                     WHERE embedding IS NOT NULL
                       {part_filter_sql}
                     ORDER BY embedding <=> (:emb)::vector
                     LIMIT :k
                    """
                )
                dense_params = dict(params)
                dense_params["emb"] = str(embedding)
                dense_rows = [dict(r) for r in (await session.execute(dense_sql, dense_params)).mappings().all()]

        # RRF fuse
        scores: dict[str, dict[str, Any]] = {}
        for rank, row in enumerate(bm25_rows, start=1):
            sid = row["id"]
            scores.setdefault(sid, {"row": row, "bm25": 0.0, "dense": 0.0})
            scores[sid]["bm25"] += 1.0 / (_RRF_K + rank)
        for rank, row in enumerate(dense_rows, start=1):
            sid = row["id"]
            scores.setdefault(sid, {"row": row, "bm25": 0.0, "dense": 0.0})
            scores[sid]["dense"] += 1.0 / (_RRF_K + rank)

        now = datetime.now(timezone.utc)
        fused = []
        for sid, agg in scores.items():
            row = agg["row"]
            raw = agg["bm25"] + agg["dense"]
            # Journal time-decay only.
            if row["partition"] == "journal" and row.get("file_mtime"):
                mtime = row["file_mtime"]
                if isinstance(mtime, datetime):
                    age_days = max(0.0, (now - mtime).total_seconds() / 86400.0)
                    raw *= 0.5 ** (age_days / 30.0)
            fused.append((raw, row))
        fused.sort(key=lambda t: t[0], reverse=True)

        results = []
        for score, row in fused[:top_k]:
            results.append(
                {
                    "id": row["id"],
                    "path": row["path"],
                    "partition": row["partition"],
                    "heading_path": row.get("heading_path"),
                    "chunk_idx": row["chunk_idx"],
                    "content": (row["content"] or "")[:1200],
                    "score": round(float(score), 6),
                }
            )

        # Distinct paths for file-level follow-up
        distinct_paths: list[str] = []
        seen: set[str] = set()
        for r in results:
            if r["path"] not in seen:
                distinct_paths.append(r["path"])
                seen.add(r["path"])

        return {
            "query": query,
            "partitions": partitions or ["reference", "projects", "journal", "inbox"],
            "top_k": top_k,
            "hits": results,
            "paths": distinct_paths,
            "bm25_count": len(bm25_rows),
            "dense_count": len(dense_rows),
            "dense_enabled": embedding is not None,
        }

    async def get_file(self, path: str) -> dict[str, Any]:
        """Return the assembled markdown for a given vault path by concatenating its chunks."""
        async with get_session() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT heading_path, content, chunk_idx, frontmatter, tags, partition, file_mtime
                          FROM vault_chunks
                         WHERE path = :p
                         ORDER BY chunk_idx ASC
                        """
                    ),
                    {"p": path},
                )
            ).mappings().all()
        if not rows:
            return {"path": path, "exists": False}
        first = rows[0]
        # Reassemble content preserving order. This is a best-effort view, not authoritative.
        body = "\n\n".join(r["content"] for r in rows)
        return {
            "path": path,
            "exists": True,
            "partition": first["partition"],
            "frontmatter": first.get("frontmatter"),
            "tags": list(first.get("tags") or []),
            "file_mtime": first["file_mtime"].isoformat() if first["file_mtime"] else None,
            "chunk_count": len(rows),
            "content": body,
        }


_singleton: Optional[VaultRetrievalService] = None


def get_vault_retrieval() -> VaultRetrievalService:
    global _singleton
    if _singleton is None:
        _singleton = VaultRetrievalService()
    return _singleton
