"""Content pipeline hardening: retry counter, image sha256, swarm role weights, lore/quotes tables.

Supports the orchestration-hardening plan from /plans/https-claude-ai-public-artifacts-44f90ce-misty-gosling.md:
  - W3: `retries` + `rubric` columns on character_carousels
  - W4: swarm_role_weights table (per-role calibrated weight, updated by swarm_calibration job)
  - W5: character_lore_chunks + character_quotes (pgvector HNSW) for grounded retrieval
  - W6: sha256 column on character_images + media_images for byte-identical dedup
"""

from alembic import op
import sqlalchemy as sa


revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # W3: carousel retries + structured rubric
    if "character_carousels" in inspector.get_table_names():
        if not _has_column(inspector, "character_carousels", "retries"):
            op.add_column(
                "character_carousels",
                sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
            )
        if not _has_column(inspector, "character_carousels", "rubric"):
            op.add_column(
                "character_carousels",
                sa.Column("rubric", sa.dialects.postgresql.JSONB(), nullable=True),
            )

    # W6: sha256 for byte-identical image dedup
    for img_table in ("character_images", "media_images"):
        if img_table in inspector.get_table_names() and not _has_column(inspector, img_table, "sha256"):
            op.add_column(
                img_table,
                sa.Column("sha256", sa.String(64), nullable=True),
            )
            op.create_index(
                f"ix_{img_table}_sha256",
                img_table,
                ["sha256"],
            )

    # W4: swarm role weights. One row per role, updated weekly by calibration job.
    if "swarm_role_weights" not in inspector.get_table_names():
        op.create_table(
            "swarm_role_weights",
            sa.Column("role_name", sa.String(50), primary_key=True),
            sa.Column("weight", sa.Float(), nullable=False),
            sa.Column("brier_score", sa.Float(), nullable=True),
            sa.Column("rank_correlation", sa.Float(), nullable=True),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        )

    # W5: lore chunks + quotes with pgvector embedding (768 dims matches Zero's standard).
    # pgvector extension should already exist via existing migrations; ensure it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    if "character_lore_chunks" not in inspector.get_table_names():
        op.create_table(
            "character_lore_chunks",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column(
                "character_id",
                sa.String(64),
                sa.ForeignKey("characters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("source_license", sa.String(40), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunk_metadata", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        # embedding column added via raw SQL because pgvector type may not be registered yet at this point.
        op.execute("ALTER TABLE character_lore_chunks ADD COLUMN embedding vector(768)")
        op.create_index(
            "ix_lore_chunks_character",
            "character_lore_chunks",
            ["character_id"],
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_lore_chunks_embedding_hnsw "
            "ON character_lore_chunks USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 200)"
        )

    if "character_quotes" not in inspector.get_table_names():
        op.create_table(
            "character_quotes",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column(
                "character_id",
                sa.String(64),
                sa.ForeignKey("characters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("source", sa.String(100), nullable=True),
            sa.Column("source_license", sa.String(40), nullable=True),
            sa.Column("quote_metadata", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.execute("ALTER TABLE character_quotes ADD COLUMN embedding vector(768)")
        op.create_index(
            "ix_quotes_character",
            "character_quotes",
            ["character_id"],
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_quotes_embedding_hnsw "
            "ON character_quotes USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 200)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for tbl in ("character_quotes", "character_lore_chunks", "swarm_role_weights"):
        if tbl in inspector.get_table_names():
            op.drop_table(tbl)

    for img_table in ("character_images", "media_images"):
        if _has_column(inspector, img_table, "sha256"):
            try:
                op.drop_index(f"ix_{img_table}_sha256", table_name=img_table)
            except Exception:
                pass
            op.drop_column(img_table, "sha256")

    if _has_column(inspector, "character_carousels", "rubric"):
        op.drop_column("character_carousels", "rubric")
    if _has_column(inspector, "character_carousels", "retries"):
        op.drop_column("character_carousels", "retries")
