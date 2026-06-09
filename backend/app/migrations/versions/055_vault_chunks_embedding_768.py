"""055 vault_chunks.embedding 1024 -> 768 (align to global text embedder)

The shared text embedder produces ``settings.embedding_dimension`` (768) and
every sibling text-embedding table (notes, user_facts, episodic_memories,
meeting_transcript_segments, research_findings, character_*, content_examples,
tiktok_products) is ``vector(768)``. ``vault_chunks`` was a stale ``vector(1024)``
outlier from an earlier embedder era — so every new 768-dim embed was rejected
by the indexer/retrieval dim guards and stored NULL, silently degrading dense
vault retrieval to BM25-only (324/1267 chunks already NULL, growing on every
reindex). The 943 legacy 1024-dim rows were ALSO unqueryable: the 768 query
embedder can't compare against 1024-dim stored vectors, and the query guard
rejected the 768 query vector first.

Null the dead 1024-dim vectors (lossless — they were never retrievable) and
re-shape the column to 768. A force reindex repopulates embeddings at 768; the
matching guard fix (vault_indexer_service / vault_retrieval_service, Fix-109)
now uses settings.embedding_dimension instead of the hardcoded 1024.

Revision ID: 055
Revises: 054
Create Date: 2026-06-09
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the HNSW index first: pgvector forbids changing a vector column's
    # dimension typmod while an opclass (HNSW/ivfflat) index references it, so a
    # fresh 036->...->055 bootstrap (where 036/041 created the index on the 1024
    # column) would otherwise error here. Migration 056 re-creates the index
    # against the 768 column with IF NOT EXISTS. DROP IF EXISTS is a harmless
    # no-op on the already-migrated live DB.
    op.execute("DROP INDEX IF EXISTS ix_vault_chunks_embedding_hnsw")
    # Clear the dead 1024-dim vectors first so the type change has no data to
    # convert, then re-shape the column to match the 768 global text embedder.
    op.execute("UPDATE vault_chunks SET embedding = NULL")
    op.execute("ALTER TABLE vault_chunks ALTER COLUMN embedding TYPE vector(768)")


def downgrade() -> None:
    # Symmetric: drop the index before reverting the dimension typmod.
    op.execute("DROP INDEX IF EXISTS ix_vault_chunks_embedding_hnsw")
    op.execute("UPDATE vault_chunks SET embedding = NULL")
    op.execute("ALTER TABLE vault_chunks ALTER COLUMN embedding TYPE vector(1024)")
