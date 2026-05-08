"""Vault Retrieval — hybrid BM25 + dense + RRF fusion with partition routing.

Each query:
  1. Embed the query via the shared LiteLLM embedder.
  2. BM25 over the tsvector column (Postgres `plainto_tsquery + ts_rank_cd`).
  3. Dense cosine over the HNSW-indexed `embedding vector(1024)` column.
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
        if len(vec) > 1024:
            vec = vec[:1024]
        elif len(vec) < 1024:
            vec = vec + [0.0] * (1024 - len(vec))
        return vec
    except Exception as e:  # noqa: BLE001
        logger.warning("vault_query_embed_failed", error=str(e))
        return None


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
