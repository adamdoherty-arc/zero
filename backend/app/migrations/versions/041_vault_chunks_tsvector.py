"""Backfill vault_chunks search infrastructure.

Migration 036 created vault_chunks with the tsvector column, HNSW index, and
unique (path, chunk_idx) constraint — but the whole block sat behind an
``if "vault_chunks" not in existing:`` guard. In environments where the table
existed before 036 ran (e.g. it was created via SQLAlchemy ``create_all`` in a
dev bring-up), the guard skipped these add-ons. Result: the table has 442
rows but no ``content_tsv`` column, so every BM25 query in
``vault_retrieval_service.search`` raises ``UndefinedColumn``.

This migration adds the missing pieces idempotently. The ``content_tsv``
column is ``GENERATED ALWAYS … STORED``, which auto-backfills from the
existing ``content`` column on creation, so no manual reindex is required.
"""

from __future__ import annotations

from alembic import op


revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All operations are idempotent. Safe to re-run.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Generated tsvector column for BM25. STORED so the GIN index is usable.
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

    # HNSW index on the existing pgvector column. Cheap when already present.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vault_chunks_embedding_hnsw "
        "ON vault_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    )

    # Unique (path, chunk_idx) so the indexer's upsert behaves correctly.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_vault_chunks_path_idx "
        "ON vault_chunks (path, chunk_idx)"
    )


def downgrade() -> None:
    # Non-destructive on the way back: keep the data, drop only what we added.
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
