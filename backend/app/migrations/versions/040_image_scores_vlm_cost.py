"""Add VLM cost + tier columns to image_scores.

Carousel V2 Stage-8 now routes through ``cheap_vlm_router`` which fans across
Kimi K2.6 (Tier 0), OpenRouter free vision pool (Tier 1), and Gemini Flash
(Tier 2). The router stamps each call's ``vlm_model`` (already exists) plus
two new fields:

  - ``vlm_cost_usd``  — per-call USD estimate (0.0 for free-tier hits)
  - ``vlm_tier``      — ``kimi`` | ``openrouter_free`` | ``gemini_paid``

These feed the Phase-6 cost-aware bandit + the daily-spend budget alert.

Safe to re-run — every ALTER is guarded by ``information_schema`` lookups.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if "image_scores" not in sa.inspect(bind).get_table_names():
        # The 039 migration was applied via Base.metadata.create_all in dev;
        # if image_scores doesn't exist the env is too far behind to upgrade.
        return

    if not _column_exists(bind, "image_scores", "vlm_cost_usd"):
        op.add_column(
            "image_scores",
            sa.Column("vlm_cost_usd", sa.Float(), nullable=True),
        )

    if not _column_exists(bind, "image_scores", "vlm_tier"):
        op.add_column(
            "image_scores",
            sa.Column("vlm_tier", sa.String(24), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    for col in ("vlm_tier", "vlm_cost_usd"):
        if _column_exists(bind, "image_scores", col):
            try:
                op.drop_column("image_scores", col)
            except Exception:  # noqa: BLE001
                pass
