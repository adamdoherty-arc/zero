"""056 repair vault_chunks search infrastructure (content_tsv + indexes)

Migration 041 already added the BM25 ``content_tsv`` generated column, the GIN
index, the HNSW embedding index, and the unique (path, chunk_idx) index — but
the live ``vault_chunks`` table was subsequently recreated from the ORM models
(via SQLAlchemy ``create_all`` in a dev bring-up), which has none of those
add-ons. alembic still records 041 as applied, so it never re-runs. Result:
``vault_retrieval_service.search`` raised ``UndefinedColumn: content_tsv`` on
EVERY query — vault search was fully 500ing (BM25 side runs first), not even
BM25-only. (Surfaced by Fix-109 after the dim fix repopulated dense embeddings.)

Re-add every piece idempotently (safe to re-run; all IF NOT EXISTS / DO $$
guards). The ``content_tsv`` column is GENERATED ALWAYS … STORED so it
auto-backfills from the existing ``content`` column — no reindex required.

Revision ID: 056
Revises: 055
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Generated tsvector column for BM25. STORED so the GIN index is usable;
    # auto-backfills from `content` on creation.
    op.execute(
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
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vault_chunks_content_tsv "
        "ON vault_chunks USING gin (content_tsv)"
    )

    # HNSW index on the 768-dim pgvector column (cheap if already present).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vault_chunks_embedding_hnsw "
        "ON vault_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    )

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_vault_chunks_path_idx "
        "ON vault_chunks (path, chunk_idx)"
    )


def downgrade() -> None:
    # Non-destructive: drop only the add-ons, keep the row data.
    op.execute("DROP INDEX IF EXISTS ux_vault_chunks_path_idx")
    op.execute("DROP INDEX IF EXISTS ix_vault_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_vault_chunks_content_tsv")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'vault_chunks' AND column_name = 'content_tsv'
            ) THEN
                ALTER TABLE vault_chunks DROP COLUMN content_tsv;
            END IF;
        END $$;
        """
    )
