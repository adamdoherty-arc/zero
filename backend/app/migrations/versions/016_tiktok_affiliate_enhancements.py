"""Add TikTok affiliate marketing enhancements: carousel, manual posting, performance tracking

Revision ID: 016_tiktok_affiliate
Revises: 015_ai_company
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '016_tiktok_affiliate'
down_revision = '015_ai_company'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Content queue: video URL, carousel, manual posting, performance
    op.add_column('content_queue', sa.Column('video_url', sa.Text(), nullable=True))
    op.add_column('content_queue', sa.Column('content_format', sa.String(20), server_default='video', nullable=False))
    op.add_column('content_queue', sa.Column('carousel_data', JSONB, nullable=True))
    op.add_column('content_queue', sa.Column('manually_published_url', sa.Text(), nullable=True))
    op.add_column('content_queue', sa.Column('performance_views', sa.Integer(), nullable=True))
    op.add_column('content_queue', sa.Column('performance_likes', sa.Integer(), nullable=True))
    op.add_column('content_queue', sa.Column('performance_comments', sa.Integer(), nullable=True))
    op.add_column('content_queue', sa.Column('performance_shares', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('content_queue', 'performance_shares')
    op.drop_column('content_queue', 'performance_comments')
    op.drop_column('content_queue', 'performance_likes')
    op.drop_column('content_queue', 'performance_views')
    op.drop_column('content_queue', 'manually_published_url')
    op.drop_column('content_queue', 'carousel_data')
    op.drop_column('content_queue', 'content_format')
    op.drop_column('content_queue', 'video_url')
