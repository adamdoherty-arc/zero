"""
Re-embed a pgvector column (or Qdrant collection) using the currently-configured
LOCAL_LLM_BACKEND. For the nomic-embed → Qwen3-Embedding migration when
switching Zero to vLLM.

Zero stores embeddings in Postgres/pgvector across several tables. This script
operates on ONE (table, id_col, text_col, embedding_col) at a time.

Usage:
    python scripts/reembed_vectors.py \\
        --table memory_chunks --id-col id --text-col content --embedding-col embedding

Creates a new column `<embedding_col>__reembedded` populated with the new
vectors. Swap atomically afterwards:
    ALTER TABLE memory_chunks DROP COLUMN embedding;
    ALTER TABLE memory_chunks RENAME COLUMN embedding__reembedded TO embedding;
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import httpx  # noqa: E402
import asyncpg  # noqa: E402


def _embed_endpoint() -> tuple[str, str, str]:
    """(url, model, api_key)"""
    backend = os.getenv("LOCAL_LLM_BACKEND", "ollama").lower()
    if backend == "vllm":
        url = os.getenv("VLLM_EMBED_BASE_URL", "http://localhost:8001/v1").rstrip("/")
        model = os.getenv("VLLM_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
        api_key = os.getenv("VLLM_API_KEY", "EMPTY") or "EMPTY"
    else:
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
        url = base
        model = os.getenv("OLLAMA_EMBEDDINGS_MODEL", "nomic-embed-text-v2-moe")
        api_key = os.getenv("OLLAMA_API_KEY", "ollama")
    return url, model, api_key


async def _embed_batch(http: httpx.AsyncClient, url: str, model: str, api_key: str, texts: list[str]) -> list[list[float]]:
    resp = await http.post(
        f"{url}/embeddings",
        json={"model": model, "input": texts},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    resp.raise_for_status()
    data = resp.json()
    return [row["embedding"] for row in data["data"]]


async def reembed(
    table: str,
    id_col: str,
    text_col: str,
    embedding_col: str,
    new_col: str,
    batch_size: int,
    limit: int | None,
) -> tuple[int, int]:
    dsn = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("POSTGRES_URL / DATABASE_URL not set")

    url, model, api_key = _embed_endpoint()
    print(f"[reembed] embed_url={url} model={model}")

    conn = await asyncpg.connect(dsn)
    try:
        # Probe vector size.
        async with httpx.AsyncClient(timeout=60.0) as http:
            probe = await _embed_batch(http, url, model, api_key, ["probe"])
            vec_size = len(probe[0])
        print(f"[reembed] Target vector size: {vec_size}")

        # Add the new column if it doesn't exist. pgvector type literal.
        await conn.execute(
            f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{new_col}" vector({vec_size})'
        )

        processed = 0
        skipped = 0
        last_id: Any = None

        async with httpx.AsyncClient(timeout=120.0) as http:
            while True:
                if last_id is None:
                    rows = await conn.fetch(
                        f'SELECT "{id_col}" AS _id, "{text_col}" AS _txt '
                        f'FROM {table} '
                        f'WHERE "{new_col}" IS NULL AND "{text_col}" IS NOT NULL '
                        f'ORDER BY "{id_col}" ASC LIMIT $1',
                        batch_size,
                    )
                else:
                    rows = await conn.fetch(
                        f'SELECT "{id_col}" AS _id, "{text_col}" AS _txt '
                        f'FROM {table} '
                        f'WHERE "{new_col}" IS NULL AND "{text_col}" IS NOT NULL '
                        f'AND "{id_col}" > $1 '
                        f'ORDER BY "{id_col}" ASC LIMIT $2',
                        last_id, batch_size,
                    )
                if not rows:
                    break

                ids = [r["_id"] for r in rows]
                texts = [r["_txt"] for r in rows]
                vectors = await _embed_batch(http, url, model, api_key, texts)

                async with conn.transaction():
                    for rid, vec in zip(ids, vectors):
                        await conn.execute(
                            f'UPDATE {table} SET "{new_col}" = $1 WHERE "{id_col}" = $2',
                            vec, rid,
                        )
                processed += len(rows)
                last_id = ids[-1]
                print(f"[reembed] processed={processed}")
                if limit and processed >= limit:
                    break

        return processed, skipped
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--id-col", default="id")
    ap.add_argument("--text-col", default="content")
    ap.add_argument("--embedding-col", default="embedding")
    ap.add_argument("--new-col", default=None, help="Default: <embedding_col>__reembedded")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    new_col = args.new_col or f"{args.embedding_col}__reembedded"
    backend = os.getenv("LOCAL_LLM_BACKEND", "ollama")
    print(f"[reembed] backend={backend} table={args.table} old={args.embedding_col} new={new_col}")
    processed, skipped = asyncio.run(
        reembed(args.table, args.id_col, args.text_col, args.embedding_col, new_col, args.batch_size, args.limit)
    )
    print(f"[reembed] DONE processed={processed} skipped={skipped}")


if __name__ == "__main__":
    main()
