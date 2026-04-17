"""Add two-stage final review fields to character_carousels.

Stage 1 (Ollama) populates `ai_review` as before. Stage 2 (Minimax M2.7 with
Kimi fallback) writes to these new columns so the two signals are preserved
independently for audit and UI display.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "character_carousels",
        sa.Column("final_review", JSONB, nullable=True),
    )
    op.add_column(
        "character_carousels",
        sa.Column("final_review_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "character_carousels",
        sa.Column("final_review_model", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("character_carousels", "final_review_model")
    op.drop_column("character_carousels", "final_review_score")
    op.drop_column("character_carousels", "final_review")
