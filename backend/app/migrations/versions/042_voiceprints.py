"""Voice fingerprints for cross-meeting speaker recognition.

Adds the ``voiceprints`` table — one row per persistent identity with a
256-dim pgvector embedding. The meeting processing pipeline computes the
centroid embedding for each diarized cluster and replaces the relative
``SPEAKER_XX`` label with the matched ``display_name`` when cosine
similarity exceeds the configured threshold.
"""

from __future__ import annotations

from alembic import op


revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS voiceprints (
            id SERIAL PRIMARY KEY,
            display_name VARCHAR(200) NOT NULL UNIQUE,
            embedding vector(256) NOT NULL,
            samples_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            source_meeting_id VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_voiceprints_embedding_hnsw "
        "ON voiceprints USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # Only one row may carry is_primary=TRUE.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_voiceprints_one_primary "
        "ON voiceprints (is_primary) WHERE is_primary = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_voiceprints_one_primary")
    op.execute("DROP INDEX IF EXISTS ix_voiceprints_embedding_hnsw")
    op.execute("DROP TABLE IF EXISTS voiceprints")
