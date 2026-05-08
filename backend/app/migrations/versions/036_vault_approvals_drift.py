"""Vault chunks + agent approvals + drift alerts for SecondBrain phases 2/3/5.

Creates three tables that together make the vault queryable, gate external-side-effect
tool calls behind human approval, and surface cross-domain drift for the weekly review.

- `vault_chunks`: markdown chunks indexed from the Obsidian vault at /vault. Partitioned
  logically by path prefix (reference | projects | journal | inbox) so retrieval can
  apply time-decay only to the journal partition per SecondBrain §4.

- `agent_approvals`: queued tool calls requiring human approval before execution
  (write_external, financial). Referenced by the attention-economy middleware and by
  the /agent page ApprovalQueue component.

- `agent_alerts`: output of the nightly drift scanner (SecondBrain §6). Six SQL rules
  emit rows here; the weekly review reads them.

Safe to re-run — every create is guarded by `if not exists`.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)

    # pgvector is required. Already created in migration 001, but re-assert idempotently.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- vault_chunks --------------------------------------------------------------
    if "vault_chunks" not in existing:
        op.create_table(
            "vault_chunks",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("path", sa.Text(), nullable=False, index=True),
            # partition drives retrieval: reference | projects | journal | inbox
            sa.Column("partition", sa.String(20), nullable=False, index=True),
            sa.Column("chunk_idx", sa.Integer(), nullable=False),
            sa.Column("heading_path", sa.Text(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False, index=True),
            sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tags", pg.ARRAY(sa.Text()), server_default="{}"),
            sa.Column("frontmatter", pg.JSONB(), nullable=True),
            sa.Column("embedding", pg.ARRAY(sa.Float()), nullable=True),  # placeholder
            sa.Column("file_mtime", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        # Replace ARRAY(float) with a proper pgvector column post-create.
        # Dimension 1024 matches Qwen3-Embedding full-dim (Matryoshka can truncate).
        op.execute("ALTER TABLE vault_chunks DROP COLUMN embedding")
        op.execute("ALTER TABLE vault_chunks ADD COLUMN embedding vector(1024)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_vault_chunks_embedding_hnsw "
            "ON vault_chunks USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 128)"
        )
        # Hybrid search: tsvector column for BM25 side of RRF fusion.
        op.execute("ALTER TABLE vault_chunks ADD COLUMN content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED")
        op.execute("CREATE INDEX IF NOT EXISTS ix_vault_chunks_content_tsv ON vault_chunks USING gin (content_tsv)")
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_vault_chunks_path_idx "
            "ON vault_chunks (path, chunk_idx)"
        )

    # --- agent_approvals -----------------------------------------------------------
    if "agent_approvals" not in existing:
        op.create_table(
            "agent_approvals",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tool_name", sa.String(200), nullable=False, index=True),
            sa.Column("tier", sa.String(20), nullable=False, index=True),  # read|write_local|write_external|financial
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("arguments", pg.JSONB(), nullable=False),
            sa.Column("requested_by", sa.String(100), nullable=False),  # e.g. supervisor, pkm, legion_ops
            sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
            # pending | approved | rejected | expired | executed | failed
            sa.Column("decision_reason", sa.Text(), nullable=True),
            sa.Column("decided_by", sa.String(100), nullable=True),  # user | agent | circuit_breaker
            sa.Column("result", pg.JSONB(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_agent_approvals_created",
            "agent_approvals",
            ["created_at"],
        )

    # --- agent_alerts --------------------------------------------------------------
    if "agent_alerts" not in existing:
        op.create_table(
            "agent_alerts",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("rule", sa.String(100), nullable=False, index=True),
            sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
            sa.Column("salience", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("entity_type", sa.String(50), nullable=True),  # project, task, topic, ...
            sa.Column("entity_id", sa.String(100), nullable=True, index=True),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("details", pg.JSONB(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
            # open | acknowledged | resolved | dismissed
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("interrupted_user", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("interrupted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_agent_alerts_created",
            "agent_alerts",
            ["created_at"],
        )


def downgrade() -> None:
    # Keep destructive — vault_chunks can be rebuilt from source markdown.
    for table in ("agent_alerts", "agent_approvals", "vault_chunks"):
        try:
            op.drop_table(table)
        except Exception:  # noqa: BLE001
            pass
