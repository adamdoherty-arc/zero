"""Add image quality feedback fields to character_images.

Adds quality_score, content_type, file_size, is_approved, feedback_reason,
and validated_at columns for image validation and feedback loop.
"""

from alembic import op
import sqlalchemy as sa


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("character_images", sa.Column("quality_score", sa.Float, server_default="0.0"))
    op.add_column("character_images", sa.Column("content_type", sa.String(50)))
    op.add_column("character_images", sa.Column("file_size", sa.Integer))
    op.add_column("character_images", sa.Column("is_approved", sa.Boolean))
    op.add_column("character_images", sa.Column("feedback_reason", sa.Text))
    op.add_column("character_images", sa.Column("validated_at", sa.DateTime(timezone=True)))

    op.create_index(
        "idx_char_img_quality",
        "character_images",
        ["character_id", "quality_score"],
    )


def downgrade() -> None:
    op.drop_index("idx_char_img_quality", table_name="character_images")
    op.drop_column("character_images", "validated_at")
    op.drop_column("character_images", "feedback_reason")
    op.drop_column("character_images", "is_approved")
    op.drop_column("character_images", "file_size")
    op.drop_column("character_images", "content_type")
    op.drop_column("character_images", "quality_score")
